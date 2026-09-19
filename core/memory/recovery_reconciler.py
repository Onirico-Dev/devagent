from core.memory.task_history import TaskHistoryStatus


class RecoveryReconciler:
    """Reconcilia transações recuperadas com o histórico de tarefas."""

    FINAL_STATUSES = {
        TaskHistoryStatus.COMMITTED.value,
        TaskHistoryStatus.ROLLED_BACK.value,
        TaskHistoryStatus.FAILED.value,
    }

    def __init__(self, history):
        self.history = history

    def reconcile(self, transactions):
        for transaction in transactions:
            status = getattr(transaction.status, "value", transaction.status)

            if status not in self.FINAL_STATUSES:
                continue

            approval_id = transaction.metadata.get("approval_id")
            task = None

            if approval_id:
                task = self.history.get(approval_id)

            if task is None:
                task = next(
                    (
                        item
                        for item in self.history.list_all()
                        if item.get("transaction_id")
                        == transaction.transaction_id
                    ),
                    None,
                )

            if task is None:
                continue

            self.history.update(
                task["task_id"],
                status=status,
                transaction_id=transaction.transaction_id,
            )
