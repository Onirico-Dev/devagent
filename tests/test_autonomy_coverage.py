import pytest

from core.autonomy_policy import AutonomyDecision, AutonomyPolicy
from core.gateway import DevAgentGateway
from core.schemas.models import Change, ChangeType, Plan
from core.security import SecurityPolicy


@pytest.fixture
def policy(tmp_path):
    return AutonomyPolicy(SecurityPolicy(tmp_path))


def make_plan():
    return Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="example.py",
                content="print('ok')",
            )
        ],
        tests=[],
        risks=[],
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("objective", ""),
        ("objective", None),
        ("changes", []),
        ("changes", ()),
        ("tests", ()),
        ("tests", [123]),
        ("risks", ()),
        ("changes", [object()]),
    ],
)
def test_policy_rejects_malformed_plan_fields(policy, field, value):
    plan = make_plan()
    setattr(plan, field, value)

    assert policy.evaluate(plan) == AutonomyDecision.REQUIRE_HUMAN


@pytest.mark.parametrize(
    "change_field,value",
    [
        ("path", ""),
        ("path", None),
        ("content", None),
        ("change_type", "invalid"),
    ],
)
def test_policy_rejects_malformed_changes(policy, change_field, value):
    plan = make_plan()
    setattr(plan.changes[0], change_field, value)

    assert policy.evaluate(plan) == AutonomyDecision.REQUIRE_HUMAN


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"objective": None, "changes": []},
        {"objective": "teste"},
        {"objective": "teste", "changes": []},
        {"objective": "teste", "changes": ()},
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py", "content": "ok"}],
            "tests": (),
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py", "content": "ok"}],
            "tests": [123],
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py", "content": "ok"}],
            "risks": (),
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py", "content": "ok"}],
            "risks": [123],
        },
        {"objective": "teste", "changes": [None]},
        {
            "objective": "teste",
            "changes": [{"change_type": "invalid", "path": "a.py", "content": "ok"}],
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": None, "content": "ok"}],
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": " ", "content": "ok"}],
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py", "content": 123}],
        },
        {
            "objective": "teste",
            "changes": [{"change_type": "create", "path": "a.py"}],
        },
        {
            "objective": "teste",
            "changes": [
                {
                    "change_type": "create",
                    "path": "a.py",
                    "content": "ok",
                    "reason": 123,
                }
            ],
        },
    ],
)
def test_gateway_rejects_invalid_persisted_plan_data(data):
    assert DevAgentGateway._is_valid_autonomy_plan_data(data) is False


@pytest.mark.parametrize(
    "change",
    [
        {
            "change_type": "create",
            "path": "a.py",
            "content": "print('ok')",
        },
        {
            "change_type": "modify",
            "path": "a.py",
            "content": "print('updated')",
            "reason": "Atualização",
        },
        {
            "change_type": "delete",
            "path": "a.py",
            "content": None,
        },
    ],
)
def test_gateway_accepts_well_formed_persisted_changes(change):
    data = {
        "objective": "teste",
        "changes": [change],
        "tests": [],
        "risks": [],
    }

    assert DevAgentGateway._is_valid_autonomy_plan_data(data) is True


@pytest.mark.parametrize("approval_id", [None, "", "   ", 123])
def test_gateway_rejects_invalid_autonomous_approval_id(approval_id):
    gateway = object.__new__(DevAgentGateway)

    with pytest.raises(ValueError, match="ID de aprovação inválido"):
        gateway.approve_autonomously(approval_id)
