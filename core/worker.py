from dataclasses import dataclass
from typing import Any

from core.observer import Observation, Observer


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
    """

    def __init__(self, gateway, observer: Observer):
        if gateway is None:
            raise ValueError("Gateway inválido.")
        if not isinstance(observer, Observer):
            raise ValueError("Observer inválido.")

        self.gateway = gateway
        self.observer = observer
        self._processed: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self._processed_ids: set[str] = set()

    @staticmethod
    def _observation_key(observation: Observation) -> tuple[str, tuple[tuple[str, str], ...]]:
        metadata = tuple(
            sorted(
                (str(key), repr(value))
                for key, value in observation.metadata.items()
            )
        )
        return observation.instruction.strip(), metadata

    def process_observation(self, observation: Observation) -> Proposal:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        instruction = observation.instruction.strip()
        if not instruction:
            raise ValueError("A instrução da observação não pode ser vazia.")

        key = self._observation_key(observation)

        if key in self._processed:
            raise ValueError("Observação já processada.")

        result = self.gateway.create_task(instruction)

        approval_id = result["approval_id"]
        self._processed.add(key)
        self._processed_ids.add(approval_id)

        return Proposal(
            instruction=instruction,
            approval_id=approval_id,
            status=result["status"],
            plan=result["plan"],
        )

    def run_once(self) -> list[Proposal]:
        proposals = []

        for observation in self.observer.observe():
            key = self._observation_key(observation)

            if key in self._processed:
                continue

            proposals.append(self.process_observation(observation))

        return proposals

    @property
    def processed_ids(self) -> set[str]:
        return set(self._processed_ids)
