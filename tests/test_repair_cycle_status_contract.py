from core.engine.repair_cycle_state import (
    RepairCycleState,
    RepairCycleStatus,
)


def test_repair_cycle_status_enum_values():
    assert {status.value for status in RepairCycleStatus} == {
        "pending",
        "analyzing",
        "repairing",
        "testing",
        "verified",
        "failed",
        "repair_failed",
        "no_repair",
        "limit_reached",
        "rolled_back",
        "committed",
    }


def test_repair_cycle_state_uses_enum_status_values():
    state = RepairCycleState("tx-1")

    assert state.status == RepairCycleStatus.PENDING.value

    state.mark_analyzing()
    assert state.status == RepairCycleStatus.ANALYZING.value

    state.mark_repairing()
    assert state.status == RepairCycleStatus.REPAIRING.value

    state.mark_testing()
    assert state.status == RepairCycleStatus.TESTING.value

    state.mark_verified()
    assert state.status == RepairCycleStatus.VERIFIED.value

    state.mark_failed("error")
    assert state.status == RepairCycleStatus.FAILED.value

    state.mark_repair_failed("error")
    assert state.status == RepairCycleStatus.REPAIR_FAILED.value

    state.mark_rolled_back()
    assert state.status == RepairCycleStatus.ROLLED_BACK.value

    state.mark_committed()
    assert state.status == RepairCycleStatus.COMMITTED.value


def test_repair_cycle_terminal_statuses_block_continuation():
    state = RepairCycleState("tx-1", attempts=0, max_attempts=2)

    state.mark_committed()
    assert state.can_continue() is False

    state.mark_rolled_back()
    assert state.can_continue() is False


def test_repair_cycle_status_values():
    assert RepairCycleStatus.NO_REPAIR.value == "no_repair"
    assert RepairCycleStatus.LIMIT_REACHED.value == "limit_reached"
