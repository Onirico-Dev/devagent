import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from threading import RLock


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Supervisor:
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

    def __init__(
        self,
        storage_path="transactions/approvals.json",
    ):
        self.storage_path = Path(
            storage_path
        ).resolve()

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.pending = {}
        self._lock = self._lock_for_path(
            self.storage_path
        )
        self._load()

    def _now(self):
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self):
        if not self.storage_path.exists():
            self.pending = {}
            return

        try:
            data = json.loads(
                self.storage_path.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(data, dict):
                valid_statuses = {
                    ApprovalStatus.PENDING.value,
                    ApprovalStatus.APPROVED.value,
                    ApprovalStatus.REJECTED.value,
                }

                self.pending = {
                    approval_id: request
                    for approval_id, request in data.items()
                    if isinstance(request, dict)
                    and request.get("status") in valid_statuses
                }
            else:
                self.pending = {}

        except (
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            self.pending = {}

    def _save(self):
        with self._lock:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.storage_path.name}.",
                suffix=".tmp",
                dir=str(self.storage_path.parent),
            )

            temporary = Path(temporary_name)

            try:
                with open(
                    fd,
                    "w",
                    encoding="utf-8",
                ) as handle:
                    json.dump(
                        self.pending,
                        handle,
                        ensure_ascii=False,
                        indent=2,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                temporary.replace(
                    self.storage_path
                )

                directory_fd = os.open(
                    str(self.storage_path.parent),
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


    def request_approval(self, plan):
        if not isinstance(plan, dict):
            raise ValueError(
                "Plano de aprovação inválido."
            )

        with self._lock:
            previous_pending = self.pending
            self._load()

            numeric_ids = []

            for approval_id in self.pending:
                try:
                    numeric_ids.append(
                        int(approval_id)
                    )
                except ValueError:
                    continue

            next_id = (
                max(numeric_ids, default=0) + 1
            )

            approval_id = str(next_id)

            snapshot = copy.deepcopy(plan)
            now = self._now()

            request = {
                "status": ApprovalStatus.PENDING.value,
                "plan": snapshot,
                "created_at": now,
                "updated_at": now,
            }

            updated_pending = {
                **self.pending,
                approval_id: request,
            }

            try:
                self.pending = updated_pending
                self._save()
            except Exception:
                self.pending = previous_pending
                raise

            return approval_id
    def prepare_approval(self, approval_id):
        request = self.pending.get(
            approval_id
        )

        if request is None:
            raise KeyError(
                "Tarefa não encontrada."
            )

        if request["status"] != (
            ApprovalStatus.PENDING.value
        ):
            raise ValueError(
                "Solicitação não está pendente."
            )

        return copy.deepcopy(request)

    def approve(self, approval_id):
        with self._lock:
            previous_pending = self.pending
            self._load()

            request = self.pending.get(
                approval_id
            )

            if request is None:
                raise KeyError(
                    "Tarefa não encontrada."
                )

            if request["status"] != (
                ApprovalStatus.PENDING.value
            ):
                raise ValueError(
                    "Solicitação não está pendente."
                )

            updated_request = {
                **request,
                "status": ApprovalStatus.APPROVED.value,
                "updated_at": self._now(),
            }

            updated_pending = {
                **self.pending,
                approval_id: updated_request,
            }

            try:
                self.pending = updated_pending
                self._save()
            except Exception:
                self.pending = previous_pending
                raise

            return copy.deepcopy(updated_request)
    def reject(self, approval_id):
        with self._lock:
            previous_pending = self.pending
            self._load()

            request = self.pending.get(
                approval_id
            )

            if request is None:
                raise KeyError(
                    "Solicitação não encontrada."
                )

            if request["status"] != (
                ApprovalStatus.PENDING.value
            ):
                raise ValueError(
                    "Solicitação não está pendente."
                )

            updated_request = {
                **request,
                "status": ApprovalStatus.REJECTED.value,
                "updated_at": self._now(),
            }

            updated_pending = {
                **self.pending,
                approval_id: updated_request,
            }

            try:
                self.pending = updated_pending
                self._save()
            except Exception:
                self.pending = previous_pending
                raise

            return copy.deepcopy(updated_request)
    def get(self, approval_id):
        request = self.pending.get(
            approval_id
        )

        if request is None:
            return None

        return copy.deepcopy(request)

    def list_all(self):
        return copy.deepcopy(
            self.pending
        )

    def list_pending(self):
        return {
            approval_id: copy.deepcopy(request)
            for approval_id, request
            in self.pending.items()
            if request["status"]
            == ApprovalStatus.PENDING.value
        }
