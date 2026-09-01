from core.memory.task_history import TaskHistoryStatus


def test_task_history_status_contract():
    assert TaskHistoryStatus.PENDING.value == "pending"
    assert TaskHistoryStatus.REPAIRING.value == "repairing"
    assert TaskHistoryStatus.EXECUTING.value == "executing"
    assert TaskHistoryStatus.TESTING.value == "testing"
    assert TaskHistoryStatus.COMMITTED.value == "committed"
    assert TaskHistoryStatus.ROLLED_BACK.value == "rolled_back"
    assert TaskHistoryStatus.FAILED.value == "failed"
    assert TaskHistoryStatus.REJECTED.value == "rejected"


def test_task_history_status_is_string_enum():
    for status in TaskHistoryStatus:
        assert isinstance(status.value, str)


def test_task_history_status_values_are_unique():
    values = [status.value for status in TaskHistoryStatus]
    assert len(values) == len(set(values))


def test_task_history_status_contains_only_history_lifecycle_states():
    assert {status.value for status in TaskHistoryStatus} == {
        "pending",
        "repairing",
        "executing",
        "testing",
        "committed",
        "rolled_back",
        "failed",
        "rejected",
    }


def test_task_history_status_is_compatible_with_string_comparisons():
    assert TaskHistoryStatus.PENDING == "pending"
    assert TaskHistoryStatus.COMMITTED == "committed"
    assert TaskHistoryStatus.FAILED == "failed"
