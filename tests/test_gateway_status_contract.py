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

def test_gateway_create_task_reuses_equivalent_pending_proposal(tmp_path):
    class Agent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [],
            }

    gateway = DevAgentGateway(Agent(), str(tmp_path))

    first = gateway.create_task("verificar   projeto")
    second = gateway.create_task("  verificar projeto  ")

    assert first["approval_id"] == second["approval_id"]
    assert len(gateway.list_pending()) == 1


def test_gateway_create_task_deduplicates_concurrent_equivalent_proposals(
    tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor

    class Agent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [],
            }

    def create():
        gateway = DevAgentGateway(Agent(), str(tmp_path))
        return gateway.create_task("verificar   projeto")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: create(), range(8)))

    approval_ids = {
        result["approval_id"]
        for result in results
    }

    assert len(approval_ids) == 1

    gateway = DevAgentGateway(Agent(), str(tmp_path))
    assert len(gateway.list_pending()) == 1

def _create_gateway_task_in_process(root):
    class Agent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [],
            }

    gateway = DevAgentGateway(Agent(), root)
    return gateway.create_task("verificar   projeto")


def test_gateway_create_task_deduplicates_across_processes(tmp_path):
    from concurrent.futures import ProcessPoolExecutor

    root = str(tmp_path)

    with ProcessPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                _create_gateway_task_in_process,
                [root] * 4,
            )
        )

    approval_ids = {
        result["approval_id"]
        for result in results
    }

    assert len(approval_ids) == 1

    class Agent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [],
            }

    gateway = DevAgentGateway(Agent(), root)
    assert len(gateway.list_pending()) == 1
