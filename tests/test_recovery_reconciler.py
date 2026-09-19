from core.memory.recovery_reconciler import RecoveryReconciler
from core.memory.task_history import TaskHistoryStatus


class FakeHistory:
    def __init__(self):
        self.tasks = []
        self.updates = []

    def get(self, task_id):
        return next(
            (task for task in self.tasks if task["task_id"] == task_id),
            None,
        )

    def list_all(self):
        return list(self.tasks)

    def update(self, task_id, **kwargs):
        self.updates.append((task_id, kwargs))


class FakeTransaction:
    def __init__(self, transaction_id, status, metadata=None):
        self.transaction_id = transaction_id
        self.status = status
        self.metadata = metadata or {}


def test_reconcile_updates_task_by_approval_id():
    history = FakeHistory()
    history.tasks = [{"task_id": "task-1", "task_id_alias": "approval-1"}]

    history.get = lambda approval_id: (
        history.tasks[0] if approval_id == "approval-1" else None
    )

    transaction = FakeTransaction(
        "tx-1",
        TaskHistoryStatus.COMMITTED.value,
        {"approval_id": "approval-1"},
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == [
        (
            "task-1",
            {
                "status": TaskHistoryStatus.COMMITTED.value,
                "transaction_id": "tx-1",
            },
        )
    ]


def test_reconcile_falls_back_to_transaction_id():
    history = FakeHistory()
    history.tasks = [{"task_id": "task-2", "transaction_id": "tx-2"}]

    transaction = FakeTransaction(
        "tx-2",
        TaskHistoryStatus.ROLLED_BACK.value,
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == [
        (
            "task-2",
            {
                "status": TaskHistoryStatus.ROLLED_BACK.value,
                "transaction_id": "tx-2",
            },
        )
    ]


def test_reconcile_skips_non_final_status():
    history = FakeHistory()

    transaction = FakeTransaction(
        "tx-3",
        "executing",
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == []


def test_reconcile_skips_when_task_does_not_exist():
    history = FakeHistory()

    transaction = FakeTransaction(
        "tx-4",
        TaskHistoryStatus.FAILED.value,
        {"approval_id": "missing"},
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == []
