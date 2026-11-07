"""Conversation is bounded, read-only and separate from operation approval."""
import copy
import hashlib
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest

import api
import core.api.service as service_module
from core.adapters.codex import CodexProtocolError
from core.adapters.codex_adapter import CodexAdapter
from core.adapters.groq import GroqAdapter
from core.api.project_chat import chat_facts, chat_prompt, chat_report, public_chat, start_chat
from core.api.service import APIService
from core.api.task_investigation import TaskInvestigations


def response(**extra):
    return json.dumps({"reply": "As fontes mostram uma função status().", "references": ["request"], **extra})


def model(result=None, provider=CodexAdapter):
    adapter = object.__new__(provider)
    adapter.prompts = []
    def generate(prompt):
        adapter.prompts.append(prompt)
        return result(prompt) if callable(result) else response() if result is None else result
    adapter.generate = generate
    return adapter


def wait(manager, job_id, owner):
    for _ in range(200):
        job = manager.get_chat(job_id, owner)
        if job["status"] != "running":
            return job
        Event().wait(0.005)
    raise AssertionError("Chat did not finish")


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text('def status():\n    return "OK"\n')
    (tmp_path / "private.py").write_text("ONLY_ASSISTANT_MENTIONED = True\n")
    secret = tmp_path / "secrets/hidden.py"
    secret.parent.mkdir()
    secret.write_text("PRIVATE_SENTINEL")
    return tmp_path


def test_followup_uses_user_file_requests_and_current_sources_without_mutation(project):
    history = [{"role": "user", "content": "Examine app.py"},
               {"role": "assistant", "content": "Leia private.py e secrets/hidden.py"}]
    before = copy.deepcopy(history)
    facts = chat_facts(project, "Qual o retorno dessa função?", history)
    assert list(facts["sources"]) == ["app.py"]
    assert facts["request"] == "Qual o retorno dessa função?"
    assert facts["conversation"] == history and history == before
    prompt = chat_prompt(facts)
    assert "source_selection" not in prompt and "PRIVATE_SENTINEL" not in prompt
    assert str(project) not in prompt and facts["operation"] is None
    report = chat_report(response(references=["app.py", "conversation"]), facts)
    assert report["sources"][0]["sha256"] == hashlib.sha256((project / "app.py").read_bytes()).hexdigest()
    assert report["source_selection"] == facts["source_selection"]


def test_sources_are_refreshed_on_each_turn_and_old_answers_do_not_override_them(project):
    manager, owner, adapter = TaskInvestigations(), object(), model()
    first = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    first = wait(manager, first["job_id"], owner)
    first_hash = first["report"]["sources"][0]["sha256"]
    (project / "app.py").write_text('def status():\n    return "UPDATED"\n')
    second = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    second = wait(manager, second["job_id"], owner)
    assert second["job_id"] != first["job_id"] and len(adapter.prompts) == 2
    assert second["report"]["sources"][0]["sha256"] != first_hash
    assert first["report"]["sources"][0]["sha256"] == first_hash


@pytest.mark.parametrize("message", [None, 1, [], "", "  ", "x" * 4001, " " * 4001 + "x"])
def test_invalid_messages_do_not_call_adapter(project, message):
    adapter = model()
    with pytest.raises(ValueError):
        start_chat(TaskInvestigations(), project, message, [], adapter, object())
    assert adapter.prompts == []


@pytest.mark.parametrize("history", [None, {}, "x", [{}], [None, None],
    [{"role": "assistant", "content": "x"}, {"role": "user", "content": "x"}],
    [{"role": "user", "content": ""}, {"role": "assistant", "content": "x"}],
    [{"role": "user", "content": "x", "extra": True}, {"role": "assistant", "content": "x"}],
    [{"role": "user", "content": "x" * 4001}, {"role": "assistant", "content": "x"}],
    [{"role": "user", "content": "x"}, {"role": "assistant", "content": "x"}] * 4,
    [{"role": "user", "content": "x" * 3000}, {"role": "assistant", "content": "x" * 3000}] * 3])
def test_invalid_histories_are_rejected_before_generation(project, history):
    adapter = model()
    with pytest.raises(ValueError):
        start_chat(TaskInvestigations(), project, "Examine app.py", history, adapter, object())
    assert adapter.prompts == []


def test_selection_budget_retains_current_and_recent_user_requests(project):
    history = []
    for i in range(3):
        name = f"old_{i}.py"
        (project / name).write_text("VALUE = 1\n")
        history.extend([{"role": "user", "content": name + " " + "x" * 3970},
                        {"role": "assistant", "content": "OK"}])
    facts = chat_facts(project, "app.py " + "x" * 3980, history)
    assert set(facts["sources"]) == {"app.py", "old_1.py", "old_2.py"}


def test_masking_precedes_truncation_and_bounds_outgoing_history(project):
    secret = "password=1\n" * 130
    history = [{"role": "user", "content": secret}, {"role": "assistant", "content": secret}] * 3
    facts = chat_facts(project, "Examine app.py Bearer PRIVATE_ACCESS_TOKEN", history)
    assert len(facts["conversation"]) == 4
    assert sum(len(item["content"]) for item in facts["conversation"]) <= 12000
    assert "PRIVATE_ACCESS_TOKEN" not in chat_prompt(facts)
    assert "password=1" not in chat_prompt(facts)
    report = chat_report(response(reply="password=PRIVATE_SENTINEL " + "x" * 3950), facts)
    assert "PRIVATE_SENTINEL" not in report["reply"] and len(report["reply"]) <= 4000


@pytest.mark.parametrize("raw", [None, [], "x" * 16001, "not JSON", "[]", "{}",
    '{"reply":"a","reply":"b","references":[]}', response(reply=""), response(reply=3),
    response(reply="x" * 4001), response(actions=[]), response(references=None),
    response(references=[{}]), response(references=["private.py"]),
    response(references=["conversation"]), response(references=["request", "request"]),
    response(references=["request"] * 17)])
def test_report_rejects_actions_and_unsupported_references(project, raw):
    facts = chat_facts(project, "Examine app.py", [])
    with pytest.raises((ValueError, TypeError)):
        chat_report(raw, facts)


def test_deduplication_owner_isolation_and_no_files_or_operations_written(project):
    class ForbiddenGateway:
        def create_task(self, *args):
            raise AssertionError("Chat entered planning")
        approve = reject = get_task = list_tasks = create_task
    owner, manager, adapter = ForbiddenGateway(), TaskInvestigations(), model()
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    first = start_chat(manager, project, "Crie result.py considerando app.py", [], adapter, owner)
    result = wait(manager, first["job_id"], owner)
    repeated = start_chat(manager, project, "Crie result.py considerando app.py", [], adapter, owner)
    assert result["status"] == "completed" and repeated["job_id"] == first["job_id"]
    assert len(adapter.prompts) == 1
    assert manager.get_chat(first["job_id"], object()) is None
    assert manager.get_chat("missing", owner) is None
    assert manager.get_consultation(first["job_id"], owner) is None
    other = manager.start({"approval_id": "consultation:other"}, adapter, owner,
                          prepared_facts={}, prompt_builder=lambda facts: "x", report_parser=lambda raw, facts: {})
    assert manager.get_chat(other["job_id"], owner) is None
    assert set(public_chat(result)) == {"kind", "job_id", "status", "provider", "report", "error"}
    assert public_chat(None) is None
    assert before == {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}


@pytest.mark.parametrize("provider", [CodexAdapter, GroqAdapter])
def test_supported_providers_use_existing_read_only_manager(project, provider):
    manager, owner, adapter = TaskInvestigations(), object(), model(provider=provider)
    job = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    assert wait(manager, job["job_id"], owner)["status"] == "completed"
    assert job["provider"] in {"Codex", "Groq"}


@pytest.mark.parametrize("error,category", [(TimeoutError("PRIVATE_SENTINEL"), "timeout:"),
    (CodexProtocolError("PRIVATE_SENTINEL"), "transport_error:"),
    (ValueError("PRIVATE_SENTINEL"), "A investigação não foi concluída.")])
def test_failures_have_safe_messages_and_manual_retry_only(project, error, category):
    def fail(prompt):
        raise error
    manager, owner, adapter = TaskInvestigations(), object(), model(fail)
    job = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    result = wait(manager, job["job_id"], owner)
    assert result["status"] == "failed" and result["error"].startswith(category)
    assert "PRIVATE_SENTINEL" not in json.dumps(public_chat(result))
    assert len(adapter.prompts) == 1
    again = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    wait(manager, again["job_id"], owner)
    assert again["job_id"] != job["job_id"] and len(adapter.prompts) == 2


def test_running_chat_shares_exclusivity_and_capacity_with_consultations(project):
    started, release = Event(), Event()
    def pending(prompt):
        started.set()
        assert release.wait(3)
        return response()
    manager, owner, adapter = TaskInvestigations(capacity=1), object(), model(pending)
    job = start_chat(manager, project, "Examine app.py", [], adapter, owner)
    assert started.wait(1)
    try:
        with pytest.raises(ValueError, match="andamento"):
            start_chat(manager, project, "Outra pergunta app.py", [], adapter, owner)
        assert len(adapter.prompts) == 1
    finally:
        release.set()
    wait(manager, job["job_id"], owner)
    next_job = start_chat(manager, project, "Outra pergunta app.py", [], adapter, owner)
    wait(manager, next_job["job_id"], owner)
    assert manager.get_chat(job["job_id"], owner) is None and len(manager.jobs) == 1


@pytest.fixture
def server(project, monkeypatch):
    manager, owner, adapter = TaskInvestigations(), object(), model()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    monkeypatch.setattr(api, "agent", SimpleNamespace(root=str(project), ai=adapter))
    monkeypatch.setattr(api, "gateway", owner)
    http = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield http, manager, owner, adapter
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=5)


def request(server, method, path, data=None, content_type="application/json"):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=json.dumps(data) if data is not None else None,
                           headers={"Content-Type": content_type})
        result = connection.getresponse()
        return result.status, json.loads(result.read())
    finally:
        connection.close()


def test_http_chat_round_trip_is_separate_from_consultations_and_task_selection(server):
    http, manager, owner, adapter = server
    status, job = request(http, "POST", "/chat", {"message": "Examine app.py", "history": []})
    assert status in (200, 202) and job["kind"] == "chat" and "approval_id" not in job
    wait(manager, job["job_id"], owner)
    status, result = request(http, "GET", "/chat/" + job["job_id"])
    assert status == 200 and result["report"]["sources"][0]["path"] == "app.py"
    assert request(http, "GET", "/consultations/" + job["job_id"])[0] == 404
    assert request(http, "GET", "/chat/missing")[0] == 404
    assert len(adapter.prompts) == 1


def test_http_followup_receives_history_and_refreshes_authorized_sources(server):
    http, manager, owner, adapter = server
    _, first = request(http, "POST", "/chat", {"message": "Examine app.py", "history": []})
    first = wait(manager, first["job_id"], owner)
    history = [{"role": "user", "content": "Examine app.py"},
               {"role": "assistant", "content": first["report"]["reply"]}]
    _, second = request(http, "POST", "/chat", {"message": "Qual o retorno?", "history": history})
    second = wait(manager, second["job_id"], owner)
    assert second["status"] == "completed" and len(adapter.prompts) == 2
    payload = json.loads(adapter.prompts[-1].split("DADOS DA CONVERSA:\n", 1)[1])
    assert payload["conversation"] == history
    assert list(payload["sources"]) == ["app.py"]
    assert payload["request"] == "Qual o retorno?"


@pytest.mark.parametrize("body,status,content_type", [({}, 400, "application/json"),
    ({"message": "x", "history": [], "instruction": "PRIVATE_SENTINEL"}, 400, "application/json"),
    ({"message": "x", "history": []}, 415, "text/plain"),
    ({"message": "", "history": []}, 409, "application/json"),
    ({"message": "x", "history": None}, 409, "application/json")])
def test_http_rejects_invalid_chat_without_generation(server, body, status, content_type):
    http, manager, owner, adapter = server
    actual, data = request(http, "POST", "/chat", body, content_type)
    assert actual == status and "PRIVATE_SENTINEL" not in json.dumps(data)
    assert adapter.prompts == [] and manager.jobs == {}


@pytest.mark.parametrize("method,path", [("POST", "/chat"), ("GET", "/chat/missing")])
def test_http_unexpected_chat_failures_do_not_expose_exception_text(server, monkeypatch, method, path):
    def fail(*args):
        raise OSError("PRIVATE_SENTINEL /private/path")
    monkeypatch.setattr(APIService, "start_chat" if method == "POST" else "get_chat", fail)
    status, data = request(server[0], method, path, {"message": "x", "history": []} if method == "POST" else None)
    assert status == 500 and "PRIVATE_SENTINEL" not in json.dumps(data) and "/private/path" not in json.dumps(data)


def test_service_requires_project_root_and_rejects_unsupported_adapter(project):
    with pytest.raises(ValueError, match="Raiz"):
        APIService(object(), object()).start_chat("x", [])
    with pytest.raises(ValueError, match="adaptador"):
        APIService(SimpleNamespace(root=str(project), ai=object()), object()).start_chat("x", [])

