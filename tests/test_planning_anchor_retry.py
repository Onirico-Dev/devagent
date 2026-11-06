"""One bounded regeneration for literal anchors; all other refusals remain final."""
import copy
import json

import pytest

from agent import DevAgent
from core.gateway import DevAgentGateway
from core.planner.ai_planner import AIPlanner
from core.planner.local_edits import LocalEditAnchorError, content_hash, expand_local_edits


SOURCE = "# ação\r\nVALUE = 1\r\nTAIL = True\r\n"


def document(old="VALUE = 1", new="VALUE = 2", **overrides):
    return {"objective": "Atualizar valor", "changes": [{
        "type": "modify", "path": "app.py", "base_sha256": content_hash(SOURCE),
        "edits": [{"old": old, "new": new}], **overrides,
    }], "tests": [], "risks": []}


class Adapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)


def plan(adapter):
    return AIPlanner(adapter).create_plan("Modifique app.py", context=SOURCE,
                                        source_files={"app.py": SOURCE})


@pytest.mark.parametrize("old, reason, detail", [
    ("ABSENT_PRIVATE_TEXT", "missing", "não encontrado"),
    ("\r\n", "ambiguous", "ambíguo"),
])
def test_anchor_diagnostic_identifies_file_edit_and_reason_without_source(old, reason, detail):
    raw = document(old, "REPLACEMENT_PRIVATE_TEXT")
    raw["changes"][0]["edits"].insert(0, {"old": "VALUE = 1", "new": "VALUE = 3"})
    before = copy.deepcopy(raw)
    with pytest.raises(LocalEditAnchorError) as caught:
        expand_local_edits(raw, {"app.py": SOURCE})
    error = caught.value
    assert (error.path, error.edit_number, error.reason) == ("app.py", 2, reason)
    assert "app.py, edição 2" in str(error) and detail in str(error)
    assert "PRIVATE_TEXT" not in str(error)
    assert raw == before


def test_overlapping_occurrences_remain_ambiguous():
    with pytest.raises(LocalEditAnchorError) as caught:
        expand_local_edits(document("aa", "b", base_sha256=content_hash("aaa")), {"app.py": "aaa"})
    assert caught.value.reason == "ambiguous"


@pytest.mark.parametrize("old", ["ABSENT_PRIVATE_TEXT", "\r\n"])
def test_one_regeneration_reuses_original_context_and_returns_full_content(old):
    first = document(old, "FAILED_RESPONSE_PRIVATE_TEXT")
    before = copy.deepcopy(first)
    adapter = Adapter(first, document())
    result = plan(adapter)
    assert result.changes[0].content == SOURCE.replace("VALUE = 1", "VALUE = 2")
    assert len(adapter.prompts) == 2
    assert adapter.prompts[1].startswith(adapter.prompts[0])
    assert SOURCE in adapter.prompts[1] and content_hash(SOURCE) in adapter.prompts[1]
    assert '"edit_number": 1' in adapter.prompts[1]
    assert '"path": "app.py"' in adapter.prompts[1]
    assert "PRIVATE_TEXT" not in adapter.prompts[1]
    assert first == before


def test_regeneration_starts_from_original_after_partial_in_memory_expansion():
    first = document("VALUE = 1", "VALUE = 3")
    first["changes"][0]["edits"].append({"old": "ABSENT", "new": "x"})
    adapter = Adapter(first, document())
    assert plan(adapter).changes[0].content == SOURCE.replace("VALUE = 1", "VALUE = 2")
    assert '"edit_number": 2' in adapter.prompts[1]


def test_second_bad_anchor_refuses_without_third_call():
    adapter = Adapter(document("ABSENT"), document("\r\n"), document())
    with pytest.raises(LocalEditAnchorError) as caught:
        plan(adapter)
    assert caught.value.reason == "ambiguous"
    assert len(adapter.prompts) == 2 and len(adapter.responses) == 1


@pytest.mark.parametrize("response, message", [
    ("invalid JSON", "JSON válido"),
    (document(base_sha256="0" * 64), "Hash"),
    (document(path="../app.py"), "presente no contexto"),
    (document(content="x"), "MODIFY"),
    (document(new="é" * 100001), "200000 bytes"),
    ({"objective": "Atualizar", "changes": [], "tests": [], "risks": []}, "sem alterações"),
])
@pytest.mark.parametrize("after_anchor", [False, True])
def test_other_validation_errors_are_not_retried(response, message, after_anchor):
    adapter = Adapter(*([document("ABSENT")] if after_anchor else []), response, document())
    with pytest.raises(ValueError, match=message):
        plan(adapter)
    assert len(adapter.prompts) == (2 if after_anchor else 1)
    assert len(adapter.responses) == 1


def test_provider_failure_during_regeneration_propagates():
    adapter = Adapter(document("ABSENT"), RuntimeError("provider unavailable"), document())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        plan(adapter)
    assert len(adapter.prompts) == 2


def test_read_only_request_never_starts_generation_or_retry():
    adapter = Adapter(document())
    with pytest.raises(ValueError, match="Consultar sem alterar"):
        AIPlanner(adapter).create_plan("Examine app.py. Consulta somente de leitura, sem alterações.")
    assert adapter.prompts == []


@pytest.mark.parametrize("legacy", [False, True])
def test_valid_first_response_uses_one_call(legacy):
    data = document()
    if legacy:
        data["changes"][0] = {"type": "modify", "path": "app.py", "content": "VALUE = 2\n"}
    adapter = Adapter(data)
    assert "VALUE = 2" in plan(adapter).changes[0].content
    assert len(adapter.prompts) == 1


def test_legacy_create_delete_keep_one_call():
    adapter = Adapter({"objective": "Substituir arquivo", "changes": [
        {"type": "create", "path": "new.py", "content": "VALUE = 2\n"},
        {"type": "delete", "path": "old.py"},
    ], "tests": [], "risks": []})
    assert len(plan(adapter).changes) == 2
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("drift", [False, True])
def test_gateway_registers_only_valid_plan_and_still_refuses_drift(tmp_path, drift):
    source = tmp_path / "app.py"
    source.write_bytes(SOURCE.encode("utf-8"))

    class ChangingAdapter(Adapter):
        def generate(self, prompt):
            response = super().generate(prompt)
            if drift and len(self.prompts) == 2:
                source.write_text("VALUE = 3\n")
            return response

    adapter = ChangingAdapter(document("ABSENT"), document())
    gateway = DevAgentGateway(DevAgent(tmp_path, ai_adapter=adapter), tmp_path)
    if drift:
        with pytest.raises(ValueError, match="mudou durante o planejamento"):
            gateway.create_task("Modifique app.py")
        assert gateway.list_tasks() == []
        assert source.read_text() == "VALUE = 3\n"
    else:
        task = gateway.create_task("Modifique app.py")
        assert task["status"] == "pending"
        assert len(gateway.list_tasks()) == 1
        assert source.read_bytes() == SOURCE.encode("utf-8")
    assert len(adapter.prompts) == 2


def test_second_failure_registers_no_task_and_preserves_files(tmp_path):
    source = tmp_path / "app.py"
    source.write_bytes(SOURCE.encode("utf-8"))
    adapter = Adapter(document("ABSENT"), document("\r\n"), document())
    gateway = DevAgentGateway(DevAgent(tmp_path, ai_adapter=adapter), tmp_path)
    with pytest.raises(LocalEditAnchorError):
        gateway.create_task("Modifique app.py")
    assert gateway.list_tasks() == []
    assert source.read_bytes() == SOURCE.encode("utf-8")
    assert len(adapter.prompts) == 2
