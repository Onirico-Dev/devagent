from core.gateway import DevAgentGateway
from core.memory.task_history import TaskHistoryStatus


def test_gateway_history_status_contract_values_are_defined():
    expected = {
        "pending",
        "repairing",
        "executing",
        "testing",
        "committed",
        "rolled_back",
        "failed",
        "rejected",
    }

    actual = {status.value for status in TaskHistoryStatus}

    assert actual == expected


def test_gateway_history_status_writes_use_task_history_status_contract():
    source = open("core/gateway.py", encoding="utf-8").read()

    for status in TaskHistoryStatus:
        assert (
            f'status="{status.value}"' not in source
            or status.value in {"failed", "repairing", "executing", "testing",
                                "committed", "rolled_back", "rejected"}
        )


def test_gateway_exposes_expected_history_status_contract():
    expected = {
        "PENDING": "pending",
        "REPAIRING": "repairing",
        "EXECUTING": "executing",
        "TESTING": "testing",
        "COMMITTED": "committed",
        "ROLLED_BACK": "rolled_back",
        "FAILED": "failed",
        "REJECTED": "rejected",
    }

    actual = {
        name: member.value
        for name, member in TaskHistoryStatus.__members__.items()
    }

    assert actual == expected
