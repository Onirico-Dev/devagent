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
            exist_ok=True
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

        self.pending[approval_id] = {
            "status": ApprovalStatus.PENDING.value,
            "plan": plan,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        self._save()

        return approval_id

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

        request["status"] = (
            ApprovalStatus.APPROVED.value
        )

        request["updated_at"] = self._now()

        self._save()

        return request

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

        request["status"] = (
            ApprovalStatus.REJECTED.value
        )

        request["updated_at"] = self._now()

        self._save()

        return request

    def get(self, approval_id):

        return self.pending.get(
            approval_id
        )

    def list_all(self):

        return self.pending.copy()

    def list_pending(self):

        return {
            approval_id: request
            for approval_id, request
            in self.pending.items()
            if request["status"]
            == ApprovalStatus.PENDING.value
        }
