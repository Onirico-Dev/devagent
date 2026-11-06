import copy
import hashlib
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

import api
import core.api.service as service_module
from core.adapters.codex_adapter import CodexAdapter
from core.api.project_consultation import consultation_facts, consultation_prompt, consultation_report, public_consultation, start_consultation
from core.api.service import APIService
from core.api.task_investigation import TaskInvestigations
from core.context.project_context import ProjectContext
from core.planner.ai_planner import AIPlanner
from core.planner.request_intent import has_requested_changes, is_read_only_request


READ_ONLY = """Investigue a divergência entre seis testes aprovados e código -15.
Examine o TestRunner, timeout, supervisão e gerenciamento de processos.
Não modificar arquivos nesta operação.
Não executar reparos automáticos.
Não alterar configurações de timeout.
Não criar commits.
Não presumir que SIGTERM significa timeout.
Não executar novamente a suíte completa sem autorização.
Produzir relatório com evidências, hipóteses e proposta de correção se justificável."""


@pytest.mark.parametrize("instruction,changes,readonly", [
    (READ_ONLY, False, True),
    ("Analise somente de leitura core/executor/test_runner.py", False, True),
    ("Investigue sem alterações e sem escrita.", False, True),
    ("Analise sem modificar nem alterar arquivos.", False, True),
    ("Crie novo.py", True, False),
    ("Crie novo.py. Não modificar outros arquivos.", True, False),
    ("Analise e corrija test.py. Não criar commits.", True, False),
    ("Sem alterar api.py, adicione um botão.", True, False),
    ("Não alterar A, mas crie B.", True, False),
    ("Analise; não modifique A e crie B.", True, False),
    ("Não só crie A; valide também.", True, False),
    ("Não deixe de corrigir A.", True, False),
    ("Analise create.py e core/modify.py", False, False),
    ("Do not modify files", False, False),
    ("criar alterar modificar corrigir remover", True, False),
])
def test_read_only_intent_respects_negated_requests_and_real_changes(instruction, changes, readonly):
    assert has_requested_changes(instruction) is changes
    assert is_read_only_request(instruction) is readonly
    assert AIPlanner(object())._requires_change(instruction) is changes


def test_direct_planner_does_not_turn_read_only_query_into_pending_empty_plan():
    class ForbiddenAI:
        def generate(self, prompt):
            raise AssertionError("Não deve chamar IA de planejamento.")
    with pytest.raises(ValueError, match="Consultar sem alterar"):
        AIPlanner(ForbiddenAI()).create_plan(READ_ONLY)


def report(**extra):
    return {"summary": "As evidências disponíveis não identificam quem encerrou o processo.",
            "findings": [{"text": "O relato informa código -15.", "evidence": ["request"]}],
            "hypotheses": [{"cause": "Uma interrupção externa é possível.", "confidence": "baixa", "evidence": ["request"]}],
            "next_steps": ["Obtenha os registros do processo e a versão executada."],
            "missing_information": ["Registro histórico do envio do sinal."],
            "correction_proposal": None, **extra}


def ai(response=None):
    instance = object.__new__(CodexAdapter)
    instance.prompts = []
    def generate(prompt):
        instance.prompts.append(prompt)
        return response(prompt) if callable(response) else json.dumps(report())
    instance.generate = generate
    return instance


def wait(manager, owner, job_id):
    for _ in range(200):
        result = manager.get_consultation(job_id, owner)
        if result["status"] != "running":
            return result
        Event().wait(0.005)
    raise AssertionError("Consulta de teste não terminou.")


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "core/executor/test_runner.py"
    source.parent.mkdir(parents=True)
    source.write_text('VALUE = "TEST_RUNNER_SOURCE"\napi_key = "HIDDEN_CREDENTIAL"\n')
    return tmp_path


def test_context_reads_permitted_sources_masks_values_and_excludes_private_aliases(project, monkeypatch):
    for name in ("secrets/private.py", "backups/private.py", ".ssh/private.py", ".env", ".env.extra"):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_SOURCE")
    (project / "alias.py").symlink_to(project / "secrets/private.py")
    seen = []
    original = ProjectContext.read_file
    def tracked(self, path, **kwargs):
        seen.append(str(path))
        return original(self, path, **kwargs)
    monkeypatch.setattr(ProjectContext, "read_file", tracked)
    selected = {"approval_id": "158", "status": "rolled_back", "instruction": "PRIVATE_INSTRUCTION", "metadata": "PRIVATE_METADATA"}
    facts = consultation_facts(project, READ_ONLY + " secrets/private.py alias.py .env .env.extra backups/private.py .ssh/private.py", selected)
    prompt = consultation_prompt(facts)
    assert "TEST_RUNNER_SOURCE" in prompt and "PRIVATE_SOURCE" not in prompt
    assert "HIDDEN_CREDENTIAL" not in prompt and "PRIVATE_INSTRUCTION" not in prompt and "PRIVATE_METADATA" not in prompt
    assert "[OCULTO]" in prompt
    assert str(project) not in prompt
    assert not any("private.py" in name or name.startswith(".env") or name == "alias.py" for name in seen)
    key = "core/executor/test_runner.py"
    assert facts["sources"][key]["sha256"] == hashlib.sha256((project / key).read_bytes()).hexdigest()
    result = consultation_report(json.dumps(report()), facts)
    assert result["operation_id"] == "158" and result["sources"][0]["path"] == key


def test_explicit_sources_fallback_semantics_and_file_limits(project):
    explicit = consultation_facts(project, "Analise core/executor/test_runner.py", None)
    assert list(explicit["sources"]) == ["core/executor/test_runner.py"]
    assert explicit["operation"] is None
    assert consultation_facts(project, "Explique TEST_RUNNER_SOURCE", None)["sources"]
    assert consultation_facts(project, "Explique a organização", None)["sources"]
    (project / "core/executor/test_runner.py").write_text("x" * 100001)
    assert consultation_facts(project, READ_ONLY, None)["sources"] == {}


@pytest.mark.parametrize("raw", [None, [], "x" * 16001, "[]", "{}", "not JSON",
    json.dumps(report(summary="")), json.dumps({**report(), "changes": []}),
    json.dumps(report(findings=[{}])), json.dumps(report(findings="bad")),
    json.dumps(report(findings=[{"text": "x", "evidence": ["missing.py"]}])),
    json.dumps(report(findings=[{"text": "x", "evidence": ["operation"]}])),
    json.dumps(report(hypotheses=[])), json.dumps(report(hypotheses=[None])),
    json.dumps(report(hypotheses=[{"cause": "x", "confidence": "comprovada", "evidence": ["request"]}])),
    json.dumps(report(next_steps=[])), json.dumps(report(missing_information=[{}])),
    json.dumps(report(correction_proposal={})),
])
def test_consultation_rejects_changes_and_unsupported_claim_references(raw):
    with pytest.raises((ValueError, TypeError)):
        consultation_report(raw, {"sources": {}, "operation": None})


def test_consultation_accepts_source_reference_and_reviewable_proposal(project):
    facts = consultation_facts(project, READ_ONLY, None)
    result = consultation_report(json.dumps(report(findings=[{"text": "A fonte define VALUE.",
        "evidence": ["core/executor/test_runner.py"]}], correction_proposal="Revisar o isolamento antes de propor alteração.")), facts)
    assert result["correction_proposal"]


@pytest.mark.parametrize("instruction", [None, "", " ", "x" * 12001])
def test_invalid_query_never_calls_ai(project, instruction):
    model = ai()
    with pytest.raises(ValueError, match="12000"):
        start_consultation(TaskInvestigations(), project, instruction, None, model, object())
    assert model.prompts == []


def test_consultation_is_in_memory_deduplicated_and_does_not_write_or_plan(project, monkeypatch):
    manager = TaskInvestigations()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    model = ai()
    gateway = object()
    service = APIService(SimpleNamespace(root=str(project), ai=model), gateway)
    def snapshot():
        return {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    before = snapshot()
    job = service.start_consultation(READ_ONLY)
    assert job["kind"] == "consultation" and "approval_id" not in job
    assert wait(manager, gateway, job["job_id"])["status"] == "completed"
    assert service.get_consultation(job["job_id"])["report"]["summary"] == report()["summary"]
    assert service.start_consultation(READ_ONLY)["job_id"] == job["job_id"]
    assert len(model.prompts) == 1 and snapshot() == before
    assert manager.get_consultation(job["job_id"], object()) is None
    assert service.get_consultation("missing") is None
    assert public_consultation(None) is None
    task_job = manager.start({"approval_id": "158"}, model, gateway)
    assert manager.get_consultation(task_job["job_id"], gateway) is None


def test_service_validates_context_identity_and_root(project, monkeypatch):
    manager = TaskInvestigations()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    class Gateway:
        selected = {"approval_id": "158", "status": "rolled_back"}
        def get_task(self, task_id):
            return self.selected
    gateway = Gateway()
    service = APIService(SimpleNamespace(root=str(project), ai=ai()), gateway)
    with pytest.raises(ValueError, match="inválido"):
        service.start_consultation(READ_ONLY, 158)
    with pytest.raises(ValueError, match="divergente"):
        service.start_consultation(READ_ONLY, "wrong")
    gateway.selected = None
    with pytest.raises(ValueError, match="indisponível"):
        service.start_consultation(READ_ONLY, "158")
    with pytest.raises(ValueError, match="Raiz"):
        APIService(object(), gateway).start_consultation(READ_ONLY)
    gateway.selected = {"approval_id": "158", "status": "rolled_back"}
    job = service.start_consultation(READ_ONLY, "158")
    assert wait(manager, gateway, job["job_id"])["status"] == "completed"


@pytest.fixture
def server(project, monkeypatch):
    manager = TaskInvestigations()
    gateway = object()
    model = ai()
    monkeypatch.setattr(service_module, "TASK_INVESTIGATIONS", manager)
    monkeypatch.setattr(api, "agent", SimpleNamespace(root=str(project), ai=model))
    monkeypatch.setattr(api, "gateway", gateway)
    http = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield http, manager, gateway, model
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def request(http, method, path, data=None):
    connection = HTTPConnection("127.0.0.1", http.server_port, timeout=3)
    try:
        connection.request(method, path, body=json.dumps(data) if data is not None else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("route", ["/consultations", "/plan"])
def test_read_only_http_request_returns_report_without_creating_or_approving_task(server, route):
    http, manager, gateway, model = server
    entered, release = Event(), Event()
    def generate(prompt):
        entered.set()
        assert release.wait(5)
        return json.dumps(report())
    model.generate = generate
    try:
        status, job = request(http, "POST", route, {"instruction": READ_ONLY})
        assert status == 202 and entered.wait(2) and job["kind"] == "consultation"
        assert "approval_id" not in job
        assert request(http, "GET", "/health")[0] == 200
        assert request(http, "GET", "/consultations/" + job["job_id"])[1]["status"] == "running"
    finally:
        release.set()
    wait(manager, gateway, job["job_id"])
    status, completed = request(http, "GET", "/consultations/" + job["job_id"] + "?source=studio")
    assert status == 200 and completed["report"]["missing_information"]
    assert request(http, "GET", "/consultations/missing")[0] == 404


def test_explicit_consultation_accepts_empty_or_malformed_instruction_errors(server):
    http, manager, gateway, model = server
    assert request(http, "POST", "/consultations", {"instruction": ""})[0] == 400
    assert request(http, "POST", "/consultations", {"instruction": "x" * 12001})[0] == 409
    assert model.prompts == [] and manager.jobs == {}


def test_explicit_consultation_requires_json_content_type(server):
    http, manager, gateway, model = server
    connection = HTTPConnection("127.0.0.1", http.server_port, timeout=3)
    try:
        connection.request("POST", "/consultations", body=json.dumps({"instruction": READ_ONLY}))
        response = connection.getresponse()
        assert response.status == 415
        response.read()
    finally:
        connection.close()
    assert model.prompts == [] and manager.jobs == {}
