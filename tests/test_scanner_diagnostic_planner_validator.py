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
