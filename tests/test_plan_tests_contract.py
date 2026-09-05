import json

import pytest

from core.planner.ai_planner import AIPlanner
from core.planner.plan_validator import PlanValidator
from core.schemas.models import Plan


class FixedAdapter:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        return self.response


def make_plan(tests):
    return Plan(
        objective="teste",
        changes=[],
        tests=tests,
        risks=[],
    )


def test_plan_validator_accepts_relative_pytest_file(tmp_path):
    validator = PlanValidator(tmp_path)

    plan = make_plan(["tests/test_version.py"])

    assert validator.validate(plan) is True


@pytest.mark.parametrize(
    "test_path",
    [
        "python -m pytest",
        "pytest -q",
        "assert version.version() == '0.2'",
        "test_version.txt",
        "tests/version.py",
    ],
)
def test_plan_validator_rejects_non_pytest_test_reference(
    tmp_path,
    test_path,
):
    validator = PlanValidator(tmp_path)

    plan = make_plan([test_path])

    with pytest.raises(ValueError):
        validator.validate(plan)


@pytest.mark.parametrize(
    "test_path",
    [
        "../tests/test_version.py",
        "../../test_version.py",
    ],
)
def test_plan_validator_rejects_test_path_escape(
    tmp_path,
    test_path,
):
    validator = PlanValidator(tmp_path)

    plan = make_plan([test_path])

    with pytest.raises(ValueError, match="Caminho fora do projeto"):
        validator.validate(plan)


def test_plan_validator_rejects_absolute_test_path(tmp_path):
    validator = PlanValidator(tmp_path)

    plan = make_plan([str(tmp_path / "tests" / "test_version.py")])

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        validator.validate(plan)


@pytest.mark.parametrize(
    "test_path",
    [
        "test_version.py",
        "tests/test_version.py",
        "tests/unit/test_version.py",
        "version_test.py",
    ],
)
def test_plan_validator_accepts_supported_pytest_names(
    tmp_path,
    test_path,
):
    validator = PlanValidator(tmp_path)

    plan = make_plan([test_path])

    assert validator.validate(plan) is True


def test_ai_planner_rejects_command_as_test_reference():
    response = json.dumps(
        {
            "objective": "teste",
            "changes": [],
            "tests": ["python -m pytest"],
            "risks": [],
        }
    )

    planner = AIPlanner(FixedAdapter(response))

    with pytest.raises(ValueError):
        planner.create_plan("teste")


def test_ai_planner_accepts_pytest_file_reference():
    response = json.dumps(
        {
            "objective": "teste",
            "changes": [],
            "tests": ["tests/test_version.py"],
            "risks": [],
        }
    )

    planner = AIPlanner(FixedAdapter(response))

    plan = planner.create_plan("teste")

    assert plan.tests == ["tests/test_version.py"]
