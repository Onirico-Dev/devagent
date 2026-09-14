import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any


class WorkerStateStore:
    """Persistência atômica e durável do estado do Worker."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}

            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)

            if not isinstance(data, dict):
                raise ValueError("Armazenamento do Worker inválido.")

            return data

    def save(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict):
            raise ValueError("Estado do Worker inválido.")

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            temporary_path = None

            try:
                fd, temporary_path = tempfile.mkstemp(
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=self.path.parent,
                )

                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        state,
                        handle,
                        ensure_ascii=False,
                        indent=2,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(temporary_path, self.path)
                temporary_path = None

                directory_fd = os.open(
                    self.path.parent,
                    os.O_RDONLY,
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

            finally:
                if temporary_path is not None:
                    try:
                        os.unlink(temporary_path)
                    except FileNotFoundError:
                        pass
