"""Literal edits become full, reviewable plans before approval."""
import copy
import json

import pytest

from core.planner.ai_planner import AIPlanner
from core.planner.local_edits import content_hash, copy_sources, expand_local_edits


SOURCE = "# ação\r\nVALUE = 1\r\nTAIL = 'preservar'\r\n"


def document(item=None):
    return {"objective": "Atualizar valor", "changes": [item or change()], "tests": [], "risks": []}


def change(**overrides):
    return {"type": "modify", "path": "app.py", "base_sha256": content_hash(SOURCE),
            "edits": [{"old": "VALUE = 1", "new": "VALUE = 2"}], "reason": "Atualizar valor", **overrides}


class FixedAdapter:
    def __init__(self, data):
        self.data = data

    def generate(self, prompt):
        self.prompt = prompt
        return json.dumps(self.data, ensure_ascii=False)


def test_local_edits_preserve_unicode_line_endings_and_unedited_text():
    raw = document()
    before = copy.deepcopy(raw)
    sources = {"app.py": SOURCE}
    adapter = FixedAdapter(raw)
    plan = AIPlanner(adapter).create_plan("Modifique app.py", context=SOURCE, source_files=sources)
    assert plan.changes[0].content == SOURCE.replace("VALUE = 1", "VALUE = 2")
    assert "\r\n" in plan.changes[0].content
    assert plan.changes[0].reason == "Atualizar valor"
    assert raw == before
    assert sources == {"app.py": SOURCE}
    assert content_hash(SOURCE) in adapter.prompt
    assert "EDIÇÕES LOCALIZADAS DISPONÍVEIS" in adapter.prompt


def test_sequential_edits_can_insert_and_remove_text():
    raw = document(change(edits=[
        {"old": "VALUE = 1", "new": "VALUE = 2\r\nEXTRA = True"},
        {"old": "EXTRA = True", "new": ""},
    ]))
    result = expand_local_edits(raw, {"app.py": SOURCE})
    assert result["changes"][0]["content"] == SOURCE.replace("VALUE = 1", "VALUE = 2\r\n")
    assert "edits" not in result["changes"][0]
    assert "base_sha256" not in result["changes"][0]


def test_change_type_alias_is_supported_for_local_edits():
    item = change(change_type="modify", type="ignored")
    assert expand_local_edits(document(item), {"app.py": SOURCE})["changes"][0]["content"].endswith("'preservar'\r\n")


@pytest.mark.parametrize("data", [None, [], {"changes": {}}, {"objective": "old"}])
def test_invalid_legacy_structures_are_left_to_existing_validation(data):
    assert expand_local_edits(data, {}) is data


def test_legacy_changes_remain_supported_alongside_local_edits():
    raw = document()
    raw["changes"] += [{"type": "create", "path": "new.py", "content": "NEW = True\n"},
                       {"type": "delete", "path": "old.py"}]
    result = expand_local_edits(raw, {"app.py": SOURCE})
    assert result["changes"][1:] == raw["changes"][1:]
    assert expand_local_edits({"changes": ["invalid"]}, {})["changes"] == ["invalid"]


@pytest.mark.parametrize("overrides, message", [
    ({"type": "create"}, "MODIFY"), ({"type": "delete"}, "MODIFY"),
    ({"content": None}, "MODIFY"), ({"content": "ambiguous"}, "MODIFY"),
    ({"path": "missing.py"}, "presente no contexto"),
    ({"path": "../app.py"}, "presente no contexto"),
    ({"path": "/app.py"}, "presente no contexto"),
    ({"path": "secrets/private.py"}, "presente no contexto"),
    ({"path": []}, "presente no contexto"),
    ({"base_sha256": "0" * 64}, "Hash"), ({"base_sha256": None}, "Hash"),
    ({"edits": []}, "1 a 100"), ({"edits": {}}, "1 a 100"),
    ({"edits": [None]}, "old e new"),
    ({"edits": [{"old": "VALUE = 1"}]}, "old e new"),
    ({"edits": [{"old": "VALUE = 1", "new": "VALUE = 2", "line": 2}]}, "old e new"),
    ({"edits": [{"old": "", "new": "x"}]}, "inválida"),
    ({"edits": [{"old": None, "new": "x"}]}, "inválida"),
    ({"edits": [{"old": "VALUE = 1", "new": None}]}, "inválida"),
    ({"edits": [{"old": "VALUE = 1", "new": "VALUE = 1"}]}, "sem alteração"),
    ({"edits": [{"old": "missing anchor", "new": "x"}]}, "exatamente uma vez"),
    ({"edits": [{"old": "\r\n", "new": "\n"}]}, "exatamente uma vez"),
    ({"edits": [{"old": "VALUE = 1", "new": "é" * 100001}]}, "200000 bytes"),
    ({"edits": [{"old": "VALUE = 1", "new": "x"}] * 101}, "1 a 100"),
])
def test_invalid_edits_are_rejected_without_mutating_the_response(overrides, message):
    raw = document(change(**overrides))
    before = copy.deepcopy(raw)
    with pytest.raises(ValueError, match=message):
        expand_local_edits(raw, {"app.py": SOURCE})
    assert raw == before


def test_hash_is_required_and_overlapping_anchor_is_ambiguous():
    item = change()
    del item["base_sha256"]
    with pytest.raises(ValueError, match="Hash"):
        expand_local_edits(document(item), {"app.py": SOURCE})
    with pytest.raises(ValueError, match="exatamente uma vez"):
        expand_local_edits(document(change(base_sha256=content_hash("aaa"),
            edits=[{"old": "aa", "new": "b"}])), {"app.py": "aaa"})


@pytest.mark.parametrize("other", [change(), *[
    {"type": "modify", "path": path, "content": "x"}
    for path in ("app.py", "./app.py", "nested/../app.py", "double//../app.py")
]])
def test_file_cannot_be_repeated_in_a_plan_using_local_edits(other):
    raw = document()
    raw["changes"].append(other)
    with pytest.raises(ValueError, match="repetido"):
        expand_local_edits(raw, {"app.py": SOURCE})


def test_maximum_number_of_sequential_edits_is_accepted():
    edits = [{"old": f"VALUE = {number}", "new": f"VALUE = {number + 1}"} for number in range(1, 101)]
    item = change(edits=edits)
    assert "VALUE = 101" in expand_local_edits(document(item), {"app.py": SOURCE})["changes"][0]["content"]


@pytest.mark.parametrize("sources", [[], {1: "x"}, {"": "x"}, {".": "x"}, {"a\\b.py": "x"},
    {"/app.py": "x"}, {"../app.py": "x"}, {"./app.py": "x"},
    {"app.py": None}, {"app.py": "é" * 100001}])
def test_invalid_source_snapshots_are_rejected(sources):
    with pytest.raises(ValueError, match="fontes|Fontes"):
        copy_sources(sources)


def test_source_dictionary_is_copied_and_never_loaded_from_response():
    assert copy_sources(None) == {}
    original = {"app.py": SOURCE}
    copied = copy_sources(original)
    original.clear()
    assert copied == {"app.py": SOURCE}
    adapter = FixedAdapter(document())
    with pytest.raises(ValueError, match="presente no contexto"):
        AIPlanner(adapter).create_plan("Modifique app.py", context=SOURCE)
    assert "EDIÇÕES LOCALIZADAS DISPONÍVEIS" not in adapter.prompt


def test_copy_of_sources_is_not_affected_by_adapter_mutating_the_callers_dictionary():
    sources = {"app.py": SOURCE}

    class Adapter(FixedAdapter):
        def generate(self, prompt):
            sources.clear()
            return super().generate(prompt)

    plan = AIPlanner(Adapter(document())).create_plan("Modifique app.py", source_files=sources)
    assert "VALUE = 2" in plan.changes[0].content
