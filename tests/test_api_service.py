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
        return ["task-1"]

    def latest_task(self):
        self.calls.append(("latest_task",))
        return {"id": "task-1"}

    def get_task(self, task_id):
        self.calls.append(("get_task", task_id))
        return {"id": task_id}

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

    assert result == ["task-1"]
    assert gateway.calls == [("list_tasks",)]


def test_latest_task_delegates_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.latest_task()

    assert result == {"id": "task-1"}
    assert gateway.calls == [("latest_task",)]


def test_get_task_delegates_task_id_to_gateway():
    agent = FakeAgent()
    gateway = FakeGateway()
    service = APIService(agent, gateway)

    result = service.get_task("task-42")

    assert result == {"id": "task-42"}
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
