import pytest



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


def test_test_result_from_dict_rejects_non_integer_returncode():
    from core.schemas.models import TestResult

    with pytest.raises(
        ValueError,
        match="returncode do resultado de testes deve ser inteiro",
    ):
        TestResult.from_dict(
            {
                "success": True,
                "returncode": "0",
            }
        )


def test_test_result_from_dict_rejects_non_string_stdout():
    from core.schemas.models import TestResult

    with pytest.raises(
        ValueError,
        match="stdout do resultado de testes deve ser uma string",
    ):
        TestResult.from_dict(
            {
                "success": True,
                "stdout": 123,
            }
        )


def test_test_result_from_dict_rejects_non_string_stderr():
    from core.schemas.models import TestResult

    with pytest.raises(
        ValueError,
        match="stderr do resultado de testes deve ser uma string",
    ):
        TestResult.from_dict(
            {
                "success": True,
                "stderr": 123,
            }
        )


def test_test_result_combine_many_returns_success_for_empty_results():
    from core.schemas.models import TestResult

    result = TestResult.combine_many([])

    assert result == {
        "success": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }


def test_test_result_combine_many_combines_multiple_results():
    from core.schemas.models import TestResult

    result = TestResult.combine_many(
        [
            {
                "success": True,
                "returncode": 0,
                "stdout": "primeiro",
                "stderr": "",
            },
            {
                "success": False,
                "returncode": 1,
                "stdout": "segundo",
                "stderr": "erro",
            },
        ]
    )

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "primeiro" in result["stdout"]
    assert "segundo" in result["stdout"]
    assert "erro" in result["stderr"]


def test_test_result_combine_many_reduces_all_results():
    from core.schemas.models import TestResult

    result = TestResult.combine_many(
        [
            {
                "success": True,
                "returncode": 0,
                "stdout": "um",
                "stderr": "",
            },
            {
                "success": True,
                "returncode": 0,
                "stdout": "dois",
                "stderr": "",
            },
            {
                "success": False,
                "returncode": 2,
                "stdout": "tres",
                "stderr": "falhou",
            },
        ]
    )

    assert result["success"] is False
    assert result["returncode"] == 2
    assert "um" in result["stdout"]
    assert "dois" in result["stdout"]
    assert "tres" in result["stdout"]
    assert "falhou" in result["stderr"]


def test_test_result_from_dict_rejects_non_dict():
    from core.schemas.models import TestResult

    with pytest.raises(ValueError, match="Resultado de testes inválido"):
        TestResult.from_dict(None)


def test_test_result_from_dict_rejects_non_boolean_success():
    from core.schemas.models import TestResult

    with pytest.raises(
        ValueError,
        match="campo success do resultado de testes deve ser booleano",
    ):
        TestResult.from_dict(
            {
                "success": "true",
            }
        )
