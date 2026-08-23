from core.parser.command_parser import CommandParser
from core.planner.planner import Planner
from core.schemas.models import ChangeType
from core.pipeline import DevAgentPipeline


def test_parser():
    command = CommandParser().parse(
        "Crie app.py sistema de clientes"
    )

    assert command.action == "create"
    assert command.target == "app.py"


def test_planner():
    command = CommandParser().parse(
        "Crie app.py sistema de clientes"
    )

    plan = Planner().create_plan(command)

    assert len(plan.changes) == 1
    assert plan.changes[0].change_type == ChangeType.CREATE


def test_pipeline():
    pipeline = DevAgentPipeline(".")
    plan = pipeline.process(
        "Crie teste.py arquivo de teste"
    )

    assert plan.objective != ""
    assert len(plan.changes) == 1
