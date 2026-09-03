import json
import os
import tempfile
from pathlib import Path
from threading import RLock


class PersistentStore:
    _locks = {}
    _locks_guard = RLock()

    @classmethod
    def _lock_for_path(cls, path):
        key = str(path)

        with cls._locks_guard:
            lock = cls._locks.get(key)

            if lock is None:
                lock = RLock()
                cls._locks[key] = lock

            return lock

    """
    Armazenamento JSON simples, atômico e protegido contra concorrência
    dentro do processo.

    As operações de leitura/escrita utilizam arquivo temporário + os.replace(),
    evitando que uma interrupção deixe o arquivo principal parcialmente gravado.

    A operação update() mantém o ciclo leitura -> transformação -> escrita
    protegido pelo mesmo lock, evitando perda de atualizações concorrentes.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self._lock_for_path(self.path)

    def load(self, default=None):
        with self._lock:
            return self._load_unlocked(default)

    def _load_unlocked(self, default=None):
        if not self.path.exists():
            return default

        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            return default

        return data

    def save(self, data):
        with self._lock:
            self._save_unlocked(data)

    def _save_unlocked(self, data):
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

            directory_fd = os.open(
                str(self.path.parent),
                os.O_RDONLY,
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def update(self, updater, default=None):
        """
        Executa uma transformação atômica:

            estado atual -> updater(estado) -> novo estado

        A leitura e a escrita acontecem dentro do mesmo lock.
        Isso evita lost updates em operações concorrentes dentro
        do mesmo processo.
        """
        if not callable(updater):
            raise TypeError("updater deve ser chamável.")

        with self._lock:
            current = self._load_unlocked(default)

            updated = updater(current)

            self._save_unlocked(updated)

            return updated
