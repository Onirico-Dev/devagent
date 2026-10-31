from core.api.service import APIService


class FakeAgent:
    pass


class FakeGateway:
    def __init__(self):
        self.agent = object()
        self.calls = []

    def health(self):
        self.calls.append(("health",))
        return {"status": "ok"}

    def list_tasks(self):
        self.calls.append(("list_tasks",))
        return [{"task_id": "task-1"}]

    def latest_task(self):
        self.calls.append(("latest_task",))
        return {"task_id": "task-1"}

    def get_task(self, task_id):
        self.calls.append(("get_task", task_id))
        return {"task_id": task_id}

    def create_task(self, instruction):
        self.calls.append(("create_task", instruction))
        return {"approval_id": "approval-1"}

    def approve(self, approval_id):
        self.calls.append(("approve", approval_id))
        return {"status": "committed"}

    def reject(self, approval_id):
        self.calls.append(("reject", approval_id))
        return {"status": "rejected"}


def test_health_returns_service_health_contract():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.health()

    assert result == {
        "status": "ok",
        "service": "devagent",
    }
    assert gateway.calls == []


def test_list_tasks_delegates_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.list_tasks()

    assert result == [{"task_id": "task-1"}]
    assert gateway.calls == [("list_tasks",)]


def test_latest_task_delegates_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.latest_task()

    assert result == {"task_id": "task-1"}
    assert gateway.calls == [("latest_task",)]


def test_get_task_delegates_task_id_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.get_task("task-42")

    assert result == {"task_id": "task-42"}
    assert gateway.calls == [("get_task", "task-42")]


def test_create_task_synchronizes_agent_and_delegates_instruction():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.create_task("criar arquivo")

    assert result == {"approval_id": "approval-1"}
    assert gateway.agent is agent
    assert gateway.calls == [("create_task", "criar arquivo")]


def test_approve_delegates_approval_id_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.approve("approval-1")

    assert result == {"status": "committed"}
    assert gateway.calls == [("approve", "approval-1")]


def test_reject_delegates_approval_id_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.reject("approval-1")

    assert result == {"status": "rejected"}
    assert gateway.calls == [("reject", "approval-1")]


def test_task_queries_filter_internal_fields_without_mutating_history():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    internal_task = {
        "task_id": "task-42",
        "approval_id": "task-42",
        "instruction": "criar arquivo",
        "plan": {"changes": []},
        "status": "committed",
        "transaction_id": "transaction-42",
        "created_at": "2026-10-30T10:00:00",
        "updated_at": "2026-10-30T10:01:00",
        "tests": {"success": True},
        "git": {"committed": True},
        "repair_attempts": 1,
        "repair": {"action": "modify"},
        "error": "diagnostic",
        "rollback_error": "rollback diagnostic",
        "metadata": {"backup_integrity": {"secret": "internal"}},
        "repair_state": {"status": "internal"},
        "backup_integrity": {"fingerprint": "internal"},
        "created_identity": {"inode": 123},
        "extra": {"private": True},
    }

    expected = {
        key: value
        for key, value in internal_task.items()
        if key in APIService.PUBLIC_TASK_FIELDS
    }

    gateway.list_tasks = lambda: [internal_task]
    gateway.latest_task = lambda: internal_task
    gateway.get_task = lambda task_id: internal_task

    assert service.list_tasks() == [expected]
    assert service.latest_task() == expected
    assert service.get_task("task-42") == expected

    assert "metadata" in internal_task
    assert "repair_state" in internal_task
    assert "backup_integrity" in internal_task
    assert "created_identity" in internal_task
    assert "extra" in internal_task


def test_latest_and_get_task_preserve_missing_task_result():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    gateway.latest_task = lambda: None
    gateway.get_task = lambda task_id: None

    assert service.latest_task() is None
    assert service.get_task("missing-task") is None
