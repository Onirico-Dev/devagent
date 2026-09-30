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
        reconciled = set()

        for transaction in transactions:
            transaction_id = transaction.transaction_id

            if transaction_id in reconciled:
                continue

            status = getattr(
                transaction.status,
                "value",
                transaction.status,
            )

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
                        if item.get("transaction_id") == transaction_id
                    ),
                    None,
                )

            if task is None:
                continue

            extra = {}
            if transaction.metadata.get("recovery") is True:
                extra["recovery"] = True

            update_kwargs = {
                "status": status,
                "transaction_id": transaction_id,
            }
            if extra:
                update_kwargs["extra"] = extra

            self.history.update(
                task["task_id"],
                **update_kwargs,
            )
            reconciled.add(transaction_id)
