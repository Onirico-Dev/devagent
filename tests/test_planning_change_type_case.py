"""Accept known action casing at the AI boundary, without widening the schema."""
import copy
import json

import pytest

from core.planner.ai_planner import AIPlanner
from core.planner.local_edits import content_hash
from core.schemas.models import ChangeType


class Adapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0))


def document(item):
    return {"objective": "Atualizar arquivo", "changes": [item], "tests": [], "risks": []}


@pytest.mark.parametrize("field", ["type", "change_type"])
@pytest.mark.parametrize("kind", ["create", "modify", "delete"])
@pytest.mark.parametrize("style", [str.upper, str.title, lambda s: s[0].upper() + s[1:-1] + s[-1].upper()])
def test_known_ai_action_variants_become_canonical(field, kind, style):
    item = {field: style(kind), "path": "CREATE_File.py", "reason": "CREATE literal"}
    if kind != "delete":
        item["content"] = 'TEXT = "CREATE MODIFY DELETE"\n'
    adapter = Adapter(document(item))
    plan = AIPlanner(adapter).create_plan("Crie ou modifique CREATE_File.py")
    assert plan.changes[0].change_type.value == kind
    assert plan.changes[0].path == "CREATE_File.py"
    assert plan.changes[0].reason == "CREATE literal"
    assert plan.changes[0].content == item.get("content")
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("field", ["type", "change_type"])
@pytest.mark.parametrize("kind", ["MODIFY", "Modify", "mOdIfY"])
def test_local_edit_action_is_normalized_before_static_and_anchor_checks(field, kind):
    source = "# CREATE literal\r\nVALUE = 'CREATE'\r\n"
    item = {field: kind, "path": "App.py", "base_sha256": content_hash(source),
            "edits": [{"old": "'CREATE'", "new": "'MODIFY'"}], "reason": "DELETE literal"}
    before = copy.deepcopy(item)
    adapter = Adapter(document(item))
    plan = AIPlanner(adapter).create_plan("Modifique App.py", context=source,
                                        source_files={"App.py": source})
    assert plan.changes[0].change_type.value == "modify"
    assert plan.changes[0].content == source.replace("'CREATE'", "'MODIFY'")
    assert plan.changes[0].path == "App.py"
    assert item == before
    assert len(adapter.prompts) == 1


@pytest.mark.parametrize("value", ["EXEC", "REMOVE", "UPDATE", "CREATE_FILE", " CREATE", "CREATE ", "", None, 1, False, [], {}])
def test_unknown_or_nontext_actions_remain_final_errors(value):
    adapter = Adapter(document({"type": value, "path": "a.py", "content": "x = 1\n"}))
    with pytest.raises(ValueError, match="Tipo de alteração inválido"):
        AIPlanner(adapter).create_plan("Crie a.py")
    assert len(adapter.prompts) == 1


def test_change_type_alias_priority_is_preserved():
    adapter = Adapter(document({"change_type": "DELETE", "type": "CREATE", "path": "a.py"}))
    plan = AIPlanner(adapter).create_plan("Remova a.py")
    assert plan.changes[0].change_type.value == "delete"
    assert len(adapter.prompts) == 1


def test_null_change_type_still_falls_back_to_type():
    adapter = Adapter(document({"change_type": None, "type": "CREATE", "path": "a.py", "content": "x = 1\n"}))
    assert AIPlanner(adapter).create_plan("Crie a.py").changes[0].change_type.value == "create"


def test_invalid_alias_is_not_overridden_by_valid_type():
    adapter = Adapter(document({"change_type": "UNKNOWN", "type": "CREATE", "path": "a.py", "content": "x = 1\n"}))
    with pytest.raises(ValueError, match="Tipo de alteração inválido"):
        AIPlanner(adapter).create_plan("Crie a.py")
    assert len(adapter.prompts) == 1


def test_type_normalization_does_not_normalize_a_source_hash():
    source = "VALUE = 1\n"
    adapter = Adapter(document({"type": "MODIFY", "path": "a.py",
                                "base_sha256": content_hash(source).upper(),
                                "edits": [{"old": "VALUE = 1", "new": "VALUE = 2"}]}))
    with pytest.raises(ValueError, match="Hash"):
        AIPlanner(adapter).create_plan("Modifique a.py", source_files={"a.py": source})
    assert len(adapter.prompts) == 1


def test_case_normalization_does_not_consume_an_extra_retry():
    adapter = Adapter({"objective": "Criar", "changes": [], "tests": [], "risks": []},
                      document({"type": "CREATE", "path": "a.py", "content": "x = 1\n"}))
    assert AIPlanner(adapter).create_plan("Crie a.py").changes[0].change_type.value == "create"
    assert len(adapter.prompts) == 2


def test_normalization_does_not_mutate_the_provider_document():
    raw = document({"type": "CREATE", "path": "CREATE.py", "content": 'VALUE = "DELETE"\n'})
    before = copy.deepcopy(raw)
    result = AIPlanner._normalize_change_types(raw)
    assert raw == before
    assert result["changes"][0]["type"] == "create"
    assert result["changes"][0]["path"] == raw["changes"][0]["path"]
    assert result["changes"][0]["content"] == raw["changes"][0]["content"]


def test_internal_enum_still_rejects_noncanonical_values():
    with pytest.raises(ValueError):
        ChangeType("CREATE")


def test_uppercase_ai_creates_are_reviewed_tested_and_committed_canonically(isolated_project):
    from agent import DevAgent
    from core.gateway import DevAgentGateway

    module = 'def status():\n    return "DEVAGENT_OK"\n'
    test = ('from case_probe import status\n\n'
            'def test_status():\n    assert status() == "DEVAGENT_OK"\n')
    adapter = Adapter({"objective": "Validar execução", "changes": [
        {"type": "CREATE", "path": "case_probe.py", "content": module},
        {"type": "CREATE", "path": "tests/test_case_probe.py", "content": test},
    ], "tests": ["tests/test_case_probe.py"], "risks": []})
    gateway = DevAgentGateway(DevAgent(isolated_project, ai_adapter=adapter), isolated_project)
    task = gateway.create_task("Crie case_probe.py e tests/test_case_probe.py")
    assert task["status"] == "pending"
    assert not (isolated_project / "case_probe.py").exists()
    assert all(item["change_type"] == "create" for item in task["plan"]["changes"])
    result = gateway.approve(task["approval_id"])
    assert result["status"] == "committed"
    assert result["tests"]["success"] and result["tests"]["returncode"] == 0
    assert result["repair_attempts"] == 0
    assert (isolated_project / "case_probe.py").read_text() == module
    assert (isolated_project / "tests/test_case_probe.py").read_text() == test
    assert len(adapter.prompts) == 1
