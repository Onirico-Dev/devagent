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
            task = self.history.get(approval_id) if approval_id else None

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

            recovery = transaction.metadata.get("recovery") is True
            extra = {}

            if recovery:
                extra["recovery"] = True

            repair_state = getattr(transaction, "repair_state", None)
            if isinstance(repair_state, dict) and repair_state:
                extra["repair_state"] = dict(repair_state)

            repair_cycle = transaction.metadata.get("repair_cycle")
            if isinstance(repair_cycle, dict):
                extra["repair_cycle"] = dict(repair_cycle)

            already_reconciled = (
                task.get("status") == status
                and task.get("transaction_id") == transaction_id
                and all(
                    task.get(key) == value
                    for key, value in extra.items()
                )
            )

            if already_reconciled:
                reconciled.add(transaction_id)
                continue

            update_kwargs = {
                "status": status,
                "transaction_id": transaction_id,
            }
            if extra:
                update_kwargs["extra"] = extra

            self.history.update(task["task_id"], **update_kwargs)
            reconciled.add(transaction_id)
