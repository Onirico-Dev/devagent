from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Supervisor:

    def __init__(self):
        self.pending = {}

    def request_approval(self, plan):
        approval_id = str(len(self.pending) + 1)

        self.pending[approval_id] = {
            "status": ApprovalStatus.PENDING,
            "plan": plan,
        }

        return approval_id

    def approve(self, approval_id):
        if approval_id not in self.pending:
            raise KeyError("Solicitação não encontrada.")

        self.pending[approval_id]["status"] = (
            ApprovalStatus.APPROVED
        )

        return self.pending[approval_id]

    def reject(self, approval_id):
        if approval_id not in self.pending:
            raise KeyError("Solicitação não encontrada.")

        self.pending[approval_id]["status"] = (
            ApprovalStatus.REJECTED
        )

        return self.pending[approval_id]

    def get(self, approval_id):
        return self.pending.get(approval_id)
