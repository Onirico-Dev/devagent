import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from core.observation import Observation


class ObservationStore:
    """Persistência atômica e durável das observações do Observer."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, list):
            raise ValueError("Armazenamento de observações inválido.")

        return data

    def _write(self, data: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.path.with_suffix(self.path.suffix + ".tmp")

        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())

            temporary.replace(self.path)

            directory_fd = os.open(
                self.path.parent,
                os.O_RDONLY,
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _serialize(observations: list[Observation]) -> list[dict[str, Any]]:
        if not isinstance(observations, list):
            raise ValueError("Observações inválidas.")

        records = []

        for observation in observations:
            if not isinstance(observation, Observation):
                raise ValueError("Observação inválida.")

            records.append(
                {
                    "instruction": observation.instruction,
                    "metadata": dict(observation.metadata),
                }
            )

        return records

    @staticmethod
    def _deserialize(records: list[dict[str, Any]]) -> list[Observation]:
        observations = []

        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Registro de observação inválido.")

            instruction = record.get("instruction")
            metadata = record.get("metadata", {})

            if not isinstance(instruction, str) or not instruction.strip():
                raise ValueError("Instrução de observação inválida.")

            if not isinstance(metadata, dict):
                raise ValueError("Metadados de observação inválidos.")

            observations.append(
                Observation(
                    instruction=instruction,
                    metadata=dict(metadata),
                )
            )

        return observations

    def load(self) -> list[Observation]:
        with self._lock:
            records = self._read()

        return self._deserialize(records)

    def save(self, observations: list[Observation]) -> None:
        records = self._serialize(observations)

        with self._lock:
            self._write(records)

    def append(self, observation: Observation) -> None:
        if not isinstance(observation, Observation):
            raise ValueError("Observação inválida.")

        with self._lock:
            records = self._read()
            records.append(
                {
                    "instruction": observation.instruction,
                    "metadata": dict(observation.metadata),
                }
            )
            self._write(records)
