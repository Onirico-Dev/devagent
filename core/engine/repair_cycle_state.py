from dataclasses import dataclass, field


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
    status: str = "pending"
    attempts: int = 0
    max_attempts: int = 2
    last_error: str = ""
    last_action: str = ""
    history: list = field(default_factory=list)

    def record(self, action, status, error=""):
        self.attempts += 1
        self.last_action = action
        self.status = status
        self.last_error = error

        self.history.append(
            {
                "attempt": self.attempts,
                "action": action,
                "status": status,
                "error": error,
            }
        )

    def can_continue(self):
        return (
            self.status not in {
                "committed",
                "rolled_back",
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
        self.status = "pending"

    def mark_analyzing(self):
        self.status = "analyzing"

    def mark_repairing(self):
        self.status = "repairing"

    def mark_testing(self):
        self.status = "testing"

    def mark_verified(self):
        self.status = "verified"

    def mark_failed(self, error=""):
        self.status = "failed"
        self.last_error = error

    def mark_rolled_back(self, error=""):
        self.status = "rolled_back"
        if error:
            self.last_error = error

    def mark_committed(self):
        self.status = "committed"

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
