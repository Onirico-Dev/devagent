import pytest

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


# ============================================================
# COMMAND PARSER — CASOS DE ENTRADA
# ============================================================


def test_parser_rejects_empty_command():
    with pytest.raises(ValueError, match="Comando vazio"):
        CommandParser().parse("")


def test_parser_rejects_whitespace_only_command():
    with pytest.raises(ValueError, match="Comando vazio"):
        CommandParser().parse("   ")


@pytest.mark.parametrize(
    "text",
    [
        "Crie app.py conteúdo",
        "Criar app.py conteúdo",
    ],
)
def test_parser_create_variants(text):
    command = CommandParser().parse(text)

    assert command.action == "create"
    assert command.target == "app.py"
    assert command.instruction == "conteúdo"


@pytest.mark.parametrize(
    "text",
    [
        "Modifique app.py conteúdo",
        "Modificar app.py conteúdo",
        "Altere app.py conteúdo",
    ],
)
def test_parser_modify_variants(text):
    command = CommandParser().parse(text)

    assert command.action == "modify"
    assert command.target == "app.py"
    assert command.instruction == "conteúdo"


@pytest.mark.parametrize(
    "text",
    [
        "delete app.py",
        "apague app.py",
        "remova app.py",
    ],
)
def test_parser_delete_variants(text):
    command = CommandParser().parse(text)

    assert command.action == "delete"
    assert command.target == "app.py"
    assert command.instruction == ""


def test_parser_analyze_command():
    command = CommandParser().parse(
        "Analise o projeto"
    )

    assert command.action == "analyze"
    assert command.target == ""
    assert command.instruction == "Analise o projeto"


def test_parser_command_without_arguments():
    command = CommandParser().parse("Analise")

    assert command.action == "analyze"
    assert command.target == ""
    assert command.instruction == ""


def test_parser_create_without_target():
    command = CommandParser().parse("Crie")

    assert command.action == "analyze"
    assert command.target == ""
    assert command.instruction == ""


def test_parser_preserves_raw_text_after_strip():
    command = CommandParser().parse(
        "   Crie app.py conteúdo   "
    )

    assert command.raw == "Crie app.py conteúdo"


def test_parser_preserves_case_in_instruction():
    command = CommandParser().parse(
        "Crie app.py Sistema de Clientes"
    )

    assert command.action == "create"
    assert command.target == "app.py"
    assert command.instruction == "Sistema de Clientes"


def test_parser_target_and_instruction_with_multiple_words():
    command = CommandParser().parse(
        "modifique core/app.py adicionar autenticação JWT"
    )

    assert command.action == "modify"
    assert command.target == "core/app.py"
    assert command.instruction == "adicionar autenticação JWT"


def test_parser_analyze_preserves_complete_instruction():
    command = CommandParser().parse(
        "Verifique todos os arquivos Python do projeto"
    )

    assert command.action == "analyze"
    assert command.target == ""
    assert command.instruction == (
        "Verifique todos os arquivos Python do projeto"
    )

def test_git_commit_transaction_does_not_commit_unrelated_changes(
    isolated_project,
):
    from core.executor.git_manager import GitManager

    unrelated = isolated_project / "nao_relacionado.txt"
    unrelated.write_text(
        "ALTERACAO EXTERNA\n",
        encoding="utf-8",
    )

    tracked = isolated_project / "transacao.txt"
    tracked.write_text(
        "ALTERACAO DA TRANSACAO\n",
        encoding="utf-8",
    )

    manager = GitManager(str(isolated_project))

    result = manager.commit_transaction(
        "transaction-isolation-test",
        "Teste de isolamento Git",
        paths=["transacao.txt"],
    )

    assert result["status"] == "committed"

    import subprocess

    committed = subprocess.run(
        [
            "git",
            "-C",
            str(isolated_project),
            "show",
            "--format=",
            "--name-only",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert "transacao.txt" in committed
    assert "nao_relacionado.txt" not in committed

    status = subprocess.run(
        [
            "git",
            "-C",
            str(isolated_project),
            "status",
            "--short",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "nao_relacionado.txt" in status
