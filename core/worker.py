from dataclasses import dataclass
from typing import Any

from core.observation import Observation
from core.observer import Observer
from core.worker_state_store import WorkerStateStore


@dataclass(frozen=True)
class Proposal:
    instruction: str
    approval_id: str
    status: str
    plan: dict[str, Any]


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
    """

    def __init__(
        self,
        gateway,
        observer: Observer,
        store: WorkerStateStore | None = None,
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
        self._processed: set[
            tuple[str, tuple[tuple[str, str], ...]]
        ] = set()
        self._processed_ids: set[str] = set()
        self._processed_observations: dict[
            tuple[str, tuple[tuple[str, str], ...]],
            Observation,
        ] = {}
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

    def _persist_state(self) -> None:
        if self.store is not None:
            self.store.save(self.export_state())

    def process_observation(
        self,
        observation: Observation,
    ) -> Proposal:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        instruction = observation.instruction.strip()
        if not instruction:
            raise ValueError(
                "A instrução da observação não pode ser vazia."
            )

        key = self._observation_key(observation)

        if key in self._processed:
            raise ValueError("Observação já processada.")

        result = self.gateway.create_task(instruction)

        approval_id = result["approval_id"]

        self._processed.add(key)
        self._processed_ids.add(approval_id)
        self._processed_observations[key] = Observation(
            instruction=instruction,
            metadata=dict(observation.metadata),
        )
        try:
            self._persist_state()
        except Exception:
            self._processed.discard(key)
            self._processed_ids.discard(approval_id)
            self._processed_observations.pop(key, None)
            raise

        return Proposal(
            instruction=instruction,
            approval_id=approval_id,
            status=result["status"],
            plan=result["plan"],
        )

    def run_once(self) -> list[Proposal]:
        proposals = []
        self._errors = []

        for observation in self.observer.observe():
            key = self._observation_key(observation)

            if key in self._processed:
                continue

            try:
                proposals.append(
                    self.process_observation(observation)
                )
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

        if not isinstance(processed, list):
            raise ValueError(
                "Estado de observações processadas inválido."
            )

        if not isinstance(processed_ids, list):
            raise ValueError(
                "Estado de IDs processados inválido."
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

        if persist:
            self._persist_state()
