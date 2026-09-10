from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Observation:
    instruction: str
    metadata: dict[str, Any]


class Observer:
    """Fonte determinística de observações para o Worker."""

    def __init__(self, observations: Iterable[Observation] | None = None):
        self._observations = list(observations or [])

    def observe(self) -> list[Observation]:
        return list(self._observations)

    def add(self, observation: Observation) -> None:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")
        if not isinstance(observation.instruction, str) or not observation.instruction.strip():
            raise ValueError("A instrução da observação não pode ser vazia.")
        self._observations.append(observation)
