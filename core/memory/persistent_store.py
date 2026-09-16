import fcntl
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

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = self._lock_for_path(self.path)
        self._process_lock_path = self.path.with_name(
            f".{self.path.name}.lock"
        )

    def _load_unlocked(self, default=None):
        if not self.path.exists():
            return default

        raw = self.path.read_text(encoding="utf-8")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Estado persistido inválido: {self.path}"
            ) from error

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

    def _process_lock(self):
        handle = self._process_lock_path.open(
            "a+",
            encoding="utf-8",
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def load(self, default=None):
        with self._lock:
            lock_file = self._process_lock()

            try:
                return self._load_unlocked(default)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()

    def save(self, data):
        with self._lock:
            lock_file = self._process_lock()

            try:
                self._save_unlocked(data)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()

    def update(self, updater, default=None):
        if not callable(updater):
            raise TypeError("updater deve ser chamável.")

        with self._lock:
            lock_file = self._process_lock()

            try:
                current = self._load_unlocked(default)
                updated = updater(current)
                self._save_unlocked(updated)
                return updated
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
