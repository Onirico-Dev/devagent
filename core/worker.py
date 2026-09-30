import inspect
from dataclasses import dataclass
from typing import Any

from core.observation import Observation
from core.observer import Observer
from core.worker_state_store import WorkerStateStore
from core.autonomy_policy import AutonomyDecision, AutonomyPolicy
from core.schemas.models import Plan
from core.feedback_handler import FeedbackHandler


@dataclass(frozen=True)
class Proposal:
    instruction: str
    approval_id: str
    status: str
    plan: dict[str, Any]
    autonomy_decision: str = AutonomyDecision.REQUIRE_HUMAN.value


class _ObservationAlreadyProcessed(Exception):
    """Sinal interno para concorrência entre Workers."""

class Worker:
    """
    Processa cada observação uma única vez e cria propostas no Gateway.

    O Worker deliberadamente NÃO chama approve() nem execute_approved().
    A transição para execução continua sob controle humano.

    Falhas individuais durante uma rodada são isoladas: a observação com
    falha permanece não processada para nova tentativa futura, enquanto
    as demais observações da rodada continuam sendo processadas.

    O estado processado pode ser persistido opcionalmente por meio de
    WorkerStateStore.

    Propostas pendentes equivalentes não são duplicadas. Quando uma
    observação corresponde a uma proposta já pendente, a proposta
    existente é reutilizada e a observação passa a ser considerada
    processada.
    """

    def __init__(
        self,
        gateway,
        observer: Observer,
        store: WorkerStateStore | None = None,
        autonomy_policy: AutonomyPolicy | None = None,
        feedback_handler: FeedbackHandler | None = None,
    ):
        if gateway is None:
            raise ValueError("Gateway inválido.")
        if not isinstance(observer, Observer):
            raise ValueError("Observer inválido.")
        if store is not None and not isinstance(store, WorkerStateStore):
            raise ValueError("Store do Worker inválido.")

        self.gateway = gateway
        self.observer = observer
        self.store = store
        self.autonomy_policy = autonomy_policy
        self.feedback_handler = feedback_handler or FeedbackHandler()
        self._processed: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self._processed_ids: set[str] = set()
        self._processed_observations: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            Observation,
        ] = {}
        self._retry_instructions: set[str] = set()
        self._errors: list[dict[str, str]] = []

        if self.store is not None:
            state = self.store.load()
            if state:
                self.restore_state(state, persist=False)

    @staticmethod
    def _metadata_key(
        metadata: dict[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (str(key), repr(value))
                for key, value in metadata.items()
            )
        )

    @classmethod
    def _observation_key(
        cls,
        observation: Observation,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        return (
            observation.instruction.strip(),
            cls._metadata_key(observation.metadata),
        )

    @staticmethod
    def _normalize_instruction(instruction: str) -> str:
        return " ".join(instruction.split())

    def _persist_state(self) -> None:
        if self.store is None:
            return

        state = self.export_state()

        def merge(current: dict[str, Any]) -> dict[str, Any]:
            processed = list(current.get("processed", []))
            processed_ids = set(current.get("processed_ids", []))

            existing = {
                (
                    item.get("instruction"),
                    self._metadata_key(item.get("metadata", {})),
                )
                for item in processed
                if isinstance(item, dict)
            }

            for item in state["processed"]:
                key = (
                    item["instruction"],
                    self._metadata_key(item["metadata"]),
                )
                if key not in existing:
                    processed.append(item)
                    existing.add(key)

            processed_ids.update(state["processed_ids"])

            processed.sort(
                key=lambda item: (
                    item["instruction"],
                    self._metadata_key(item["metadata"]),
                )
            )

            retry_instructions = set(current.get("retry_instructions", []))
            retry_instructions.update(state["retry_instructions"])

            result = {
                "processed": processed,
                "processed_ids": sorted(processed_ids),
            }

            if retry_instructions:
                result["retry_instructions"] = sorted(retry_instructions)

            return result

        self.store.update(merge)

    def _create_feedback_task(
        self,
        instruction: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        create_task = self.gateway.create_task

        try:
            parameters = inspect.signature(create_task).parameters
        except (TypeError, ValueError):
            parameters = {}

        if "context" in parameters:
            return create_task(
                instruction,
                context=context,
            )

        return create_task(instruction)

    def _find_pending_proposal(
        self,
        instruction: str,
    ) -> Proposal | None:
        list_pending = getattr(self.gateway, "list_pending", None)
        if not callable(list_pending):
            return None

        pending_tasks = list_pending()
        normalized_instruction = self._normalize_instruction(instruction)

        for task in pending_tasks:
            if not isinstance(task, dict):
                continue

            task_instruction = task.get("instruction")
            if not isinstance(task_instruction, str):
                continue

            if (
                self._normalize_instruction(task_instruction)
                != normalized_instruction
            ):
                continue

            approval_id = task.get(
                "approval_id",
                task.get("task_id"),
            )
            if not isinstance(approval_id, str) or not approval_id:
                continue

            plan = task.get("plan")
            if not isinstance(plan, dict):
                continue

            return Proposal(
                instruction=task_instruction.strip(),
                approval_id=approval_id,
                status=str(task.get("status", "pending")),
                plan=dict(plan),
            )

        return None

    def _mark_processed(
        self,
        key: tuple[str, tuple[tuple[str, str], ...]],
        observation: Observation,
        approval_id: str,
    ) -> None:
        self._processed.add(key)
        self._processed_ids.add(approval_id)
        self._processed_observations[key] = Observation(
            instruction=observation.instruction.strip(),
            metadata=dict(observation.metadata),
        )

    def _persist_processed_state(self, operation) -> None:
        processed = set(self._processed)
        processed_ids = set(self._processed_ids)
        processed_observations = dict(self._processed_observations)

        try:
            operation()
            self._persist_state()
        except Exception:
            self._processed = processed
            self._processed_ids = processed_ids
            self._processed_observations = processed_observations
            raise

    def process_observation(
        self,
        observation: Observation,
        allow_retry: bool = False,
    ) -> Proposal:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        instruction = observation.instruction.strip()

        if not instruction:
            raise ValueError(
                "A instrução da observação não pode ser vazia."
            )

        key = self._observation_key(observation)

        if key in self._processed and not allow_retry:
            raise ValueError("Observação já processada.")

        if self.store is None:
            return self._process_observation_unlocked(
                observation,
                key,
                instruction,
            )

        result_holder: dict[str, Any] = {}

        def atomic_process(current: dict[str, Any]) -> dict[str, Any]:
            processed = list(current.get("processed", []))
            processed_ids = set(current.get("processed_ids", []))

            if allow_retry:
                processed = [
                    item
                    for item in processed
                    if not (
                        isinstance(item, dict)
                        and item.get("instruction") == instruction
                        and self._metadata_key(
                            item.get("metadata", {})
                        )
                        == self._metadata_key(observation.metadata)
                    )
                ]

            existing_keys = {
                (
                    item.get("instruction"),
                    self._metadata_key(item.get("metadata", {})),
                )
                for item in processed
                if isinstance(item, dict)
            }

            if key in existing_keys:
                raise _ObservationAlreadyProcessed()

            existing = self._find_pending_proposal(instruction)

            if existing is not None:
                approval_id = existing.approval_id
                result_holder["proposal"] = existing
            else:
                result = self.gateway.create_task(instruction)
                approval_id = result["approval_id"]
                result_holder["result"] = result

            processed.append(
                {
                    "instruction": instruction,
                    "metadata": dict(observation.metadata),
                }
            )
            processed_ids.add(approval_id)

            processed.sort(
                key=lambda item: (
                    item["instruction"],
                    self._metadata_key(item["metadata"]),
                )
            )

            return {
                "processed": processed,
                "processed_ids": sorted(processed_ids),
            }

        try:
            self.store.update(atomic_process)
        except _ObservationAlreadyProcessed:
            raise ValueError("Observação já processada.")

        self._mark_processed(
            key=key,
            observation=observation,
            approval_id=(
                result_holder["proposal"].approval_id
                if "proposal" in result_holder
                else result_holder["result"]["approval_id"]
            ),
        )

        if "proposal" in result_holder:
            return result_holder["proposal"]

        result = result_holder["result"]
        autonomy_decision = AutonomyDecision.REQUIRE_HUMAN.value

        if self.autonomy_policy is not None:
            plan = dict(result["plan"])
            plan.setdefault("objective", instruction)
            normalized_changes = []

            for change in plan.get("changes", []):
                change = dict(change)

                if (
                    "change_type" not in change
                    and "type" in change
                ):
                    change["change_type"] = str(
                        change.pop("type")
                    ).lower()

                normalized_changes.append(change)

            plan["changes"] = normalized_changes
            plan_object = Plan.from_dict(plan)
            autonomy_decision = self.autonomy_policy.evaluate(
                plan_object
            ).value

        return Proposal(
            instruction=instruction,
            approval_id=result["approval_id"],
            status=result["status"],
            plan=result["plan"],
            autonomy_decision=autonomy_decision,
        )

    def _process_observation_unlocked(
        self,
        observation: Observation,
        key: tuple[str, tuple[tuple[str, str], ...]],
        instruction: str,
    ) -> Proposal:
        existing = self._find_pending_proposal(instruction)

        if existing is not None:
            self._mark_processed(
                key=key,
                observation=observation,
                approval_id=existing.approval_id,
            )

            try:
                self._persist_state()
            except Exception:
                self._processed.discard(key)
                self._processed_ids.discard(existing.approval_id)
                self._processed_observations.pop(key, None)
                raise

            return existing

        result = self.gateway.create_task(instruction)
        approval_id = result["approval_id"]

        self._mark_processed(
            key=key,
            observation=observation,
            approval_id=approval_id,
        )

        try:
            self._persist_state()
        except Exception:
            self._processed.discard(key)
            self._processed_ids.discard(approval_id)
            self._processed_observations.pop(key, None)
            raise

        autonomy_decision = AutonomyDecision.REQUIRE_HUMAN.value

        if self.autonomy_policy is not None:
            plan = dict(result["plan"])
            plan.setdefault("objective", instruction)
            normalized_changes = []

            for change in plan.get("changes", []):
                change = dict(change)

                if (
                    "change_type" not in change
                    and "type" in change
                ):
                    change["change_type"] = str(
                        change.pop("type")
                    ).lower()

                normalized_changes.append(change)

            plan["changes"] = normalized_changes
            plan_object = Plan.from_dict(plan)
            autonomy_decision = self.autonomy_policy.evaluate(
                plan_object
            ).value

        return Proposal(
            instruction=instruction,
            approval_id=approval_id,
            status=result["status"],
            plan=result["plan"],
            autonomy_decision=autonomy_decision,
        )

    def run_once(self) -> list[Proposal]:
        proposals = []
        self._errors = []

        for observation in self.observer.observe():
            key = self._observation_key(observation)
            instruction = observation.instruction.strip()
            retry_allowed = instruction in self._retry_instructions

            if key in self._processed and not retry_allowed:
                continue

            try:
                if observation.metadata.get("source") == "transaction_result":
                    feedback_result = self.feedback_handler.handle(observation)

                    analysis = feedback_result.get("analysis", {})
                    if isinstance(analysis, dict):
                        status = analysis.get("status")
                        evidence = analysis.get("evidence", {})

                        if status in {"rolled_back", "failed"} and isinstance(evidence, dict):
                            transaction_metadata = evidence.get(
                                "transaction_metadata",
                                {},
                            )

                            if isinstance(transaction_metadata, dict):
                                failed_instruction = transaction_metadata.get(
                                    "instruction"
                                )

                                if (
                                    isinstance(failed_instruction, str)
                                    and failed_instruction.strip()
                                ):
                                    failed_instruction = failed_instruction.strip()

                                    repair_cycle = transaction_metadata.get(
                                        "repair_cycle",
                                        {},
                                    )

                                    retry_exhausted = False
                                    if isinstance(repair_cycle, dict):
                                        remaining = repair_cycle.get("remaining")
                                        attempts = repair_cycle.get("attempts")
                                        max_attempts = repair_cycle.get("max_attempts")

                                        retry_exhausted = (
                                            remaining == 0
                                            or (
                                                isinstance(attempts, int)
                                                and isinstance(max_attempts, int)
                                                and attempts >= max_attempts
                                            )
                                        )

                                    if not retry_exhausted:
                                        self._retry_instructions.add(
                                            failed_instruction
                                        )
                                        self._persist_state()

                                        retry_keys = {
                                            processed_key
                                            for processed_key, processed_observation
                                            in self._processed_observations.items()
                                            if (
                                                processed_observation.instruction.strip()
                                                == failed_instruction
                                            )
                                        }
                                        for retry_key in retry_keys:
                                            self._processed.discard(retry_key)
                                            self._processed_observations.pop(
                                                retry_key,
                                                None,
                                            )


                    proposal_data = feedback_result.get("proposal")

                    if proposal_data is not None:
                        if not isinstance(proposal_data, dict):
                            raise ValueError(
                                "Proposta de feedback inválida."
                            )

                        instruction = proposal_data.get("instruction")

                        if (
                            not isinstance(instruction, str)
                            or not instruction.strip()
                        ):
                            raise ValueError(
                                "Proposta de feedback sem instrução."
                            )

                        existing = self._find_pending_proposal(instruction)

                        if existing is not None:
                            proposal = existing
                        else:
                            result = self._create_feedback_task(
                            instruction,
                            proposal_data,
                        )

                            proposal = Proposal(
                                instruction=instruction.strip(),
                                approval_id=result["approval_id"],
                                status=str(
                                    result.get("status", "pending")
                                ),
                                plan=dict(result.get("plan", {})),
                            )

                        proposals.append(proposal)
                        approval_id = proposal.approval_id
                    else:
                        def mark_feedback_processed():
                            self._processed.add(key)
                            self._processed_observations[key] = Observation(
                                instruction=observation.instruction.strip(),
                                metadata=dict(observation.metadata),
                            )

                        self._persist_processed_state(mark_feedback_processed)
                        continue

                    def mark_transaction_processed():
                        self._mark_processed(
                            key=key,
                            observation=observation,
                            approval_id=approval_id,
                        )

                    self._persist_processed_state(mark_transaction_processed)
                    continue

                proposals.append(
                    self.process_observation(
                        observation,
                        allow_retry=retry_allowed,
                    )
                )

                if retry_allowed:
                    self._retry_instructions.discard(instruction)
                    self._persist_state()

            except Exception as exc:
                self._errors.append(
                    {
                        "instruction": observation.instruction.strip(),
                        "error": str(exc),
                    }
                )

        return proposals

    @property
    def processed_ids(self) -> set[str]:
        return set(self._processed_ids)

    @property
    def errors(self) -> list[dict[str, str]]:
        return [dict(error) for error in self._errors]

    def export_state(self) -> dict[str, Any]:
        return {
            "processed": [
                {
                    "instruction": observation.instruction,
                    "metadata": dict(observation.metadata),
                }
                for observation in sorted(
                    self._processed_observations.values(),
                    key=lambda item: (
                        item.instruction,
                        self._metadata_key(item.metadata),
                    ),
                )
            ],
            "processed_ids": sorted(self._processed_ids),
            "retry_instructions": sorted(self._retry_instructions),
        }

    def restore_state(
        self,
        state: dict[str, Any],
        persist: bool = True,
    ) -> None:
        if not isinstance(state, dict):
            raise ValueError("Estado do Worker inválido.")

        processed = state.get("processed", [])
        processed_ids = state.get("processed_ids", [])
        retry_instructions = state.get("retry_instructions", [])

        if not isinstance(processed, list):
            raise ValueError(
                "Estado de observações processadas inválido."
            )

        if not isinstance(processed_ids, list):
            raise ValueError(
                "Estado de IDs processados inválido."
            )

        if (
            not isinstance(retry_instructions, list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in retry_instructions
            )
        ):
            raise ValueError(
                "Estado de instruções de retry inválido."
            )

        restored = set()
        restored_observations = {}

        for item in processed:
            if not isinstance(item, dict):
                raise ValueError("Registro de estado inválido.")

            instruction = item.get("instruction")
            metadata = item.get("metadata", {})

            if not isinstance(instruction, str) or not instruction.strip():
                raise ValueError("Instrução processada inválida.")

            if not isinstance(metadata, dict):
                raise ValueError("Metadados processados inválidos.")

            observation = Observation(
                instruction=instruction.strip(),
                metadata=dict(metadata),
            )

            key = self._observation_key(observation)
            restored.add(key)
            restored_observations[key] = observation

        if any(
            not isinstance(item, str) or not item
            for item in processed_ids
        ):
            raise ValueError("ID processado inválido.")

        self._processed = restored
        self._processed_ids = set(processed_ids)
        self._processed_observations = restored_observations
        self._retry_instructions = {
            item.strip()
            for item in retry_instructions
        }

        if persist:
            self._persist_state()
