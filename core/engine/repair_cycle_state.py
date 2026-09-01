from dataclasses import dataclass, field
from enum import Enum



class RepairCycleStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    REPAIRING = "repairing"
    TESTING = "testing"
    VERIFIED = "verified"
    FAILED = "failed"
    REPAIR_FAILED = "repair_failed"
    ROLLED_BACK = "rolled_back"
    COMMITTED = "committed"


@dataclass
class RepairCycleState:
    """
    Estado persistente e autoritativo do ciclo de reparo de uma transação.

    O Gateway utiliza este objeto como fonte de verdade para:
    - quantidade de tentativas;
    - limite máximo;
    - último erro;
    - última ação;
    - histórico das tentativas;
    - estado atual do ciclo.
    """

    transaction_id: str
    status: str = RepairCycleStatus.PENDING.value
    attempts: int = 0
    max_attempts: int = 2
    last_error: str = ""
    last_action: str = ""
    history: list = field(default_factory=list)

    def record(self, action, status, error=""):
        self.attempts += 1
        self.last_action = action
        self.status = status
        normalized_error = str(error) if error else ""
        self.last_error = normalized_error

        self.history.append(
            {
                "attempt": self.attempts,
                "action": action,
                "status": status,
                "error": normalized_error,
            }
        )

    def can_continue(self):
        return (
            self.status not in {
                RepairCycleStatus.COMMITTED.value,
                RepairCycleStatus.ROLLED_BACK.value,
            }
            and self.attempts < self.max_attempts
        )

    def remaining(self):
        return max(
            0,
            self.max_attempts - self.attempts,
        )

    def exhausted(self):
        return self.attempts >= self.max_attempts

    def mark_pending(self):
        self.status = RepairCycleStatus.PENDING.value

    def mark_analyzing(self):
        self.status = RepairCycleStatus.ANALYZING.value

    def mark_repairing(self):
        self.status = RepairCycleStatus.REPAIRING.value

    def mark_testing(self):
        self.status = RepairCycleStatus.TESTING.value

    def mark_verified(self):
        self.status = RepairCycleStatus.VERIFIED.value

    def mark_failed(self, error=""):
        self.status = RepairCycleStatus.FAILED.value
        self.last_error = str(error) if error else ""

    def mark_repair_failed(self, error=""):
        self.status = RepairCycleStatus.REPAIR_FAILED.value
        self.last_error = str(error) if error else ""

    def mark_rolled_back(self, error=""):
        self.status = RepairCycleStatus.ROLLED_BACK.value
        if error:
            self.last_error = str(error)

    def mark_committed(self):
        self.status = RepairCycleStatus.COMMITTED.value

    def persist(self, transaction):
        transaction.repair_state = self.to_dict()
        transaction.metadata["repair_cycle"] = {
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "remaining": self.remaining(),
            "last_action": self.last_action,
            "last_error": self.last_error,
        }
        return transaction.repair_state

    def to_dict(self):
        return {
            "transaction_id": self.transaction_id,
            "status": self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "last_action": self.last_action,
            "history": list(self.history),
        }

    @classmethod
    def restore(cls, transaction):
        data = getattr(
            transaction,
            "repair_state",
            None,
        ) or {}

        if not data:
            return cls(
                transaction.transaction_id,
            )

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError(
                "Estado de reparo inválido."
            )

        transaction_id = data.get(
            "transaction_id"
        )

        if not transaction_id:
            raise ValueError(
                "Estado de reparo sem transaction_id."
            )

        state = cls(
            transaction_id=transaction_id,
            status=data.get(
                "status",
                "pending",
            ),
            attempts=max(
                0,
                int(
                    data.get(
                        "attempts",
                        0,
                    )
                ),
            ),
            max_attempts=max(
                1,
                int(
                    data.get(
                        "max_attempts",
                        2,
                    )
                ),
            ),
            last_error=data.get(
                "last_error",
                "",
            ),
            last_action=data.get(
                "last_action",
                "",
            ),
            history=list(
                data.get(
                    "history",
                    [],
                )
            ),
        )

        return state
