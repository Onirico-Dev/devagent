class RepairController:
    """
    Interface de controle do ciclo de reparo.

    O estado autoritativo das tentativas pertence ao RepairCycleState
    persistido na Transaction. Este controlador mantém apenas a política
    de limite e compatibilidade com o Gateway.
    """

    def __init__(self, max_attempts=3):
        if max_attempts < 1:
            raise ValueError(
                "max_attempts deve ser maior que zero."
            )

        self.max_attempts = max_attempts
        self.attempts = {}

    def start(self, transaction_id):
        self.attempts.setdefault(transaction_id, 0)

    def restore_state(self, transaction_id, attempts):
        self.attempts[transaction_id] = max(0, int(attempts))

    def reset(self, transaction_id):
        """
        Remove o estado transitório de tentativas da transação.

        O estado persistente continua pertencendo ao RepairCycleState.
        O reset aqui apenas limpa o contador mantido pelo controlador.
        """
        self.attempts.pop(transaction_id, None)

    def can_repair(self, transaction_id):
        return (
            self.get_attempts(transaction_id)
            < self.max_attempts
        )

    def can_attempt(self, transaction_id):
        return self.can_repair(transaction_id)

    def record_attempt(self, transaction_id):
        return self.register_attempt(transaction_id)

    def register_attempt(self, transaction_id):
        self.start(transaction_id)

        if not self.can_repair(transaction_id):
            return False

        self.attempts[transaction_id] += 1
        return True

    def get_attempts(self, transaction_id):
        return self.attempts.get(transaction_id, 0)

    def remaining(self, transaction_id):
        return max(
            0,
            self.max_attempts
            - self.get_attempts(transaction_id),
        )

    def exhausted(self, transaction_id):
        return (
            self.get_attempts(transaction_id)
            >= self.max_attempts
        )
