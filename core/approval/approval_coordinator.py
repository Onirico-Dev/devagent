import fcntl
import hashlib
from pathlib import Path
from threading import RLock


class ApprovalCoordinator:
    """Serializa decisões de aprovação por ID, entre threads e processos."""

    _locks = {}
    _locks_guard = RLock()

    def __init__(self, root):
        self.root = root

    @classmethod
    def _lock_for(cls, approval_id):
        key = str(approval_id)

        with cls._locks_guard:
            lock = cls._locks.get(key)

            if lock is None:
                lock = RLock()
                cls._locks[key] = lock

            return lock

    def process_lock(self, approval_id):
        key = str(approval_id).encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()

        lock_path = (
            Path(self.root).resolve()
            / "transactions"
            / "approval_locks"
            / f"{digest}.lock"
        )

        lock_path.parent.mkdir(parents=True, exist_ok=True)

        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        return handle

    def acquire(self, approval_id):
        thread_lock = self._lock_for(approval_id)
        thread_lock.acquire()

        try:
            process_lock = self.process_lock(approval_id)
        except Exception:
            thread_lock.release()
            raise

        return thread_lock, process_lock

    @staticmethod
    def release(thread_lock, process_lock):
        try:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
        finally:
            process_lock.close()
            thread_lock.release()
