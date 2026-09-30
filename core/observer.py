from typing import Iterable

from core.observation import Observation
from core.observation_store import ObservationStore


class Observer:
    """Fonte de observações com persistência opcional."""

    def __init__(
        self,
        observations: Iterable[Observation] | None = None,
        store: ObservationStore | None = None,
    ):
        self._store = store

        if observations is not None:
            self._observations = list(observations)
        elif store is not None:
            self._observations = store.load()
        else:
            self._observations = []

    def observe(self) -> list[Observation]:
        if self._store is not None:
            self._observations = self._store.load()

        return list(self._observations)

    def add(self, observation: Observation) -> None:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        if (
            not isinstance(observation.instruction, str)
            or not observation.instruction.strip()
        ):
            raise ValueError("A instrução da observação não pode ser vazia.")

        self._observations.append(observation)

        if self._store is not None:
            self._store.save(self._observations)

    def add_if_absent(self, observation: Observation) -> bool:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        if (
            not isinstance(observation.instruction, str)
            or not observation.instruction.strip()
        ):
            raise ValueError("A instrução da observação não pode ser vazia.")

        if self._store is None:
            for existing in self._observations:
                if (
                    existing.metadata.get("source") == "transaction_result"
                    and existing.metadata.get("transaction_id")
                    == observation.metadata.get("transaction_id")
                ):
                    return False

            self._observations.append(observation)
            return True

        added = self._store.append_if_absent(observation)
        self._observations = self._store.load()
        return added
