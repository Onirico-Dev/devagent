from pathlib import Path

import pytest

from core.scanner.project_scanner import ProjectScanner
from core.engine.diagnostic_engine import DiagnosticEngine
from core.planner.planner import Planner
from core.planner.plan_validator import PlanValidator
from core.parser.command_parser import Command, CommandParser
from core.schemas.models import Change, ChangeType, Plan


# ============================================================
# PROJECT SCANNER
# ============================================================

def test_project_scanner_finds_files_and_directories(tmp_path):
    (tmp_path / "arquivo.txt").write_text("abc")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')")

    scanner = ProjectScanner(str(tmp_path))
    results = scanner.scan()

    paths = {item.path for item in results}

    assert "arquivo.txt" in paths
    assert "src" in paths
    assert str(Path("src") / "main.py") in paths

    file_info = next(item for item in results if item.path == "arquivo.txt")
    assert file_info.exists is True
    assert file_info.is_file is True
    assert file_info.is_directory is False
    assert file_info.size == 3


def test_project_scanner_ignores_git_directory(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret")
    (tmp_path / "normal.py").write_text("print('ok')")

    results = ProjectScanner(str(tmp_path)).scan()
    paths = {item.path for item in results}

    assert "normal.py" in paths
    assert ".git" not in paths
    assert str(Path(".git") / "config") not in paths


def test_project_scanner_missing_root_raises():
    missing = "/caminho/que/certamente/nao/existe"

    with pytest.raises(FileNotFoundError, match="Projeto não encontrado"):
        ProjectScanner(missing).scan()


# ============================================================
# DIAGNOSTIC ENGINE
# ============================================================

def test_diagnostic_engine_success():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": True,
        "stdout": "Tudo passou",
        "stderr": "",
    })

    assert result["success"] is True
    assert result["error_type"] is None
    assert result["message"] is None
    assert result["raw"] == "Tudo passou"
    assert result["file"] is None
    assert result["line"] is None


def test_diagnostic_engine_extracts_python_error():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": False,
        "stdout": "",
        "stderr": (
            'Traceback (most recent call last):\n'
            '  File "core/example.py", line 42, in run\n'
            '    raise ValueError("problema")\n'
            'ValueError: problema'
        ),
    })

    assert result["success"] is False
    assert result["error_type"] == "ValueError"
    assert result["file"] == "core/example.py"
    assert result["line"] == 42
    assert result["message"] == "ValueError: problema"


def test_diagnostic_engine_extracts_exception():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": False,
        "stdout": "",
        "stderr": "RuntimeException: falha",
    })

    assert result["error_type"] == "RuntimeException"
    assert result["message"] == "RuntimeException: falha"


def test_diagnostic_engine_unknown_error():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": False,
        "stdout": "algo inesperado aconteceu",
        "stderr": "",
    })

    assert result["error_type"] == "UnknownError"
    assert result["message"] == "algo inesperado aconteceu"


def test_diagnostic_engine_extracts_py_file_and_line():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": False,
        "stdout": "",
        "stderr": "core/test.py:99: alguma falha",
    })

    assert result["file"] == "core/test.py"
    assert result["line"] == 99


def test_diagnostic_engine_empty_failure():
    engine = DiagnosticEngine()

    result = engine.diagnose({
        "success": False,
        "stdout": "",
        "stderr": "",
    })

    assert result["error_type"] == "UnknownError"
    assert result["message"] == "Erro desconhecido."
    assert result["file"] is None
    assert result["line"] is None


# ============================================================
# PLANNER
# ============================================================

def test_planner_create():
    command = Command(
        raw="crie arquivo.py código",
        action="create",
        target="arquivo.py",
        instruction="print('hello')",
    )

    plan = Planner().create_plan(command)

    assert isinstance(plan, Plan)
    assert plan.objective == command.raw
    assert len(plan.changes) == 1

    change = plan.changes[0]
    assert change.change_type == ChangeType.CREATE
    assert change.path == "arquivo.py"
    assert change.content == "print('hello')"


def test_planner_create_requires_content():
    command = Command(
        raw="crie arquivo.py",
        action="create",
        target="arquivo.py",
        instruction="",
    )

    with pytest.raises(ValueError, match="CREATE exige conteúdo textual"):
        Planner().create_plan(command)


def test_planner_modify():
    command = Command(
        raw="modifique arquivo.py novo conteúdo",
        action="modify",
        target="arquivo.py",
        instruction="novo conteúdo",
    )

    plan = Planner().create_plan(command)

    assert len(plan.changes) == 1
    assert plan.changes[0].change_type == ChangeType.MODIFY
    assert plan.changes[0].path == "arquivo.py"
    assert plan.changes[0].content == "novo conteúdo"


def test_planner_delete():
    command = Command(
        raw="apague arquivo.py",
        action="delete",
        target="arquivo.py",
        instruction="motivo",
    )

    plan = Planner().create_plan(command)

    assert len(plan.changes) == 1

    change = plan.changes[0]
    assert change.change_type == ChangeType.DELETE
    assert change.path == "arquivo.py"
    assert change.content is None
    assert "Operação destrutiva" in plan.risks


def test_planner_unknown_action_creates_empty_plan():
    command = Command(
        raw="analise o projeto",
        action="analyze",
        target="",
        instruction="o projeto",
    )

    plan = Planner().create_plan(command)

    assert plan.changes == []
    assert plan.tests == []
    assert plan.risks == []


# ============================================================
# PLAN VALIDATOR
# ============================================================

def test_plan_validator_accepts_valid_create(tmp_path):
    plan = Plan(
        objective="criar arquivo",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="novo.py",
                content="print('ok')",
            )
        ],
    )

    assert PlanValidator(tmp_path).validate(plan) is True


def test_plan_validator_accepts_valid_modify(tmp_path):
    plan = Plan(
        objective="modificar arquivo",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="arquivo.py",
                content="novo conteúdo",
            )
        ],
    )

    assert PlanValidator(tmp_path).validate(plan) is True


def test_plan_validator_accepts_valid_delete(tmp_path):
    plan = Plan(
        objective="apagar arquivo",
        changes=[
            Change(
                change_type=ChangeType.DELETE,
                path="arquivo.py",
            )
        ],
    )

    assert PlanValidator(tmp_path).validate(plan) is True


def test_plan_validator_rejects_non_plan(tmp_path):
    with pytest.raises(TypeError, match="instância de Plan"):
        PlanValidator(tmp_path).validate({})


def test_plan_validator_rejects_invalid_objective(tmp_path):
    plan = Plan(
        objective=123,
        changes=[],
    )

    with pytest.raises(ValueError, match="Objetivo inválido"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_invalid_changes(tmp_path):
    plan = Plan(
        objective="teste",
        changes="nao é lista",
    )

    with pytest.raises(ValueError, match="Changes deve ser uma lista"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_empty_path(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="",
                content="x",
            )
        ],
    )

    with pytest.raises(ValueError, match="Alteração sem caminho"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_path_traversal(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="../fora.py",
                content="x",
            )
        ],
    )

    with pytest.raises(ValueError, match="Caminho fora do projeto"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_delete_with_content(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.DELETE,
                path="arquivo.py",
                content="não deveria existir",
            )
        ],
    )

    with pytest.raises(ValueError, match="DELETE não pode possuir conteúdo"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_create_without_string_content(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="arquivo.py",
                content=None,
            )
        ],
    )

    with pytest.raises(ValueError, match="CREATE exige conteúdo textual"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_modify_without_string_content(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="arquivo.py",
                content=None,
            )
        ],
    )

    with pytest.raises(ValueError, match="MODIFY exige conteúdo textual"):
        PlanValidator(tmp_path).validate(plan)

def test_command_parser_recognizes_create_variants():
    from core.parser.command_parser import CommandParser

    parser = CommandParser()

    cases = [
        "Crie app.py",
        "Crie um arquivo chamado app.py",
        "Crie arquivo app.py",
        "Criar arquivo app.py",
    ]

    for text in cases:
        command = parser.parse(text)

        assert command.action == "create"
        assert command.target == "app.py"


def test_command_parser_recognizes_modify_variants():
    from core.parser.command_parser import CommandParser

    parser = CommandParser()

    cases = [
        "Modifique app.py",
        "Modificar app.py",
        "Altere app.py",
        "Alterar arquivo app.py",
    ]

    for text in cases:
        command = parser.parse(text)

        assert command.action == "modify"
        assert command.target == "app.py"


def test_command_parser_recognizes_delete_variants():
    from core.parser.command_parser import CommandParser

    parser = CommandParser()

    cases = [
        "Delete app.py",
        "Apague app.py",
        "Remova app.py",
        "Remover arquivo app.py",
    ]

    for text in cases:
        command = parser.parse(text)

        assert command.action == "delete"
        assert command.target == "app.py"
        assert command.instruction == ""


def test_command_parser_recognizes_analysis():
    from core.parser.command_parser import CommandParser

    parser = CommandParser()

    for text in [
        "Analise o projeto",
        "Análise o projeto",
    ]:
        command = parser.parse(text)

        assert command.action == "analyze"
        assert command.target == ""
        assert command.instruction == text


def test_command_parser_does_not_execute_operation_without_target():
    from core.parser.command_parser import CommandParser

    parser = CommandParser()

    for text in [
        "Crie",
        "Modifique",
        "Delete",
        "Apague",
        "Remova",
    ]:
        command = parser.parse(text)

        assert command.action == "analyze"
        assert command.target == ""


def test_plan_validator_validates_all_changes(tmp_path):
    plan = Plan(
        objective="validar múltiplas alterações",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="primeiro.py",
                content="print('ok')",
            ),
            Change(
                change_type=ChangeType.CREATE,
                path="segundo.py",
                content=None,
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="CREATE exige conteúdo textual",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_empty_objective(tmp_path):
    plan = Plan(
        objective="",
        changes=[],
    )

    with pytest.raises(ValueError, match="Objetivo não pode ser vazio"):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_non_change_item(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[{"path": "arquivo.py"}],
    )

    with pytest.raises(
        TypeError,
        match="instância de Change",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_non_string_path(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path=123,
                content="x",
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="deve ser uma string",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_absolute_path(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path=str(tmp_path / "arquivo.py"),
                content="x",
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_non_string_test(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[],
        tests=["tests/test_plan.py", 123],
    )

    with pytest.raises(
        ValueError,
        match="Cada teste deve ser uma string",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_rejects_non_string_risk(tmp_path):
    plan = Plan(
        objective="teste",
        changes=[],
        risks=["risco", 123],
    )

    with pytest.raises(
        ValueError,
        match="Cada risco deve ser uma string",
    ):
        PlanValidator(tmp_path).validate(plan)


def test_plan_validator_validates_all_change_types(tmp_path):
    plan = Plan(
        objective="alterar projeto",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="novo.py",
                content="print('novo')",
            ),
            Change(
                change_type=ChangeType.MODIFY,
                path="existente.py",
                content="print('alterado')",
            ),
            Change(
                change_type=ChangeType.DELETE,
                path="antigo.py",
                content=None,
            ),
        ],
    )

    assert PlanValidator(tmp_path).validate(plan) is True

def test_change_engine_accepts_create_for_nonexistent_file(tmp_path):
    from core.engine.change_engine import ChangeEngine

    change = Change(
        change_type=ChangeType.CREATE,
        path="novo.py",
        content="print('ok')",
    )

    ChangeEngine(tmp_path).validate_change(change)


def test_change_engine_rejects_create_for_existing_file(tmp_path):
    from core.engine.change_engine import ChangeEngine

    target = tmp_path / "existente.py"
    target.write_text("print('old')")

    change = Change(
        change_type=ChangeType.CREATE,
        path="existente.py",
        content="print('new')",
    )

    with pytest.raises(
        FileExistsError,
        match="Arquivo já existe",
    ):
        ChangeEngine(tmp_path).validate_change(change)


def test_change_engine_accepts_modify_for_existing_file(tmp_path):
    from core.engine.change_engine import ChangeEngine

    target = tmp_path / "existente.py"
    target.write_text("print('old')")

    change = Change(
        change_type=ChangeType.MODIFY,
        path="existente.py",
        content="print('new')",
    )

    ChangeEngine(tmp_path).validate_change(change)


def test_change_engine_rejects_modify_for_nonexistent_file(tmp_path):
    from core.engine.change_engine import ChangeEngine

    change = Change(
        change_type=ChangeType.MODIFY,
        path="inexistente.py",
        content="print('new')",
    )

    with pytest.raises(
        FileNotFoundError,
        match="Arquivo não encontrado",
    ):
        ChangeEngine(tmp_path).validate_change(change)


def test_change_engine_rejects_delete_for_directory(tmp_path):
    from core.engine.change_engine import ChangeEngine

    (tmp_path / "diretorio").mkdir()

    change = Change(
        change_type=ChangeType.DELETE,
        path="diretorio",
    )

    with pytest.raises(
        IsADirectoryError,
        match="não é um arquivo",
    ):
        ChangeEngine(tmp_path).validate_change(change)


def test_project_scanner_rejects_file_root(tmp_path):
    root_file = tmp_path / "project.py"
    root_file.write_text("print('ok')")

    with pytest.raises(
        NotADirectoryError,
        match="Projeto não é um diretório",
    ):
        ProjectScanner(str(root_file)).scan()


def test_project_scanner_ignores_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("secret")

    project = tmp_path / "project"
    project.mkdir()
    (project / "normal.py").write_text("normal")

    link = project / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks não suportados neste ambiente.")

    results = ProjectScanner(str(project)).scan()
    paths = {item.path for item in results}

    assert "normal.py" in paths
    assert "external" not in paths
    assert str(Path("external") / "secret.py") not in paths


@pytest.mark.parametrize(
    "value",
    [None, [], "invalid", 123],
)
def test_diagnostic_engine_rejects_non_dict_result(value):
    engine = DiagnosticEngine()

    with pytest.raises(
        ValueError,
        match="Resultado de testes deve ser um dicionário.",
    ):
        engine.diagnose(value)


@pytest.mark.parametrize(
    "field",
    ["stdout", "stderr"],
)
def test_diagnostic_engine_rejects_non_string_output(field):
    engine = DiagnosticEngine()

    result = {
        "success": False,
        "stdout": "",
        "stderr": "",
    }
    result[field] = 123

    with pytest.raises(
        ValueError,
        match=rf"{field} do resultado de testes deve ser uma string.",
    ):
        engine.diagnose(result)


def test_planner_rejects_non_command():
    with pytest.raises(TypeError, match="Planner exige uma instância de Command"):
        Planner().create_plan({})


@pytest.mark.parametrize("action", ["create", "modify", "delete"])
def test_planner_rejects_empty_target(action):
    command = Command(
        raw="operação",
        action=action,
        target="",
        instruction="conteúdo",
    )

    with pytest.raises(ValueError, match="Operação exige um alvo textual"):
        Planner().create_plan(command)


# ============================================================
# PLAN VALIDATOR — PROJECT COHERENCE
# ============================================================

def test_plan_validator_rejects_modify_nonexistent_file(tmp_path):
    validator = PlanValidator(tmp_path)

    plan = Plan(
        objective="Modificar arquivo inexistente",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="inexistente.py",
                content="print('novo')",
                reason="Teste",
            )
        ],
        tests=[],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Arquivo inexistente para MODIFY",
    ):
        validator.validate_project_coherence(plan)

def test_plan_validator_rejects_delete_nonexistent_file(tmp_path):
    validator = PlanValidator(tmp_path)

    plan = Plan(
        objective="Excluir arquivo inexistente",
        changes=[
            Change(
                change_type=ChangeType.DELETE,
                path="inexistente.py",
                content=None,
                reason="Teste",
            )
        ],
        tests=[],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Arquivo inexistente para DELETE",
    ):
        validator.validate_project_coherence(plan)

def test_plan_validator_accepts_modify_existing_file(tmp_path):
    target = tmp_path / "existente.py"
    target.write_text(
        "print('original')\n",
        encoding="utf-8",
    )

    plan = Plan(
        objective="Modificar arquivo",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="existente.py",
                content="print('novo')",
                reason="Teste",
            )
        ],
        tests=[],
        risks=[],
    )

    validator = PlanValidator(str(tmp_path))

    assert validator.validate_project_coherence(plan) is True


def test_plan_validator_accepts_delete_existing_file(tmp_path):
    target = tmp_path / "existente.py"
    target.write_text(
        "print('original')\n",
        encoding="utf-8",
    )

    plan = Plan(
        objective="Excluir arquivo",
        changes=[
            Change(
                change_type=ChangeType.DELETE,
                path="existente.py",
                content=None,
                reason="Teste",
            )
        ],
        tests=[],
        risks=[],
    )

    validator = PlanValidator(str(tmp_path))

    assert validator.validate_project_coherence(plan) is True

# ============================================================
# PLAN VALIDATOR — MULTI-FILE PROJECT COHERENCE
# ============================================================


def test_plan_validator_project_coherence_accepts_mixed_existing_changes(
    tmp_path,
):
    (tmp_path / "modify.py").write_text(
        "print('original')\n",
        encoding="utf-8",
    )
    (tmp_path / "delete.py").write_text(
        "print('remover')\n",
        encoding="utf-8",
    )

    validator = PlanValidator(tmp_path)

    plan = Plan(
        objective="Modificar, excluir e criar arquivos",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="modify.py",
                content="print('novo')",
                reason="Atualizar arquivo",
            ),
            Change(
                change_type=ChangeType.DELETE,
                path="delete.py",
                content=None,
                reason="Remover arquivo",
            ),
            Change(
                change_type=ChangeType.CREATE,
                path="create.py",
                content="print('criado')",
                reason="Criar arquivo",
            ),
        ],
        tests=[],
        risks=[],
    )

    assert validator.validate_project_coherence(plan) is True


def test_plan_validator_project_coherence_rejects_mixed_plan_with_missing_modify(
    tmp_path,
):
    (tmp_path / "existing.py").write_text(
        "print('original')\n",
        encoding="utf-8",
    )

    validator = PlanValidator(tmp_path)

    plan = Plan(
        objective="Plano misto inválido",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="existing.py",
                content="print('novo')",
                reason="Atualizar arquivo",
            ),
            Change(
                change_type=ChangeType.DELETE,
                path="missing.py",
                content=None,
                reason="Excluir arquivo inexistente",
            ),
        ],
        tests=[],
        risks=[],
    )

    with pytest.raises(
        ValueError,
        match="Arquivo inexistente para DELETE",
    ):
        validator.validate_project_coherence(plan)
