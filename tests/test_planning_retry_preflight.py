"""Known fatal fields anywhere in the response must prevent regeneration."""
import copy
import json

import pytest

from core.planner.ai_planner import AIPlanner
from core.planner.local_edits import content_hash


SOURCE = "VALUE = 1\n"
SOURCES = {"app.py": SOURCE, "other.py": SOURCE}


def local(path="app.py", **overrides):
    return {"type": "modify", "path": path, "base_sha256": content_hash(SOURCE),
            "edits": [{"old": "VALUE = 1", "new": "VALUE = 2"}], **overrides}


def document(changes):
    return {"objective": "Atualizar valores", "changes": changes, "tests": [], "risks": []}


FATAL = [
    (local("other.py", base_sha256="0" * 64), "Hash"),
    (local("other.py", edits=[]), "1 a 100"),
    (local("other.py", edits=[{"old": "VALUE = 1", "new": "VALUE = 1"}]), "sem alteração"),
    (local("other.py", edits=[{"old": "", "new": "x"}]), "inválida"),
    (local("other.py", edits=[{"old": "VALUE = 1", "new": 1}]), "inválida"),
    (local("other.py", edits=[{"old": "VALUE = 1"}]), "old e new"),
    (local("other.py", edits=[{"old": "VALUE = 1", "new": "x", "extra": True}]), "old e new"),
    (local("other.py", edits=[{"old": "VALUE = 1", "new": "x"}] * 101), "1 a 100"),
    (local("other.py", type="create"), "MODIFY"),
    (local("other.py", content="x"), "MODIFY"),
    (local("missing.py"), "contexto"),
    (local("other.py", reason=123), "Motivo"),
    ({"type": "create", "path": "new.py", "content": None}, "conteúdo textual"),
    ({"type": "modify", "path": "legacy.py", "content": "x", "reason": []}, "Motivo"),
    (None, "Cada alteração"),
    (local("other.py", edits=[{"old": "VALUE = 1", "new": "é" * 100001}]), "200000 bytes"),
]


class Adapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0))


@pytest.mark.parametrize("invalid, message", FATAL)
@pytest.mark.parametrize("invalid_first", [False, True])
def test_fatal_validation_wins_over_anchor_regardless_of_file_order(invalid, message, invalid_first):
    missing = local(edits=[{"old": "ABSENT_PRIVATE", "new": "VALUE = 2"}])
    changes = [invalid, missing] if invalid_first else [missing, invalid]
    response = document(changes)
    before = copy.deepcopy(response)
    adapter = Adapter(response, document([local()]))
    with pytest.raises(ValueError, match=message):
        AIPlanner(adapter).create_plan("Modifique app.py", context=SOURCE, source_files=SOURCES)
    assert len(adapter.prompts) == 1
    assert response == before


def test_invalid_later_substitution_in_same_file_is_not_hidden_by_first_anchor():
    response = document([local(edits=[
        {"old": "ABSENT_PRIVATE", "new": "VALUE = 2"},
        {"old": "VALUE = 1", "new": "VALUE = 1"},
    ])])
    adapter = Adapter(response, document([local()]))
    with pytest.raises(ValueError, match="sem alteração"):
        AIPlanner(adapter).create_plan("Modifique app.py", source_files=SOURCES)
    assert len(adapter.prompts) == 1


def test_valid_later_substitution_can_still_target_text_created_by_earlier_edit():
    response = document([local(edits=[
        {"old": "VALUE = 1", "new": "VALUE = 2"},
        {"old": "VALUE = 2", "new": "VALUE = 3"},
    ])])
    adapter = Adapter(response)
    plan = AIPlanner(adapter).create_plan("Modifique app.py", source_files=SOURCES)
    assert plan.changes[0].content == "VALUE = 3\n"
    assert len(adapter.prompts) == 1


def test_small_replacement_cannot_grow_an_already_full_file_beyond_the_limit():
    from core.planner.local_edits import MAX_CONTENT_BYTES

    source = "#" + "x" * (MAX_CONTENT_BYTES - 1)
    response = document([local(base_sha256=content_hash(source),
                               edits=[{"old": "#", "new": "##"}])])
    adapter = Adapter(response, document([local()]))
    with pytest.raises(ValueError, match="200000 bytes"):
        AIPlanner(adapter).create_plan("Modifique app.py", context=source,
                                       source_files={"app.py": source})
    assert len(adapter.prompts) == 1
