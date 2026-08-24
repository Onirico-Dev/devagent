from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Supervisor:

    def __init__(self):
        self.pending = {}
        self._next_id = 1

    def request_approval(self, plan):

        approval_id = str(self._next_id)
        self._next_id += 1

        self.pending[approval_id] = {
            "status": ApprovalStatus.PENDING,
            "plan": plan,
        }

        return approval_id

    def approve(self, approval_id):

        request = self._get_request(
            approval_id
        )

        if request["status"] != ApprovalStatus.PENDING:
            raise ValueError(
                "Solicitação não está pendente."
            )

        request["status"] = (
            ApprovalStatus.APPROVED
        )

        return request

    def reject(self, approval_id):

        request = self._get_request(
            approval_id
        )

        if request["status"] != ApprovalStatus.PENDING:
            raise ValueError(
                "Solicitação não está pendente."
            )

        request["status"] = (
            ApprovalStatus.REJECTED
        )

        return request

    def get(self, approval_id):

        return self.pending.get(
            approval_id
        )

    def _get_request(self, approval_id):

        if approval_id not in self.pending:
            raise KeyError(
                "Solicitação não encontrada."
            )

        return self.pending[approval_id]
