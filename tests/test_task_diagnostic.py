import copy
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

import api
from core.api.service import APIService
from core.api.task_diagnostic import diagnose_task


@pytest.mark.parametrize("task,category", [
    ({"status": "pending"}, "pending"),
    ({"status": "rejected"}, "rejected"),
    *[({"status": status}, "in_progress") for status in
      ("approved", "executing", "testing", "running", "repairing")],
    ({"status": "committed", "tests": {"success": True, "returncode": 0}}, "completed"),
    ({"status": "committed"}, "completed"),
    ({"status": "committed", "tests": {"success": False}}, "inconsistent"),
    ({"status": "committed", "tests": {"returncode": 1}}, "inconsistent"),
    ({"status": "rolled_back", "tests": {"success": True, "returncode": -15}}, "inconsistent"),
    ({"status": "rolled_back", "tests": {"success": False, "returncode": -15}}, "interrupted"),
    ({"status": "failed", "tests": {"returncode": 1}}, "test_failure"),
    ({"status": "failed", "tests": {"success": False, "returncode": 0}}, "test_failure"),
    ({"status": "rolled_back"}, "failure"),
    ({"status": "failed", "tests": {"success": True, "returncode": 0}}, "failure"),
    ({"status": "unknown"}, "insufficient_data"),
    ({"status": "PRIVATE_STATUS"}, "insufficient_data"),
    ({"status": []}, "insufficient_data"),
    ({}, "insufficient_data"),
    ({"status": "rolled_back", "rollback_error": "PRIVATE_ERROR"}, "rollback_failure"),
])
def test_classifies_recorded_facts_without_claiming_root_cause(task, category):
    before = copy.deepcopy(task)
    report = diagnose_task(task)
    assert report["category"] == category
    assert report["summary"] and report["evidence"] and report["next_steps"]
    assert "sem chamada à IA" in report["limitations"]
    assert task == before


@pytest.mark.parametrize("tests,attempts,git", [
    (None, None, None), ([], [], []), ("PRIVATE", {}, "PRIVATE"),
    ({"success": "false", "returncode": "0"}, -1, {"commit_hash": {}}),
    ({"success": 1, "returncode": True}, True, {"commit_hash": ""}),
    ({"success": False, "returncode": -65536}, 65536, {}),
    ({"success": True, "returncode": 65536}, 0, {"commit_hash": "abc123"}),
])
def test_missing_or_malformed_fields_are_not_coerced(tests, attempts, git):
    report = diagnose_task({"tests": tests, "repair_attempts": attempts, "git": git})
    assert report["evidence"][1] == "Código de saída: Não informado"
    assert "PRIVATE" not in json.dumps(report)


def test_report_excludes_raw_content_and_internal_fields():
    task = {"status": "rolled_back", "tests": {"success": False, "returncode": -15,
            "stdout": "PRIVATE_OUTPUT", "stderr": "PRIVATE_STDERR"},
            "repair_attempts": 0, "error": "PRIVATE_ERROR",
            "instruction": "PRIVATE_INSTRUCTION", "plan": {"secret": "PRIVATE_PLAN"},
            "metadata": "PRIVATE_METADATA", "repair": "PRIVATE_REPAIR",
            "git": {"commit_hash": "PRIVATE_HASH", "message": "PRIVATE_MESSAGE"}}
    report = diagnose_task(task)
    assert "PRIVATE" not in json.dumps(report)
    assert report["category"] == "interrupted"
    assert "não comprova timeout" in report["next_steps"][0]
    assert "Tentativas de reparo: 0" in report["evidence"]
    assert "Hash do commit: Disponível" in report["evidence"]


class ReadGateway:
    def __init__(self, task):
        self.task = task
        self.calls = []

    def get_task(self, task_id):
        self.calls.append(task_id)
        return self.task

    def __getattr__(self, name):
        raise AssertionError("Operação não autorizada no diagnóstico: " + name)


def test_service_uses_only_public_task_read_and_preserves_input():
    task = {"approval_id": "166", "status": "committed", "metadata": "PRIVATE"}
    before = copy.deepcopy(task)
    gateway = ReadGateway(task)
    service = APIService(object(), gateway)
    assert service.task_diagnostic("166")["approval_id"] == "166"
    assert gateway.calls == ["166"]
    assert task == before


def test_service_handles_missing_task_and_mismatched_identifier():
    assert APIService(object(), ReadGateway(None)).task_diagnostic("166") is None
    with pytest.raises(ValueError, match="identificador"):
        APIService(object(), ReadGateway({"approval_id": "167"})).task_diagnostic("166")


def test_real_gateway_diagnostic_does_not_change_persisted_project(isolated_project):
    from agent import DevAgent
    from core.adapters.mock import MockAdapter
    from core.gateway import DevAgentGateway

    agent = DevAgent(str(isolated_project), ai_adapter=MockAdapter())
    gateway = DevAgentGateway(agent, str(isolated_project))
    gateway.history.create("166", "PRIVATE_INSTRUCTION", {"changes": []})
    def snapshot():
        return {str(path.relative_to(isolated_project)): path.read_bytes()
                for path in isolated_project.rglob("*") if path.is_file()}
    before = snapshot()
    report = APIService(object(), gateway).task_diagnostic("166")
    assert report["category"] == "pending"
    assert snapshot() == before


@pytest.fixture
def diagnostic_server(monkeypatch):
    gateway = ReadGateway({"approval_id": "166", "status": "committed"})
    monkeypatch.setattr(api, "agent", object())
    monkeypatch.setattr(api, "gateway", gateway)
    server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, gateway
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_report(server, route, method="GET"):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(method, route)
        response = connection.getresponse()
        return response.status, json.loads(response.read()), dict(response.getheaders())
    finally:
        connection.close()


def test_http_diagnostic_returns_report_with_query_and_security_headers(diagnostic_server):
    server, gateway = diagnostic_server
    for route in ("/tasks/166/diagnostic", "/tasks/166/diagnostic?source=studio"):
        status, report, headers = get_report(server, route)
        assert status == 200 and report["category"] == "completed"
        assert headers["Cache-Control"] == "no-cache"
        assert headers["X-Content-Type-Options"] == "nosniff"
    assert gateway.calls == ["166", "166"]


def test_http_diagnostic_missing_mismatch_and_invalid_routes(diagnostic_server):
    server, gateway = diagnostic_server
    gateway.task = None
    assert get_report(server, "/tasks/166/diagnostic")[0] == 404
    gateway.task = {"approval_id": "167"}
    assert get_report(server, "/tasks/166/diagnostic")[0] == 409
    calls = list(gateway.calls)
    for route, method in [("/tasks//diagnostic", "GET"),
                          ("/tasks/166/diagnostic/extra", "GET"),
                          ("/tasks/166/other", "GET"),
                          ("/tasks/166/diagnostic", "POST")]:
        assert get_report(server, route, method)[0] == 404
    assert gateway.calls == calls
