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

        task = next(
            (item for item in self.tasks if item["task_id"] == task_id),
            None,
        )
        if task is None:
            raise KeyError(f"Tarefa não encontrada: {task_id}")

        if kwargs.get("status") is not None:
            task["status"] = kwargs["status"]

        if kwargs.get("transaction_id") is not None:
            task["transaction_id"] = kwargs["transaction_id"]

        extra = kwargs.get("extra")
        if extra:
            task.update(extra)


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


def test_reconcile_deduplicates_same_transaction():
    history = FakeHistory()
    history.tasks = [
        {
            "task_id": "task-duplicate",
            "transaction_id": "tx-duplicate",
        }
    ]

    transaction = FakeTransaction(
        "tx-duplicate",
        TaskHistoryStatus.COMMITTED.value,
    )

    RecoveryReconciler(history).reconcile(
        [transaction, transaction]
    )

    assert history.updates == [
        (
            "task-duplicate",
            {
                "status": TaskHistoryStatus.COMMITTED.value,
                "transaction_id": "tx-duplicate",
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

def test_reconcile_propagates_history_update_failure():
    history = FakeHistory()
    history.tasks = [{"task_id": "task-5", "transaction_id": "tx-5"}]

    def fail_update(*args, **kwargs):
        raise RuntimeError("simulated history persistence failure")

    history.update = fail_update

    transaction = FakeTransaction(
        "tx-5",
        TaskHistoryStatus.FAILED.value,
    )

    try:
        RecoveryReconciler(history).reconcile([transaction])
    except RuntimeError as error:
        assert str(error) == "simulated history persistence failure"
    else:
        raise AssertionError(
            "RecoveryReconciler deveria propagar a falha do histórico"
        )


def test_reconcile_failed_recovery_updates_history_to_failed():
    history = FakeHistory()
    history.tasks = [
        {
            "task_id": "task-recovery-failure",
            "transaction_id": "tx-recovery-failure",
        }
    ]

    transaction = FakeTransaction(
        "tx-recovery-failure",
        TaskHistoryStatus.FAILED.value,
        {
            "recovery_error": "simulated rollback failure",
        },
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == [
        (
            "task-recovery-failure",
            {
                "status": TaskHistoryStatus.FAILED.value,
                "transaction_id": "tx-recovery-failure",
            },
        )
    ]
def test_reconcile_preserves_recovery_marker():
    history = FakeHistory()
    history.tasks = [
        {
            "task_id": "task-recovery",
            "transaction_id": "tx-recovery",
        }
    ]

    transaction = FakeTransaction(
        "tx-recovery",
        TaskHistoryStatus.COMMITTED.value,
        {
            "recovery": True,
        },
    )

    RecoveryReconciler(history).reconcile([transaction])

    assert history.updates == [
        (
            "task-recovery",
            {
                "status": TaskHistoryStatus.COMMITTED.value,
                "transaction_id": "tx-recovery",
                "extra": {
                    "recovery": True,
                },
            },
        )
    ]
def test_reconcile_does_not_rewrite_already_reconciled_task(tmp_path):
    from core.memory.task_history import TaskHistory

    history = TaskHistory(tmp_path / "tasks.json")
    history.create(
        approval_id="approval-idempotent",
        instruction="teste",
        plan={},
    )

    transaction = FakeTransaction(
        "tx-idempotent",
        TaskHistoryStatus.COMMITTED.value,
        {"approval_id": "approval-idempotent", "recovery": True},
    )

    reconciler = RecoveryReconciler(history)

    reconciler.reconcile([transaction])
    first = history.get("approval-idempotent")

    reconciler.reconcile([transaction])
    second = history.get("approval-idempotent")

    assert second == first

def test_reconcile_is_idempotent_across_repeated_calls():
    history = FakeHistory()
    history.tasks = [
        {
            "task_id": "task-repeat",
            "transaction_id": "tx-repeat",
        }
    ]

    transaction = FakeTransaction(
        "tx-repeat",
        TaskHistoryStatus.COMMITTED.value,
        {"recovery": True},
    )

    reconciler = RecoveryReconciler(history)

    reconciler.reconcile([transaction])
    reconciler.reconcile([transaction])

    assert history.updates == [
        (
            "task-repeat",
            {
                "status": TaskHistoryStatus.COMMITTED.value,
                "transaction_id": "tx-repeat",
                "extra": {"recovery": True},
            },
        )
    ]

    assert history.tasks[0]["status"] == TaskHistoryStatus.COMMITTED.value
    assert history.tasks[0]["transaction_id"] == "tx-repeat"
    assert history.tasks[0]["recovery"] is True

def test_reconcile_refreshes_stale_task_history_instance(tmp_path):
    from core.memory.task_history import TaskHistory

    storage_path = tmp_path / "tasks.json"
    stale_history = TaskHistory(storage_path)
    writer_history = TaskHistory(storage_path)

    writer_history.create(
        approval_id="approval-cross-instance",
        instruction="reconciliar tarefa",
        plan={},
    )

    transaction = FakeTransaction(
        "tx-cross-instance",
        TaskHistoryStatus.COMMITTED.value,
        {"approval_id": "approval-cross-instance"},
    )

    RecoveryReconciler(stale_history).reconcile([transaction])

    stale_history.refresh()
    task = stale_history.get("approval-cross-instance")
    assert task["status"] == TaskHistoryStatus.COMMITTED.value
    assert task["transaction_id"] == "tx-cross-instance"
