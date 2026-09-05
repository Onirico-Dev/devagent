import pytest

from core.schemas.models import Change, ChangeType, Plan
from core.planner.plan_validator import PlanValidator


def make_validator(tmp_path):
    return PlanValidator(tmp_path)


def make_plan(changes=None, objective="teste"):
    return Plan(
        objective=objective,
        changes=changes or [],
        tests=[],
        risks=[],
    )


def make_change(change_type, path="arquivo.py", content="VALUE = 1\n"):
    return Change(
        change_type=change_type,
        path=path,
        content=content,
    )


def test_plan_validator_accepts_valid_plan(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(ChangeType.CREATE),
    ])

    result = validator.validate(plan)

    assert result is True


def test_plan_validator_rejects_non_plan(tmp_path):
    validator = make_validator(tmp_path)

    with pytest.raises(TypeError, match="O plano deve ser uma instância de Plan."):
        validator.validate({})


def test_plan_validator_rejects_non_string_objective(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan(objective=123)

    with pytest.raises(ValueError, match="Objetivo inválido"):
        validator.validate(plan)


def test_plan_validator_rejects_non_list_changes(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan()
    plan.changes = "não é lista"

    with pytest.raises(ValueError, match="Changes deve ser uma lista"):
        validator.validate(plan)


def test_plan_validator_rejects_change_without_path(tmp_path):
    validator = make_validator(tmp_path)

    change = make_change(ChangeType.CREATE)
    change.path = ""

    plan = make_plan([change])

    with pytest.raises(ValueError, match="Alteração sem caminho."):
        validator.validate(plan)


def test_plan_validator_rejects_path_outside_project(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(ChangeType.CREATE, "../fora.py"),
    ])

    with pytest.raises(ValueError, match="Caminho fora do projeto"):
        validator.validate(plan)


def test_plan_validator_rejects_absolute_path(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.CREATE,
            str(tmp_path / "absoluto.py"),
        ),
    ])

    with pytest.raises(ValueError, match="Caminho absoluto não permitido"):
        validator.validate(plan)


def test_plan_validator_rejects_delete_with_content(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.DELETE,
            "arquivo.py",
            "conteúdo proibido",
        ),
    ])

    with pytest.raises(ValueError, match="DELETE.*content|DELETE.*conteúdo"):
        validator.validate(plan)


def test_plan_validator_accepts_delete_without_content(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.DELETE,
            "arquivo.py",
            None,
        ),
    ])

    assert validator.validate(plan) is True


def test_plan_validator_requires_content_for_create(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.CREATE,
            "arquivo.py",
            None,
        ),
    ])

    with pytest.raises(ValueError, match="content|conteúdo"):
        validator.validate(plan)


def test_plan_validator_requires_content_for_modify(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.MODIFY,
            "arquivo.py",
            None,
        ),
    ])

    with pytest.raises(ValueError, match="content|conteúdo"):
        validator.validate(plan)


def test_plan_validator_accepts_modify_with_content(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.MODIFY,
            "arquivo.py",
            "VALUE = 2\n",
        ),
    ])

    assert validator.validate(plan) is True


def test_plan_validator_accepts_create_with_empty_string_content(tmp_path):
    validator = make_validator(tmp_path)

    plan = make_plan([
        make_change(
            ChangeType.CREATE,
            "arquivo.py",
            "",
        ),
    ])

    assert validator.validate(plan) is True

def test_plan_validator_rejects_empty_objective(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([])
    plan.objective = "   "

    with pytest.raises(ValueError, match="Objetivo não pode ser vazio."):
        validator.validate(plan)


def test_plan_validator_rejects_non_list_tests(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([])
    plan.tests = "não é lista"

    with pytest.raises(ValueError, match="Tests deve ser uma lista."):
        validator.validate(plan)


def test_plan_validator_rejects_non_list_risks(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([])
    plan.risks = "não é lista"

    with pytest.raises(ValueError, match="Risks deve ser uma lista."):
        validator.validate(plan)


def test_plan_validator_rejects_non_string_test(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([])
    plan.tests = [123]

    with pytest.raises(ValueError, match="Cada teste deve ser uma string."):
        validator.validate(plan)


def test_plan_validator_rejects_non_string_risk(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([])
    plan.risks = [123]

    with pytest.raises(ValueError, match="Cada risco deve ser uma string."):
        validator.validate(plan)


def test_plan_validator_rejects_non_change(tmp_path):
    validator = make_validator(tmp_path)
    plan = make_plan([object()])

    with pytest.raises(
        TypeError,
        match="Cada alteração deve ser uma instância de Change.",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_invalid_change_type(tmp_path):
    validator = make_validator(tmp_path)
    change = make_change(ChangeType.CREATE)
    change.change_type = "create"
    plan = make_plan([change])

    with pytest.raises(ValueError, match="Tipo de alteração inválido."):
        validator.validate(plan)


def test_plan_validator_rejects_non_string_change_reason(tmp_path):
    validator = make_validator(tmp_path)
    change = make_change(ChangeType.CREATE)
    change.reason = 123
    plan = make_plan([change])

    with pytest.raises(
        ValueError,
        match="Motivo da alteração deve ser uma string.",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_non_string_change_path(tmp_path):
    validator = make_validator(tmp_path)
    change = make_change(ChangeType.CREATE)
    change.path = 123
    plan = make_plan([change])

    with pytest.raises(
        ValueError,
        match="Caminho da alteração deve ser uma string.",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_modify_without_content(tmp_path):
    validator = make_validator(tmp_path)
    change = make_change(ChangeType.MODIFY, "arquivo.py", None)
    plan = make_plan([change])

    with pytest.raises(
        ValueError,
        match="MODIFY exige conteúdo textual.",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_delete_with_content(tmp_path):
    validator = make_validator(tmp_path)
    change = make_change(ChangeType.DELETE, "arquivo.py", "conteúdo")
    plan = make_plan([change])

    with pytest.raises(
        ValueError,
        match="DELETE não pode possuir conteúdo.",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_empty_test_reference():
    validator = PlanValidator()

    plan = Plan(
        objective="teste",
        changes=[],
        tests=[""],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Cada teste deve ser um caminho de arquivo pytest",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_absolute_test_path(tmp_path):
    validator = PlanValidator(str(tmp_path))

    plan = Plan(
        objective="Executar teste",
        changes=[],
        tests=["/tmp/test_example.py"],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_test_path_outside_project(tmp_path):
    validator = PlanValidator(str(tmp_path))

    plan = Plan(
        objective="Executar teste",
        changes=[],
        tests=["../test_example.py"],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_non_python_test_file(tmp_path):
    validator = PlanValidator(str(tmp_path))

    plan = Plan(
        objective="Executar teste",
        changes=[],
        tests=["test_example.txt"],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="O teste deve ser um arquivo Python",
    ):
        validator.validate(plan)


def test_plan_validator_rejects_invalid_pytest_filename(tmp_path):
    validator = PlanValidator(str(tmp_path))

    plan = Plan(
        objective="Executar teste",
        changes=[],
        tests=["example.py"],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match=r"test_.*\.py ou \*_test\.py",
    ):
        validator.validate(plan)


def test_plan_validator_project_coherence_rejects_outside_path(
    tmp_path,
):
    validator = PlanValidator(str(tmp_path))

    outside = tmp_path.parent / "outside.py"
    outside.write_text(
        "print('outside')",
        encoding="utf-8",
    )

    change = Change(
        change_type=ChangeType.MODIFY,
        path="../outside.py",
        content="print('modified')",
        reason="Teste de segurança",
    )

    plan = Plan(
        objective="Modificar arquivo",
        changes=[change],
        tests=[],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        validator.validate_project_coherence(plan)
