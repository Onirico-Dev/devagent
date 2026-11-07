"""Retry only validated missing/empty changes, before human approval."""
import json

import pytest

from agent import DevAgent
from core.gateway import DevAgentGateway
from core.planner.ai_planner import AIPlanner


INSTRUCTION = "Crie o arquivo novo.py"
VALID = {
    "objective": "Criar novo.py",
    "changes": [{"type": "create", "path": "novo.py", "content": "value = 1\n"}],
    "tests": [],
    "risks": [],
}


def without_changes(missing=False, **overrides):
    data = {**VALID, "changes": [], **overrides}
    if missing:
        del data["changes"]
    return data


class SequenceAdapter:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return json.dumps(response) if not isinstance(response, str) else response


@pytest.mark.parametrize("missing", [False, True])
def test_missing_and_empty_changes_regenerate_with_distinct_diagnostics(missing):
    adapter = SequenceAdapter(without_changes(missing), VALID)
    plan = AIPlanner(adapter).create_plan(
        INSTRUCTION, context="fontes originais", feedback_context={"attempt": 5},
    )
    assert plan.changes[0].path == "novo.py"
    assert len(adapter.prompts) == 2
    assert adapter.prompts[1].startswith(adapter.prompts[0])
    reason = "missing" if missing else "empty"
    assert f'"reason": "{reason}"' in adapter.prompts[1]
    assert "fontes originais" in adapter.prompts[1]
    assert '"attempt": 5' in adapter.prompts[1]


@pytest.mark.parametrize("first_missing", [False, True])
@pytest.mark.parametrize("second_missing", [False, True])
def test_retry_budget_is_global_for_missing_and_empty(first_missing, second_missing):
    from core.planner.ai_planner import MissingChangesError

    adapter = SequenceAdapter(
        without_changes(first_missing), without_changes(second_missing), VALID,
    )
    with pytest.raises(MissingChangesError) as caught:
        AIPlanner(adapter).create_plan(INSTRUCTION)
    assert caught.value.reason == ("missing" if second_missing else "empty")
    assert len(adapter.prompts) == 2


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("overrides", [
    {"objective": ""}, {"objective": 1},
    {"tests": "pytest"}, {"tests": ["../test_escape.py"]},
    {"tests": ["/tmp/test_escape.py"]}, {"tests": ["pytest -q"]},
    {"risks": "invalid"}, {"risks": [1]},
])
def test_other_invalid_fields_prevent_retry_even_with_no_changes(missing, overrides):
    adapter = SequenceAdapter(without_changes(missing, **overrides), VALID)
    with pytest.raises(ValueError):
        AIPlanner(adapter).create_plan(INSTRUCTION)
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("response", [
    "not JSON", [],
    {**VALID, "changes": None}, {**VALID, "changes": {}},
    {**VALID, "changes": ["invalid"]},
    {**VALID, "changes": [{"type": "modify", "path": "novo.py"}]},
    {**VALID, "changes": [{"type": "delete", "path": "novo.py", "content": "x"}]},
])
def test_noneligible_responses_do_not_regenerate(response):
    adapter = SequenceAdapter(response, VALID)
    with pytest.raises(ValueError):
        AIPlanner(adapter).create_plan(INSTRUCTION)
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("failure", [TimeoutError("timeout"), RuntimeError("transport")])
@pytest.mark.parametrize("on_retry", [False, True])
def test_provider_failure_propagates_without_extra_calls(failure, on_retry):
    responses = [without_changes()] if on_retry else []
    adapter = SequenceAdapter(*responses, failure, VALID)
    with pytest.raises(type(failure)) as caught:
        AIPlanner(adapter).create_plan(INSTRUCTION)
    assert caught.value is failure
    assert len(adapter.prompts) == (2 if on_retry else 1)


def test_valid_plan_needs_one_call():
    adapter = SequenceAdapter(VALID)
    assert AIPlanner(adapter).create_plan(INSTRUCTION).changes
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_read_only_request_does_not_regenerate(missing):
    adapter = SequenceAdapter(without_changes(missing))
    if missing:
        with pytest.raises(ValueError, match="Campo obrigatório 'changes' ausente"):
            AIPlanner(adapter).create_plan("Analise o projeto")
    else:
        assert AIPlanner(adapter).create_plan("Analise o projeto").changes == []
    assert len(adapter.prompts) == 1


def gateway_with_adapter(root, adapter):
    agent = DevAgent(root, ai_adapter=adapter)
    return DevAgentGateway(agent, root)


def test_regenerated_plan_remains_pending_without_execution(isolated_project):
    adapter = SequenceAdapter(without_changes(True), VALID)
    gateway = gateway_with_adapter(isolated_project, adapter)
    result = gateway.create_task(INSTRUCTION)
    assert result["approval_id"]
    assert gateway.list_pending()
    assert not (isolated_project / "novo.py").exists()
    assert gateway.transactions.list_terminal_transactions() == []
    assert len(adapter.prompts) == 2


@pytest.mark.parametrize("path", ["../escape.py", "/tmp/escape.py", ".git/config.py"])
def test_regeneration_does_not_bypass_path_protections(isolated_project, path):
    unsafe = {**VALID, "changes": [{**VALID["changes"][0], "path": path}]}
    adapter = SequenceAdapter(without_changes(), unsafe, VALID)
    gateway = gateway_with_adapter(isolated_project, adapter)
    with pytest.raises((ValueError, PermissionError)):
        gateway.create_task(INSTRUCTION)
    assert not gateway.list_pending()
    assert len(adapter.prompts) == 2


def test_retry_diagnostic_does_not_echo_rejected_response():
    rejected = without_changes()
    rejected["objective"] = "SECRET-RESPONSE-CONTENT"
    adapter = SequenceAdapter(rejected, VALID)
    AIPlanner(adapter).create_plan(INSTRUCTION)
    assert "SECRET-RESPONSE-CONTENT" not in adapter.prompts[1]


SOURCE = "# ação\r\nVALUE = 1\r\nTAIL = True\r\n"


def local_document(old="VALUE = 1", new="VALUE = 2"):
    from core.planner.local_edits import content_hash
    return {**VALID, "changes": [{
        "type": "modify", "path": "app.py", "base_sha256": content_hash(SOURCE),
        "edits": [{"old": old, "new": new}],
    }]}


FAILURES = {
    "missing": without_changes(True),
    "empty": without_changes(),
    "anchor_missing": local_document("ABSENT"),
    "anchor_ambiguous": local_document("\r\n"),
}


@pytest.mark.parametrize("first", FAILURES)
@pytest.mark.parametrize("second", FAILURES)
def test_single_global_retry_budget_including_anchors(first, second):
    adapter = SequenceAdapter(FAILURES[first], FAILURES[second], local_document())
    with pytest.raises(ValueError):
        AIPlanner(adapter).create_plan(
            "Modifique app.py", context=SOURCE, source_files={"app.py": SOURCE},
        )
    assert len(adapter.prompts) == 2


@pytest.mark.parametrize("first", FAILURES)
def test_each_eligible_cause_can_recover_with_same_original_sources(first):
    from core.planner.local_edits import content_hash
    adapter = SequenceAdapter(FAILURES[first], local_document())
    result = AIPlanner(adapter).create_plan(
        "Modifique app.py", context=SOURCE, source_files={"app.py": SOURCE},
    )
    assert result.changes[0].content == SOURCE.replace("VALUE = 1", "VALUE = 2")
    assert adapter.prompts[1].startswith(adapter.prompts[0])
    assert content_hash(SOURCE) in adapter.prompts[1]
    assert len(adapter.prompts) == 2


@pytest.mark.parametrize("field, value", [
    ("objective", ""), ("tests", ["../test_escape.py"]),
    ("tests", ["pytest -q"]), ("risks", [1]),
])
def test_invalid_envelope_prevents_anchor_retry(field, value):
    data = {**local_document("ABSENT"), field: value}
    adapter = SequenceAdapter(data, local_document())
    with pytest.raises(ValueError):
        AIPlanner(adapter).create_plan("Modifique app.py", source_files={"app.py": SOURCE})
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("first", FAILURES)
def test_invalid_replacement_after_eligible_error_does_not_get_another_call(first):
    adapter = SequenceAdapter(FAILURES[first], local_document("VALUE = 1", "VALUE = 1"), local_document())
    with pytest.raises(ValueError, match="Substituição local inválida"):
        AIPlanner(adapter).create_plan("Modifique app.py", source_files={"app.py": SOURCE})
    assert len(adapter.prompts) == 2


@pytest.mark.parametrize("reason", ["invalid_replacement", "unknown"])
def test_unknown_anchor_reason_does_not_regenerate(monkeypatch, reason):
    from core.planner.local_edits import LocalEditAnchorError
    import core.planner.ai_planner as module

    def refuse(*args):
        raise LocalEditAnchorError("app.py", 1, reason)

    monkeypatch.setattr(module, "expand_local_edits", refuse)
    adapter = SequenceAdapter(local_document(), local_document())
    with pytest.raises(LocalEditAnchorError):
        AIPlanner(adapter).create_plan("Modifique app.py", source_files={"app.py": SOURCE})
    assert len(adapter.prompts) == 1


def test_original_source_mapping_is_copied_before_generation():
    sources = {"app.py": SOURCE}

    class MutatingAdapter(SequenceAdapter):
        def generate(self, prompt):
            sources["app.py"] = "MODIFIED EXTERNALLY"
            return super().generate(prompt)

    adapter = MutatingAdapter(local_document("ABSENT"), local_document())
    result = AIPlanner(adapter).create_plan("Modifique app.py", context=SOURCE, source_files=sources)
    assert result.changes[0].content == SOURCE.replace("VALUE = 1", "VALUE = 2")


def test_explicit_read_only_request_does_not_call_provider():
    adapter = SequenceAdapter(VALID)
    with pytest.raises(ValueError, match="Consultar sem alterar"):
        AIPlanner(adapter).create_plan("Examine app.py. Consulta somente de leitura, sem alterações.")
    assert adapter.prompts == []
