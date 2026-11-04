import copy
import fcntl
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

    def _process_lock(self):
        lock_path = self.storage_path.with_name(
            f".{self.storage_path.name}.lock"
        )
        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _now(self):
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self):
        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.pending = {}
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Arquivo de aprovações contém JSON inválido: "
                f"{self.storage_path}"
            ) from error

        if not isinstance(data, dict):
            raise ValueError(
                f"Estrutura do arquivo de aprovações inválida: "
                f"{self.storage_path}"
            )

        valid_statuses = {
            ApprovalStatus.PENDING.value,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.REJECTED.value,
        }

        loaded_pending = {
            approval_id: request
            for approval_id, request in data.items()
            if isinstance(request, dict)
            and request.get("status") in valid_statuses
        }

        self.pending = loaded_pending

    def _write_pending_to_temporary(self):
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

            return temporary
        except Exception:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise

    def _replace_storage_file(self, temporary):
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

    def _cleanup_temporary_file(self, temporary):
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass

    def _save(self):
        with self._lock:
            temporary = self._write_pending_to_temporary()

            try:
                self._replace_storage_file(
                    temporary
                )
            finally:
                self._cleanup_temporary_file(
                    temporary
                )


    def _validate_approval_plan(self, plan):
        if not isinstance(plan, dict):
            raise ValueError(
                "Plano de aprovação inválido."
            )

    def _next_approval_id(self):
        numeric_ids = []

        for approval_id in self.pending:
            try:
                numeric_ids.append(
                    int(approval_id)
                )
            except ValueError:
                continue

        return str(
            max(numeric_ids, default=0) + 1
        )

    def _build_approval_request(
        self,
        plan,
        instruction=None,
        idempotency_key=None,
    ):
        snapshot = copy.deepcopy(plan)
        now = self._now()

        request = {
            "status": ApprovalStatus.PENDING.value,
            "plan": snapshot,
            "created_at": now,
            "updated_at": now,
        }

        if instruction is not None:
            request["instruction"] = instruction

        if idempotency_key is not None:
            request["idempotency_key"] = idempotency_key

        return request

    def _persist_approval_request(
        self,
        approval_id,
        request,
        previous_pending,
    ):
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

    def request_approval(
        self,
        plan,
        instruction=None,
        idempotency_key=None,
    ):
        if instruction is not None and not isinstance(instruction, str):
            raise ValueError("Instrução de aprovação inválida.")

        if idempotency_key is not None:
            if (
                not isinstance(idempotency_key, str)
                or not idempotency_key.strip()
            ):
                raise ValueError("Chave de idempotência inválida.")
            idempotency_key = idempotency_key.strip()

        process_lock = self._process_lock()
        try:
            self._validate_approval_plan(plan)

            with self._lock:
                self._load()
                previous_pending = copy.deepcopy(self.pending)

                if idempotency_key is not None:
                    matches = [
                        (approval_id, request)
                        for approval_id, request in self.pending.items()
                        if (
                            isinstance(request, dict)
                            and request.get("idempotency_key")
                            == idempotency_key
                        )
                    ]

                    if matches:
                        if len(matches) > 1:
                            raise RuntimeError(
                                "Chave de idempotência associada "
                                "a múltiplas aprovações."
                            )

                        existing_id, existing_request = matches[0]

                        if (
                            existing_request.get("instruction")
                            != instruction
                        ):
                            raise ValueError(
                                "Chave de idempotência reutilizada "
                                "com dados diferentes."
                            )

                        return existing_id

                approval_id = self._next_approval_id()
                request = self._build_approval_request(
                    plan,
                    instruction=instruction,
                    idempotency_key=idempotency_key,
                )

                self._persist_approval_request(
                    approval_id,
                    request,
                    previous_pending,
                )

                return approval_id
        finally:
            fcntl.flock(
                process_lock.fileno(),
                fcntl.LOCK_UN,
            )
            process_lock.close()

    def prepare_approval(self, approval_id):
        process_lock = self._process_lock()
        try:
            with self._lock:
                self._load()
                request = self.pending.get(approval_id)
                if request is None:
                    raise KeyError("Tarefa não encontrada.")
                if request["status"] != ApprovalStatus.PENDING.value:
                    raise ValueError("Solicitação não está pendente.")
                return copy.deepcopy(request)
        finally:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
            process_lock.close()

    def approve(self, approval_id):
        process_lock = self._process_lock()
        try:
                    with self._lock:
                        self._load()
                        previous_pending = copy.deepcopy(self.pending)

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
        finally:
            fcntl.flock(
                process_lock.fileno(),
                fcntl.LOCK_UN,
            )
            process_lock.close()
    def reject(self, approval_id):
        process_lock = self._process_lock()
        try:
                    with self._lock:
                        self._load()
                        previous_pending = copy.deepcopy(self.pending)

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
        finally:
            fcntl.flock(
                process_lock.fileno(),
                fcntl.LOCK_UN,
            )
            process_lock.close()
    def get(self, approval_id):
        process_lock = self._process_lock()
        try:
            with self._lock:
                self._load()
                request = self.pending.get(approval_id)
                if request is None:
                    return None
                return copy.deepcopy(request)
        finally:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
            process_lock.close()

    def list_all(self):
        process_lock = self._process_lock()
        try:
            with self._lock:
                self._load()
                return copy.deepcopy(self.pending)
        finally:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
            process_lock.close()

    def list_pending(self):
        process_lock = self._process_lock()
        try:
            with self._lock:
                self._load()
                return {
                    approval_id: copy.deepcopy(request)
                    for approval_id, request in self.pending.items()
                    if request["status"] == ApprovalStatus.PENDING.value
                }
        finally:
            fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
            process_lock.close()
