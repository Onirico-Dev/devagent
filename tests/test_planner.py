import pytest

from core.parser.command_parser import Command
from core.planner.planner import Planner
from core.schemas.models import ChangeType


@pytest.fixture
def planner():
    return Planner()


def make_command(action, target="arquivo.py", instruction="conteudo", raw=None):
    return Command(
        action=action,
        target=target,
        instruction=instruction,
        raw=raw or f"{action} {target} {instruction}",
    )


def test_planner_create_returns_create_plan(planner):
    command = make_command(
        "create",
        target="novo.py",
        instruction="VALUE = 1\n",
        raw="criar novo.py",
    )

    plan = planner.create_plan(command)

    assert plan.objective == "criar novo.py"
    assert len(plan.changes) == 1

    change = plan.changes[0]
    assert change.change_type == ChangeType.CREATE
    assert change.path == "novo.py"
    assert change.content == "VALUE = 1\n"
    assert change.reason == "VALUE = 1\n"
    assert plan.tests == []
    assert plan.risks == []


def test_planner_create_rejects_non_string_content(planner):
    command = make_command("create")
    command.instruction = None

    with pytest.raises(ValueError, match="CREATE exige conteúdo textual"):
        planner.create_plan(command)


def test_planner_create_rejects_empty_content(planner):
    command = make_command("create", instruction="   ")

    with pytest.raises(ValueError, match="CREATE exige conteúdo textual"):
        planner.create_plan(command)


def test_planner_modify_returns_modify_plan(planner):
    command = make_command(
        "modify",
        target="arquivo.py",
        instruction="VALUE = 2\n",
        raw="modificar arquivo.py",
    )

    plan = planner.create_plan(command)

    assert plan.objective == "modificar arquivo.py"
    assert len(plan.changes) == 1

    change = plan.changes[0]
    assert change.change_type == ChangeType.MODIFY
    assert change.path == "arquivo.py"
    assert change.content == "VALUE = 2\n"
    assert change.reason == "VALUE = 2\n"
    assert plan.tests == []
    assert plan.risks == []


def test_planner_delete_returns_delete_plan(planner):
    command = make_command(
        "delete",
        target="arquivo.py",
        instruction="remover arquivo.py",
        raw="deletar arquivo.py",
    )

    plan = planner.create_plan(command)

    assert plan.objective == "deletar arquivo.py"
    assert len(plan.changes) == 1

    change = plan.changes[0]
    assert change.change_type == ChangeType.DELETE
    assert change.path == "arquivo.py"
    assert change.content is None
    assert change.reason == "remover arquivo.py"
    assert plan.tests == []
    assert plan.risks == ["Operação destrutiva"]


@pytest.mark.parametrize(
    "action",
    ["unknown", "", "invalid"],
)
def test_planner_unknown_action_returns_empty_plan(planner, action):
    command = make_command(
        action,
        target="arquivo.py",
        instruction="alguma coisa",
        raw=f"{action} arquivo.py",
    )

    plan = planner.create_plan(command)

    assert plan.objective == f"{action} arquivo.py"
    assert plan.changes == []
    assert plan.tests == []
    assert plan.risks == []


def test_planner_preserves_create_instruction_exactly(planner):
    instruction = 'print("Olá")\n\nVALUE = "teste"\n'
    command = make_command(
        "create",
        target="script.py",
        instruction=instruction,
    )

    plan = planner.create_plan(command)

    assert plan.changes[0].content == instruction
    assert plan.changes[0].reason == instruction


def test_planner_modify_allows_empty_instruction(planner):
    command = make_command(
        "modify",
        target="arquivo.py",
        instruction="",
    )

    plan = planner.create_plan(command)

    assert plan.changes[0].change_type == ChangeType.MODIFY
    assert plan.changes[0].content == ""
    assert plan.changes[0].reason == ""


def test_planner_delete_does_not_set_content(planner):
    command = make_command(
        "delete",
        target="arquivo.py",
        instruction="remover",
    )

    plan = planner.create_plan(command)

    assert plan.changes[0].content is None


def test_planner_returns_independent_plan_instances(planner):
    command = make_command(
        "create",
        target="arquivo.py",
        instruction="VALUE = 1",
    )

    first = planner.create_plan(command)
    second = planner.create_plan(command)

    assert first is not second
    assert first.changes is not second.changes
    assert first.changes[0] is not second.changes[0]
