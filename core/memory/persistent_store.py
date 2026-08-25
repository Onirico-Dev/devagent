import json
import os
import tempfile
from pathlib import Path
from threading import RLock


class PersistentStore:
    """
    Armazenamento JSON simples, atômico e protegido contra concorrência
    dentro do processo.

    A escrita utiliza arquivo temporário + os.replace(), evitando que
    uma interrupção deixe o arquivo principal parcialmente gravado.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def load(self, default=None):
        with self._lock:
            if not self.path.exists():
                return default

            try:
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                return default

            return data

    def save(self, data):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )

            temporary = Path(temporary_name)

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        data,
                        handle,
                        ensure_ascii=False,
                        indent=2,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(temporary, self.path)

            finally:
                try:
                    if temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass
