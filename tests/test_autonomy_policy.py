import pytest

from core.autonomy_policy import (
    AutonomyDecision,
    AutonomyPolicy,
)
from core.schemas.models import Change, ChangeType, Plan
from core.security import SecurityPolicy


@pytest.fixture
def policy(tmp_path):
    return AutonomyPolicy(SecurityPolicy(tmp_path))


def make_plan(change_type=ChangeType.CREATE, content="print('ok')", risks=None):
    return Plan(
        objective="teste",
        changes=[
            Change(
                change_type=change_type,
                path="example.py",
                content=content,
            )
        ],
        tests=[],
        risks=[] if risks is None else risks,
    )


def test_low_risk_create_can_be_auto_approved(policy):
    plan = make_plan()

    assert policy.evaluate(plan) == AutonomyDecision.AUTO_APPROVE


def test_low_risk_modify_can_be_auto_approved(policy):
    plan = make_plan(
        change_type=ChangeType.MODIFY,
    )

    assert policy.evaluate(plan) == AutonomyDecision.AUTO_APPROVE


def test_delete_requires_human(policy):
    plan = make_plan(
        change_type=ChangeType.DELETE,
        content=None,
    )

    assert policy.evaluate(plan) == AutonomyDecision.REQUIRE_HUMAN


def test_declared_risk_requires_human(policy):
    plan = make_plan(
        risks=["Operação destrutiva"],
    )

    assert policy.evaluate(plan) == AutonomyDecision.REQUIRE_HUMAN


def test_high_content_risk_requires_human(policy):
    plan = make_plan(
        content="import subprocess\nsubprocess.run(['echo', 'ok'])",
    )

    assert policy.evaluate(plan) == AutonomyDecision.REQUIRE_HUMAN


def test_invalid_path_is_rejected_by_security(policy):
    plan = make_plan()
    plan.changes[0].path = "../outside.py"

    with pytest.raises(PermissionError, match="fora do projeto"):
        policy.evaluate(plan)


def test_non_plan_is_rejected(policy):
    with pytest.raises(
        TypeError,
        match="instância de Plan",
    ):
        policy.evaluate(None)
