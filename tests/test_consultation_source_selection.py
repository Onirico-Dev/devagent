"""Source selection is local evidence, separate from the AI's conclusions."""
import copy
import hashlib
import json
from pathlib import Path
from threading import Event

import pytest

from core.api.project_consultation import consultation_facts, consultation_prompt, consultation_report, start_consultation
from core.api.task_investigation import TaskInvestigations
from core.adapters.codex_adapter import CodexAdapter
from core.context.project_context import ProjectContext


def write(root, name, text="VALUE = 1\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def response(**extra):
    return json.dumps({"summary": "Consulta limitada às fontes enviadas.", "findings": [],
        "hypotheses": [{"cause": "Faltam evidências históricas.", "confidence": "baixa", "evidence": ["request"]}],
        "next_steps": ["Revise as fontes omitidas."], "missing_information": [],
        "correction_proposal": None, **extra})


def records(facts):
    return {r["path"]: (r["reason"], r["origin"]) for r in facts["source_selection"]["records"]}


def test_explicit_sources_have_exact_hashes_and_locally_reported_missing_files(tmp_path):
    path = write(tmp_path, "src/app.py", "VALUE = 1\r\n")
    facts = consultation_facts(tmp_path, "Examine src/app.py e tests/missing.py", None)
    assert set(facts["sources"]) == {"src/app.py"}
    assert facts["sources"]["src/app.py"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert records(facts) == {"src/app.py": ("included", "explicit"), "tests/missing.py": ("not_found", "explicit")}
    assert facts["source_selection"]["version"] == 1
    assert facts["source_selection"]["truncated"] is False
    assert str(tmp_path) not in json.dumps(facts)


def test_size_budget_binary_and_extension_are_distinct_omission_causes(tmp_path):
    write(tmp_path, "first.txt", "a" * 60000)
    write(tmp_path, "second.txt", "b" * 60000)
    write(tmp_path, "large.txt", "c" * 100001)
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe")
    facts = consultation_facts(tmp_path, "Examine first.txt second.txt large.txt binary.py image.png", None)
    assert records(facts) == {
        "first.txt": ("included", "explicit"), "second.txt": ("context_budget", "explicit"),
        "large.txt": ("file_size", "explicit"), "binary.py": ("binary", "explicit"),
        "image.png": ("extension", "explicit"),
    }
    assert set(facts["sources"]) == {"first.txt"}


def test_explicit_source_limit_preserves_order_and_reports_remaining_candidates(tmp_path):
    names = [f"source_{i}.py" for i in range(18)]
    for name in names:
        write(tmp_path, name)
    facts = consultation_facts(tmp_path, "Examine " + " ".join(names), None)
    assert list(facts["sources"]) == names[:16]
    assert all(records(facts)[name] == ("file_limit", "explicit") for name in names[16:])


def test_concept_and_relevance_sources_are_not_reported_as_explicit_requests(tmp_path):
    write(tmp_path, "core/supervisor.py")
    concept = consultation_facts(tmp_path, "Examine a supervisão", None)
    assert records(concept)["core/supervisor.py"] == ("included", "concept")
    assert records(concept)["core/gateway.py"] == ("not_found", "concept")
    write(tmp_path, "unique.py", "def unique_marker():\n    return 1\n")
    relevant = consultation_facts(tmp_path, "Explique unique_marker", None)
    assert records(relevant)["unique.py"] == ("included", "relevance")


def test_semantic_source_limit_is_reported_without_changing_selected_order(tmp_path):
    names = [f"a{i:02}.py" for i in range(18)]
    for name in names:
        write(tmp_path, name, "def shared_marker():\n    return 1\n")
    facts = consultation_facts(tmp_path, "Explique shared_marker", None)
    assert list(facts["sources"]) == names[:16]
    assert records(facts)[names[-1]] == ("file_limit", "relevance")


@pytest.mark.parametrize("name", ["secrets/hidden.py", "backups/hidden.py", ".ssh/hidden.py", ".env", ".env.production"])
def test_protected_requests_are_generic_without_existence_probes(tmp_path, monkeypatch, name):
    write(tmp_path, "app.py")
    original_stat = Path.stat
    original_resolve = Path.resolve
    def guarded_stat(path, *args, **kwargs):
        assert name not in str(path), "Protected path was probed"
        return original_stat(path, *args, **kwargs)
    def guarded_resolve(path, *args, **kwargs):
        assert name not in str(path), "Protected path was resolved"
        return original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", guarded_stat)
    monkeypatch.setattr(Path, "resolve", guarded_resolve)
    facts = consultation_facts(tmp_path, "Examine app.py " + name, None)
    assert records(facts)["[caminho bloqueado]"] == ("protected", "explicit")
    assert name not in json.dumps(facts["source_selection"])
    assert list(facts["sources"]) == ["app.py"]


def test_symlinks_and_outside_paths_do_not_expose_targets(tmp_path):
    private = write(tmp_path, "secrets/hidden.py", "PRIVATE_SENTINEL")
    public = write(tmp_path, "app.py")
    (tmp_path / "alias.py").symlink_to(private)
    (tmp_path / "public_alias.py").symlink_to(public)
    facts = consultation_facts(tmp_path, "Examine app.py alias.py public_alias.py ../outside.py /tmp/outside.py", None)
    assert list(facts["sources"]) == ["app.py"]
    manifest = json.dumps(facts["source_selection"])
    assert "PRIVATE_SENTINEL" not in manifest and "hidden.py" not in manifest
    assert "alias.py" not in manifest and "outside.py" not in manifest


def test_inaccessible_candidate_has_static_reason_without_exception_message(tmp_path, monkeypatch):
    context = ProjectContext(tmp_path)
    original = Path.resolve
    def fail(path, *args, **kwargs):
        if path.name == "blocked.py":
            raise PermissionError("PRIVATE_EXCEPTION")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", fail)
    assert context.source_omission("blocked.py") == "unavailable"


def test_manifest_is_bounded_and_does_not_change_sources_when_abbreviated(tmp_path):
    write(tmp_path, "app.py")
    names = [f"missing_{i}.py" for i in range(100)]
    facts = consultation_facts(tmp_path, "Examine app.py " + " ".join(names), None)
    selection = facts["source_selection"]
    assert len(selection["records"]) == 48 and selection["truncated"] is True
    assert list(facts["sources"]) == ["app.py"]
    assert len(json.dumps(selection, ensure_ascii=False).encode()) <= 16000


def test_record_limits_cover_long_unicode_paths_and_aggregate_bytes():
    diagnostic = {"records": [], "truncated": False}
    ProjectContext.record_source_selection(diagnostic, "x" * 241, "not_found")
    assert diagnostic == {"records": [], "truncated": True}
    for i in range(48):
        ProjectContext.record_source_selection(diagnostic, "字" * 225 + str(i) + ".py", "not_found")
    assert len(diagnostic["records"]) < 48
    assert len(json.dumps(diagnostic["records"], ensure_ascii=False).encode()) <= 12000
    assert diagnostic["truncated"] is True


def test_collector_diagnostic_is_optional_reused_by_caller_and_not_shared(tmp_path):
    write(tmp_path, "app.py")
    context = ProjectContext(tmp_path)
    diagnostic = {"PRIVATE_STALE": True}
    snapshots = {}
    plain = context.build(["app.py"])
    assert context.build(["app.py"], diagnostics=diagnostic, snapshots=snapshots) == plain
    original = copy.deepcopy(diagnostic)
    context.build(["missing.py"], diagnostics=diagnostic)
    assert diagnostic != original and "PRIVATE_STALE" not in diagnostic
    assert original == {"records": [{"path": "app.py", "reason": "included"}], "truncated": False}
    facts = consultation_facts(tmp_path, "Examine app.py missing.py", None)
    before = copy.deepcopy(facts)
    consultation_facts(tmp_path, "Examine app.py another.py", None)
    assert facts == before


@pytest.mark.parametrize("name,reason", [(".env", "protected"), ("../outside.py", "protected"),
    ("alias.py", "protected"), ("missing.py", "not_found"), ("file.png", "extension")])
def test_build_reports_omitted_requested_paths_while_preserving_text_contract(tmp_path, name, reason):
    write(tmp_path, "app.py")
    (tmp_path / "alias.py").symlink_to(tmp_path / "app.py")
    context = ProjectContext(tmp_path)
    diagnostic = {}
    text = context.build([name], diagnostics=diagnostic)
    assert isinstance(text, str) and "=== ARQUIVO: app.py ===" in text
    assert any(record["reason"] == reason for record in diagnostic["records"])


def test_prompt_excludes_manifest_and_ai_cannot_supply_or_replace_it(tmp_path):
    write(tmp_path, "app.py")
    facts = consultation_facts(tmp_path, "Examine app.py missing.py", None)
    before = copy.deepcopy(facts)
    prompt = consultation_prompt(facts)
    assert "source_selection" not in prompt and "not_found" not in prompt
    result = consultation_report(response(), facts)
    assert result["source_selection"] == facts["source_selection"]
    assert facts == before
    with pytest.raises(ValueError):
        consultation_report(response(source_selection={"records": []}), facts)
    legacy = {"sources": {}, "operation": None}
    assert "source_selection" not in consultation_report(response(), legacy)


def test_completed_job_contains_local_manifest_without_writes_or_extra_ai_calls(tmp_path):
    write(tmp_path, "app.py")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    model = object.__new__(CodexAdapter)
    prompts = []
    def generate(prompt):
        prompts.append(prompt)
        return response()
    model.generate = generate
    owner = object()
    manager = TaskInvestigations()
    job = start_consultation(manager, tmp_path, "Examine app.py missing.py", None, model, owner)
    for _ in range(200):
        result = manager.get_consultation(job["job_id"], owner)
        if result["status"] != "running":
            break
        Event().wait(0.005)
    assert result["status"] == "completed"
    assert result["report"]["source_selection"]["records"][-1]["reason"] == "not_found"
    assert len(prompts) == 1 and "source_selection" not in prompts[0]
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
