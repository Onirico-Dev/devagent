from core.engine.repair_executor import RepairExecutorStatus


def test_repair_executor_status_contract():
    assert RepairExecutorStatus.FAILED.value == "failed"
    assert RepairExecutorStatus.REPAIR_APPLIED.value == "repair_applied"
    assert RepairExecutorStatus.REPAIR_VERIFIED.value == "repair_verified"
    assert RepairExecutorStatus.REPAIR_FAILED.value == "repair_failed"
    assert RepairExecutorStatus.INVALID_TEST_RESULT.value == "invalid_test_result"
