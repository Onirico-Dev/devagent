import copy
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest

import api
import core.api.service as service_module
import core.api.task_investigation as investigation
from core.adapters.codex_adapter import CodexAdapter
from core.adapters.groq import GroqAdapter
from core.adapters.mock import MockAdapter
from core.api.service import APIService


def task(**extra):
    return {"approval_id": "167", "status": "rolled_back", "updated_at": "2026-11-06",
            "tests": {"success": False, "returncode": -15, "stderr": "Processo interrompido"},
            "repair_attempts": 1, **extra}


def report(**extra):
    return {"summary": "O registro não confirma a causa da interrupção.",
            "hypotheses": [{"cause": "Pode ter ocorrido encerramento externo.",
                            "confidence": "baixa", "evidence": ["diagnostic", "stderr"]}],
            "next_steps": ["Confira o motivo do encerramento antes de propor alterações."], **extra}


def adapter(response=None, provider=CodexAdapter):
    instance = object.__new__(provider)
    instance.prompts = []
    def generate(prompt):
        instance.prompts.append(prompt)
        if callable(response):
            return response(prompt)
        return json.dumps(report()) if response is None else response
    instance.generate = generate
    return instance


def wait_job(manager, selected, job, owner):
    # Event.wait yields to the background worker without relying on a fixed delay.
    for _ in range(200):
        current = manager.get(selected, job["job_id"], owner)
        if current["status"] != "running":
            return current
        Event().wait(0.005)
    raise AssertionError("Investigação de teste não terminou.")


def test_prompt_excludes_non_evidence_and_masks_common_credentials():
    selected = task(instruction="PRIVATE_INSTRUCTION", plan={"content": "PRIVATE_PLAN"},
                    metadata="PRIVATE_METADATA", repair="PRIVATE_REPAIR", git={"message": "PRIVATE_MESSAGE"},
                    tests={"stdout": 'api_key="HIDDEN_KEY" password=HIDDEN_PASSWORD\nBearer HIDDEN_BEARER',
                           "stderr": "authorization: Bearer HIDDEN_AUTH\n" + "x" * 5000},
                    error="secret='HIDDEN_SECRET'", rollback_error=[])
    before = copy.deepcopy(selected)
    facts = investigation.investigation_facts(selected)
    prompt = investigation.build_prompt(facts)
    assert "PRIVATE" not in prompt and "HIDDEN_" not in prompt
    assert "[OCULTO]" in prompt and "conteúdo anterior omitido" in facts["stderr"]
    assert len(prompt) < 15000
    assert selected == before
    assert investigation.excerpt({}, 10) is None
    assert investigation.excerpt("", 10) is None
    assert investigation.investigation_facts(task(tests=[]))["stdout"] is None


@pytest.mark.parametrize("raw", [None, [], "x" * 16001, "", "not JSON", "[]", "{}",
    '{"summary":"a","summary":"b"}',
    json.dumps(report(summary=" ")), json.dumps(report(summary="x" * 1201)),
    json.dumps(report(hypotheses=[])), json.dumps(report(hypotheses="bad")),
    json.dumps(report(hypotheses=[{}])), json.dumps(report(hypotheses=[None])),
    json.dumps(report(hypotheses=[{"cause": "a", "confidence": "certa", "evidence": ["diagnostic"]}])),
    json.dumps(report(hypotheses=[{"cause": "a", "confidence": "baixa", "evidence": ["stdout"]}])),
    json.dumps(report(hypotheses=[{"cause": "a", "confidence": "baixa", "evidence": [{}]}])),
    json.dumps(report(next_steps=[])), json.dumps(report(next_steps=[{}])),
    json.dumps({**report(), "changes": []}),
])
def test_invalid_model_responses_are_rejected(raw):
    with pytest.raises((ValueError, TypeError)):
        investigation.parse_report(raw, investigation.investigation_facts(task()))


@pytest.mark.parametrize("provider,label", [(CodexAdapter, "Codex"), (GroqAdapter, "Groq")])
def test_known_adapters_return_validated_report_and_reuse_identical_result(provider, label):
    ai = adapter(provider=provider)
    manager = investigation.TaskInvestigations()
    owner = object()
    selected = task()
    job = manager.start(selected, ai, owner)
    current = wait_job(manager, selected, job, owner)
    assert current["status"] == "completed" and current["report"] == report()
    assert current["provider"] == label and current["error"] is None
    assert manager.start(selected, ai, owner)["job_id"] == job["job_id"]
    assert len(ai.prompts) == 1
    assert "owner" not in current and "key" not in current and "adapter" not in current
    assert manager.get(selected, "missing", owner) is None
    assert manager.get(selected, job["job_id"], object()) is None
    assert manager.get(task(approval_id="168"), job["job_id"], owner) is None
    with pytest.raises(ValueError, match="mudaram"):
        manager.get(task(updated_at="changed"), job["job_id"], owner)


@pytest.mark.parametrize("ai", [None, object(), MockAdapter()])
def test_unknown_or_mock_adapter_does_not_start_job(ai):
    manager = investigation.TaskInvestigations()
    with pytest.raises(ValueError, match="Codex ou Groq"):
        manager.start(task(), ai, object())
    assert manager.jobs == {}


def test_pending_job_deduplicates_and_allows_reads_without_waiting():
    entered, release = Event(), Event()
    def generate(prompt):
        entered.set()
        assert release.wait(5)
        return json.dumps(report())
    ai = adapter(generate)
    owner = object()
    manager = investigation.TaskInvestigations()
    selected = task()
    try:
        job = manager.start(selected, ai, owner)
        assert entered.wait(2)
        assert job["status"] == "running"
        assert manager.get(selected, job["job_id"], owner)["status"] == "running"
        assert manager.start(selected, ai, owner)["job_id"] == job["job_id"]
        with pytest.raises(ValueError, match="em andamento"):
            manager.start(task(approval_id="168"), ai, owner)
        assert len(ai.prompts) == 1
    finally:
        release.set()
    assert wait_job(manager, selected, job, owner)["status"] == "completed"


def test_failures_do_not_expose_adapter_errors_and_retry_is_possible():
    def fail(prompt):
        raise TimeoutError("PRIVATE_TRANSPORT_DETAILS")
    ai = adapter(fail)
    manager = investigation.TaskInvestigations(capacity=1)
    owner = object()
    selected = task()
    first = manager.start(selected, ai, owner)
    current = wait_job(manager, selected, first, owner)
    assert current["status"] == "failed" and "PRIVATE" not in json.dumps(current)
    ai.generate = lambda prompt: json.dumps(report())
    second = manager.start(selected, ai, owner)
    assert second["job_id"] != first["job_id"]
    assert wait_job(manager, selected, second, owner)["status"] == "completed"
    assert manager.get(selected, first["job_id"], owner) is None


def test_failure_to_start_worker_is_reported(monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError("PRIVATE_THREAD_DETAILS")
    monkeypatch.setattr(investigation, "Thread", BrokenThread)
    current = investigation.TaskInvestigations().start(task(), adapter(), object())
    assert current["status"] == "failed" and "PRIVATE" not in json.dumps(current)


class ReadGateway:
    def __init__(self, selected):
        self.selected = selected
        self.calls = []
    def get_task(self, task_id):
        self.calls.append(task_id)
        return self.selected
    def __getattr__(self, name):
        raise AssertionError("Somente consulta da tarefa autorizada: " + name)


def test_service_uses_only_public_task_read_and_adapter(monkeypatch):
    manager = investigation.TaskInvestigations()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    selected = task(metadata="PRIVATE_METADATA")
    gateway = ReadGateway(selected)
    ai = adapter()
    service = APIService(SimpleNamespace(ai=ai), gateway)
    job = service.start_task_investigation("167")
    wait_job(manager, selected, job, gateway)
    assert service.get_task_investigation("167", job["job_id"])["status"] == "completed"
    assert gateway.calls == ["167", "167"]
    assert "PRIVATE_METADATA" not in ai.prompts[0]
    gateway.selected = None
    assert service.start_task_investigation("167") is None
    assert service.get_task_investigation("167", job["job_id"]) is None
    gateway.selected = task(approval_id="wrong")
    with pytest.raises(ValueError, match="identificador"):
        service.start_task_investigation("167")
    with pytest.raises(ValueError, match="identificador"):
        service.get_task_investigation("167", job["job_id"])


def test_real_gateway_investigation_does_not_write_project_or_create_plan(isolated_project, monkeypatch):
    from agent import DevAgent
    from core.gateway import DevAgentGateway
    ai = adapter()
    agent = DevAgent(str(isolated_project), ai_adapter=ai)
    gateway = DevAgentGateway(agent, str(isolated_project))
    gateway.history.create("167", "PRIVATE_INSTRUCTION", {"changes": []})
    def snapshot():
        return {str(path.relative_to(isolated_project)): path.read_bytes()
                for path in isolated_project.rglob("*") if path.is_file()}
    before = snapshot()
    manager = investigation.TaskInvestigations()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    selected = gateway.get_task("167")
    ai.generate = lambda prompt: json.dumps(report(hypotheses=[{
        "cause": "Os dados não confirmam execução.", "confidence": "baixa", "evidence": ["diagnostic"]}]))
    job = APIService(agent, gateway).start_task_investigation("167")
    assert wait_job(manager, selected, job, gateway)["status"] == "completed"
    assert snapshot() == before


@pytest.fixture
def investigation_server(monkeypatch):
    manager = investigation.TaskInvestigations()
    gateway = ReadGateway(task())
    ai = adapter()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    monkeypatch.setattr(api, "agent", SimpleNamespace(ai=ai))
    monkeypatch.setattr(api, "gateway", gateway)
    server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, gateway, ai, manager
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read()), dict(response.getheaders())
    finally:
        connection.close()


def start(server, path="/tasks/167/investigation"):
    return request(server, "POST", path, "{}", {"Content-Type": "application/json"})


def test_http_investigation_completes_and_keeps_health_responsive(investigation_server):
    server, gateway, ai, manager = investigation_server
    entered, release = Event(), Event()
    def generate(prompt):
        entered.set()
        assert release.wait(5)
        return json.dumps(report())
    ai.generate = generate
    try:
        status, job, headers = start(server, "/tasks/167/investigation?source=studio")
        assert status == 202 and entered.wait(2)
        assert headers["Cache-Control"] == "no-cache" and headers["X-Content-Type-Options"] == "nosniff"
        assert request(server, "GET", "/health")[0] == 200
        assert request(server, "GET", "/tasks/167")[0] == 200
        assert start(server)[1]["job_id"] == job["job_id"]
        route = "/tasks/167/investigation/" + job["job_id"]
        assert request(server, "GET", route)[1]["status"] == "running"
    finally:
        release.set()
    wait_job(manager, gateway.selected, job, gateway)
    assert request(server, "GET", route + "?source=studio")[1]["report"] == report()
    assert start(server)[0] == 200
    gateway.selected = task(updated_at="changed")
    assert request(server, "GET", route)[0] == 409


def test_http_missing_unsupported_and_mismatched_tasks(investigation_server):
    server, gateway, ai, manager = investigation_server
    gateway.selected = None
    assert start(server)[0] == 404
    assert request(server, "GET", "/tasks/167/investigation/missing")[0] == 404
    gateway.selected = task(approval_id="wrong")
    assert start(server)[0] == 409
    gateway.selected = task()
    assert request(server, "GET", "/tasks/167/investigation/missing")[0] == 404


@pytest.mark.parametrize("body,headers,expected", [
    ("{}", {}, 415), ("{}", {"Content-Type": "text/plain"}, 415),
    ("{}", {"Content-Type": "application/json", "Content-Length": "bad"}, 400),
    ("{}", {"Content-Type": "application/json", "Content-Length": "0"}, 400),
    ("x" * 65, {"Content-Type": "application/json"}, 400),
    ("bad JSON", {"Content-Type": "application/json"}, 400),
    ("[]", {"Content-Type": "application/json"}, 400),
    ('{"instruction":"unexpected"}', {"Content-Type": "application/json"}, 400),
])
def test_http_rejects_unrequested_payloads_without_calling_ai(investigation_server, body, headers, expected):
    server, gateway, ai, manager = investigation_server
    assert request(server, "POST", "/tasks/167/investigation", body, headers)[0] == expected
    assert ai.prompts == [] and gateway.calls == [] and manager.jobs == {}


@pytest.mark.parametrize("method,path", [
    ("GET", "/tasks/167/investigation"), ("POST", "/tasks/167/investigation/missing"),
    ("POST", "/tasks//investigation"), ("GET", "/tasks//investigation/job"),
    ("GET", "/tasks/167/investigation/job/extra"), ("GET", "/tasks/167/investigation/"),
])
def test_http_invalid_routes_do_not_start_investigation(investigation_server, method, path):
    server, gateway, ai, manager = investigation_server
    assert request(server, method, path)[0] == 404
    assert ai.prompts == [] and manager.jobs == {}
