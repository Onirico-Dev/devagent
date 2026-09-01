from core.engine.repair_cycle_state import RepairCycleState


def test_repair_cycle_status_contract():
    state = RepairCycleState("tx-1")

    state.mark_pending()
    assert state.status == "pending"

    state.mark_analyzing()
    assert state.status == "analyzing"

    state.mark_repairing()
    assert state.status == "repairing"

    state.mark_testing()
    assert state.status == "testing"

    state.mark_verified()
    assert state.status == "verified"

    state.mark_repair_failed("falha")
    assert state.status == "repair_failed"

    state.mark_failed("erro")
    assert state.status == "failed"

    state.mark_rolled_back("rollback")
    assert state.status == "rolled_back"

    state.mark_committed()
    assert state.status == "committed"
