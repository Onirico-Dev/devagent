

def test_plan_from_dict_reconstructs_complete_plan():
    from core.schemas.models import ChangeType, Plan

    data = {
        "objective": "Criar arquivo",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('ok')",
                "reason": "Teste",
            }
        ],
        "tests": ["pytest tests/test_app.py"],
        "risks": [],
    }

    plan = Plan.from_dict(data)

    assert plan.objective == "Criar arquivo"
    assert len(plan.changes) == 1
    assert plan.changes[0].change_type == ChangeType.CREATE
    assert plan.changes[0].path == "app.py"
    assert plan.changes[0].content == "print('ok')"
    assert plan.changes[0].reason == "Teste"
    assert plan.tests == ["pytest tests/test_app.py"]
    assert plan.risks == []


def test_plan_from_dict_applies_optional_defaults():
    from core.schemas.models import Plan

    plan = Plan.from_dict(
        {
            "objective": "Criar arquivo",
            "changes": [],
        }
    )

    assert plan.changes == []
    assert plan.tests == []
    assert plan.risks == []


def test_plan_from_dict_rejects_non_dict():
    from core.schemas.models import Plan

    try:
        Plan.from_dict(None)
    except ValueError as exc:
        assert str(exc) == "Plano inválido."
    else:
        raise AssertionError("Era esperado ValueError.")


def test_plan_from_dict_rejects_missing_objective():
    from core.schemas.models import Plan

    try:
        Plan.from_dict({"changes": []})
    except KeyError:
        pass
    else:
        raise AssertionError("Era esperado KeyError.")
