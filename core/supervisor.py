import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Supervisor:
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
                self.pending = data
            else:
                self.pending = {}

        except (
            OSError,
            json.JSONDecodeError,
        ):
            self.pending = {}

    def _save(self):
        temporary = self.storage_path.with_suffix(
            ".tmp"
        )

        temporary.write_text(
            json.dumps(
                self.pending,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary.replace(
            self.storage_path
        )

    def request_approval(self, plan):
        if not isinstance(plan, dict):
            raise ValueError(
                "Plano de aprovação inválido."
            )

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

        previous_pending = self.pending
        updated_pending = {
            **previous_pending,
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

        previous_pending = self.pending
        updated_pending = {
            **previous_pending,
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

        previous_pending = self.pending
        updated_pending = {
            **previous_pending,
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
