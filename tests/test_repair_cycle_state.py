from core.engine.repair_cycle_state import RepairCycleState


def test_repair_cycle_state_records_attempt():
    state = RepairCycleState("tx-1")

    state.record(
        action="modify",
        status="failed",
        error="teste falhou",
    )

    data = state.to_dict()

    assert data["transaction_id"] == "tx-1"
    assert data["attempts"] == 1
    assert data["last_action"] == "modify"
    assert data["last_error"] == "teste falhou"
    assert len(data["history"]) == 1


def test_repair_cycle_state_can_be_restored():
    original = RepairCycleState("tx-2")

    original.record(
        "modify",
        "failed",
        "erro",
    )

    restored = RepairCycleState.from_dict(
        original.to_dict()
    )

    assert restored.transaction_id == "tx-2"
    assert restored.attempts == 1
    assert restored.history == original.history


def test_repair_cycle_state_stops_at_limit():
    state = RepairCycleState(
        "tx-3",
        max_attempts=2,
    )

    state.record(
        "modify",
        "failed",
    )

    assert state.can_continue()

    state.record(
        "modify",
        "failed",
    )

    assert not state.can_continue()


def test_repair_cycle_state_restore_empty_transaction():
    class Transaction:
        transaction_id = "tx-empty"
        repair_state = {}

    state = RepairCycleState.restore(
        Transaction()
    )

    assert state.transaction_id == "tx-empty"
    assert state.status == "pending"
    assert state.attempts == 0
    assert state.max_attempts == 2
    assert state.can_continue()


def test_repair_cycle_state_restore_existing_transaction():
    class Transaction:
        transaction_id = "tx-existing"

        repair_state = {
            "transaction_id": "tx-existing",
            "status": "failed",
            "attempts": 1,
            "max_attempts": 2,
            "last_error": "falha",
            "last_action": "modify",
            "history": [],
        }

    state = RepairCycleState.restore(
        Transaction()
    )

    assert state.transaction_id == "tx-existing"
    assert state.attempts == 1
    assert state.max_attempts == 2
    assert state.last_error == "falha"
    assert state.can_continue()


def test_repair_controller_restores_attempts():
    from core.engine.repair_controller import RepairController

    controller = RepairController(
        max_attempts=2
    )

    controller.restore_state(
        "tx-restore",
        1,
    )

    assert controller.get_attempts("tx-restore") == 1
    assert controller.can_repair("tx-restore")

    controller.restore_state(
        "tx-restore",
        2,
    )

    assert controller.get_attempts("tx-restore") == 2
    assert not controller.can_repair("tx-restore")


def test_repair_controller_enforces_attempt_limit():
    from core.engine.repair_controller import RepairController

    controller = RepairController(
        max_attempts=2
    )

    transaction_id = "tx-limit"

    assert controller.can_repair(transaction_id) is True

    for _ in range(controller.max_attempts):
        assert controller.register_attempt(
            transaction_id
        ) is True

    assert controller.can_repair(
        transaction_id
    ) is False

    assert controller.register_attempt(
        transaction_id
    ) is False


def test_repair_controller_state_lifecycle():
    from core.engine.repair_controller import RepairController

    controller = RepairController(
        max_attempts=2
    )

    tx = "tx-lifecycle"

    controller.start(tx)

    assert controller.get_attempts(tx) == 0
    assert controller.remaining(tx) == 2
    assert controller.can_repair(tx) is True

    assert controller.register_attempt(tx) is True
    assert controller.get_attempts(tx) == 1
    assert controller.remaining(tx) == 1

    assert controller.register_attempt(tx) is True
    assert controller.get_attempts(tx) == 2
    assert controller.remaining(tx) == 0

    assert controller.exhausted(tx) is True
    assert controller.register_attempt(tx) is False


def test_repair_controller_restore_preserves_limit():
    from core.engine.repair_controller import RepairController

    controller = RepairController(
        max_attempts=2
    )

    controller.restore_state(
        "tx-restored",
        1,
    )

    assert controller.get_attempts(
        "tx-restored"
    ) == 1

    assert controller.remaining(
        "tx-restored"
    ) == 1

    assert controller.can_repair(
        "tx-restored"
    ) is True

    assert controller.register_attempt(
        "tx-restored"
    ) is True

    assert controller.exhausted(
        "tx-restored"
    ) is True


def test_repair_state_survives_task_history_reload(tmp_path):
    from core.memory.task_history import TaskHistory

    storage = tmp_path / "tasks.json"

    history = TaskHistory(
        str(storage)
    )

    history.create(
        approval_id="approval-persist",
        instruction="corrigir teste",
        plan={
            "changes": [],
            "tests": [],
        },
    )

    repair_state = {
        "transaction_id": "tx-persist",
        "status": "failed",
        "attempts": 2,
        "max_attempts": 2,
        "last_error": "falha de teste",
        "last_action": "modify",
        "history": [
            {
                "attempt": 1,
                "action": "modify",
                "status": "failed",
                "error": "erro 1",
            },
            {
                "attempt": 2,
                "action": "modify",
                "status": "failed",
                "error": "erro 2",
            },
        ],
    }

    history.update(
        "approval-persist",
        status="failed",
        transaction_id="tx-persist",
        extra={
            "repair_state": repair_state,
            "repair_attempts": 2,
        },
    )

    restored_history = TaskHistory(
        str(storage)
    )

    restored = restored_history.get(
        "approval-persist"
    )

    assert restored is not None
    assert restored["transaction_id"] == "tx-persist"
    assert restored["repair_attempts"] == 2
    assert restored["repair_state"]["attempts"] == 2
    assert restored["repair_state"]["max_attempts"] == 2
    assert len(
        restored["repair_state"]["history"]
    ) == 2


def test_repair_cycle_state_restores_persisted_limit():
    data = {
        "transaction_id": "tx-limit-persisted",
        "status": "failed",
        "attempts": 2,
        "max_attempts": 2,
        "last_error": "limite",
        "last_action": "modify",
        "history": [],
    }

    state = RepairCycleState.from_dict(
        data
    )

    assert state.attempts == 2
    assert state.max_attempts == 2
    assert not state.can_continue()


def test_repair_cycle_state_default_limit_matches_gateway_policy():
    state = RepairCycleState(
        "tx-policy"
    )

    assert state.max_attempts == 2


def test_repair_cycle_state_remaining_attempts():
    state = RepairCycleState(
        "tx-remaining",
        max_attempts=2,
    )

    assert state.remaining() == 2

    state.record(
        "modify",
        "failed",
        "erro 1",
    )

    assert state.remaining() == 1

    state.record(
        "modify",
        "failed",
        "erro 2",
    )

    assert state.remaining() == 0
    assert state.exhausted()
    assert not state.can_continue()


def test_repair_cycle_state_status_lifecycle():
    state = RepairCycleState(
        "tx-lifecycle"
    )

    state.mark_analyzing()
    assert state.status == "analyzing"

    state.mark_repairing()
    assert state.status == "repairing"

    state.mark_testing()
    assert state.status == "testing"

    state.mark_verified()
    assert state.status == "verified"

    state.mark_committed()
    assert state.status == "committed"

    assert not state.can_continue()


def test_repair_cycle_state_restore_preserves_default_policy():
    data = {
        "transaction_id": "tx-policy-restore",
        "status": "pending",
        "attempts": 0,
        "last_error": "",
        "last_action": "",
        "history": [],
    }

    state = RepairCycleState.from_dict(
        data
    )

    assert state.max_attempts == 2
    assert state.can_continue()


def test_repair_cycle_state_persist_updates_transaction():
    from core.schemas.models import Transaction

    transaction = Transaction(
        transaction_id="tx-persist",
    )

    state = RepairCycleState(
        transaction_id="tx-persist",
        max_attempts=2,
    )

    state.mark_analyzing()
    state.last_action = "modify"
    state.persist(transaction)

    assert transaction.repair_state["status"] == "analyzing"
    assert transaction.repair_state["transaction_id"] == "tx-persist"
    assert transaction.metadata["repair_cycle"]["status"] == "analyzing"
    assert transaction.metadata["repair_cycle"]["max_attempts"] == 2
    assert transaction.metadata["repair_cycle"]["remaining"] == 2
