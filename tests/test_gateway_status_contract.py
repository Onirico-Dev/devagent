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


def test_gateway_list_pending_exposes_task_history_pending_tasks(tmp_path):
    class Agent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [],
            }

    gateway = DevAgentGateway(Agent(), str(tmp_path))

    created = gateway.create_task("verificar projeto")

    pending = gateway.list_pending()

    assert len(pending) == 1
    assert pending[0]["approval_id"] == created["approval_id"]
    assert pending[0]["instruction"] == "verificar projeto"
    assert pending[0]["status"] == TaskHistoryStatus.PENDING.value
