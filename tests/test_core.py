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

def test_devagent_defaults_to_mock_adapter(monkeypatch):
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    monkeypatch.delenv("DEVAGENT_AI", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    agent = DevAgent()

    assert isinstance(agent.ai, MockAdapter)


def test_devagent_explicit_mock_adapter(monkeypatch):
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    monkeypatch.setenv("DEVAGENT_AI", "mock")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    agent = DevAgent()

    assert isinstance(agent.ai, MockAdapter)


def test_devagent_groq_requires_api_key(monkeypatch):
    from agent import DevAgent

    monkeypatch.setenv("DEVAGENT_AI", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    try:
        DevAgent()
    except RuntimeError as error:
        assert str(error) == (
            "DEVAGENT_AI=groq exige GROQ_API_KEY configurada."
        )
    else:
        raise AssertionError(
            "DEVAGENT_AI=groq deveria exigir GROQ_API_KEY."
        )


def test_devagent_selects_groq_adapter(monkeypatch):
    from agent import DevAgent
    from core.adapters.groq import GroqAdapter

    monkeypatch.setenv("DEVAGENT_AI", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    agent = DevAgent()

    assert isinstance(agent.ai, GroqAdapter)
    assert agent.ai.api_key == "test-key"


def test_devagent_unknown_provider_falls_back_to_mock(monkeypatch):
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    monkeypatch.setenv("DEVAGENT_AI", "provider-inexistente")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    agent = DevAgent()

    assert isinstance(agent.ai, MockAdapter)


def test_groq_adapter_requires_api_key(monkeypatch):
    from core.adapters.groq import GroqAdapter

    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    try:
        GroqAdapter()
    except RuntimeError as error:
        assert str(error) == "GROQ_API_KEY não configurada."
    else:
        raise AssertionError(
            "GroqAdapter deveria exigir GROQ_API_KEY."
        )


def test_groq_adapter_reads_model_from_environment(monkeypatch):
    from core.adapters.groq import GroqAdapter

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")

    adapter = GroqAdapter()

    assert adapter.api_key == "test-key"
    assert adapter.model == "test-model"


def test_groq_adapter_rejects_invalid_prompt(monkeypatch):
    from core.adapters.groq import GroqAdapter

    adapter = GroqAdapter(api_key="test-key")

    try:
        adapter.generate(None)
    except TypeError as error:
        assert str(error) == "O prompt deve ser uma string."
    else:
        raise AssertionError(
            "GroqAdapter deveria rejeitar prompt que não seja string."
        )


def test_groq_adapter_rejects_empty_prompt():
    from core.adapters.groq import GroqAdapter

    adapter = GroqAdapter(api_key="test-key")

    try:
        adapter.generate("   ")
    except ValueError as error:
        assert str(error) == "O prompt não pode ser vazio."
    else:
        raise AssertionError(
            "GroqAdapter deveria rejeitar prompt vazio."
        )


def test_groq_adapter_sends_expected_request(monkeypatch):
    from core.adapters.groq import GroqAdapter

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": " resposta "
                        }
                    }
                ]
            }

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        fake_post,
    )

    adapter = GroqAdapter(
        api_key="test-key",
        model="test-model",
        timeout=17,
    )

    result = adapter.generate("Olá")

    assert result == "resposta"
    assert captured["url"] == adapter.API_URL
    assert captured["kwargs"]["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["kwargs"]["json"] == {
        "model": "test-model",
        "messages": [
            {
                "role": "user",
                "content": "Olá",
            }
        ],
        "temperature": 0.2,
    }
    assert captured["kwargs"]["timeout"] == 17


def test_groq_adapter_rejects_invalid_response(monkeypatch):
    from core.adapters.groq import GroqAdapter

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": []
            }

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    adapter = GroqAdapter(api_key="test-key")

    try:
        adapter.generate("Olá")
    except RuntimeError as error:
        assert str(error) == "Resposta inválida da API Groq."
    else:
        raise AssertionError(
            "GroqAdapter deveria rejeitar resposta sem conteúdo válido."
        )


def test_groq_adapter_rejects_non_string_response(monkeypatch):
    from core.adapters.groq import GroqAdapter

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": 123
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    adapter = GroqAdapter(api_key="test-key")

    try:
        adapter.generate("Olá")
    except RuntimeError as error:
        assert str(error) == (
            "A resposta da Groq não contém texto válido."
        )
    else:
        raise AssertionError(
            "GroqAdapter deveria rejeitar conteúdo de resposta não textual."
        )


def test_groq_adapter_propagates_http_error(monkeypatch):
    from core.adapters.groq import GroqAdapter

    class FakeResponse:
        def raise_for_status(self):
            raise RuntimeError("HTTP 401")

        def json(self):
            return {}

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    adapter = GroqAdapter(api_key="test-key")

    with pytest.raises(RuntimeError, match="HTTP 401"):
        adapter.generate("Olá")


def test_groq_adapter_propagates_request_exception(monkeypatch):
    from core.adapters.groq import GroqAdapter

    def fake_post(*args, **kwargs):
        raise RuntimeError("falha de conexão")

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        fake_post,
    )

    adapter = GroqAdapter(api_key="test-key")

    with pytest.raises(RuntimeError, match="falha de conexão"):
        adapter.generate("Olá")


def test_groq_adapter_rejects_invalid_json_response(monkeypatch):
    from core.adapters.groq import GroqAdapter

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("JSON inválido")

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    adapter = GroqAdapter(api_key="test-key")

    with pytest.raises(ValueError, match="JSON inválido"):
        adapter.generate("Olá")


def test_groq_adapter_strips_response_content(monkeypatch):
    from core.adapters.groq import GroqAdapter

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "  resposta válida  ",
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    adapter = GroqAdapter(api_key="test-key")

    assert adapter.generate("Olá") == "resposta válida"


def test_build_transaction_from_approved_plan_rejects_whitespace_path():
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    agent = DevAgent(ai_adapter=MockAdapter())

    plan = {
        "instruction": "Crie app.py",
        "changes": [
            {
                "change_type": "create",
                "path": "   ",
                "content": "print('OK')",
                "reason": "teste",
            }
        ],
    }

    with pytest.raises(ValueError, match="Alteração sem caminho"):
        agent.build_transaction_from_approved_plan(plan)


def test_build_transaction_from_approved_plan_rejects_non_string_reason():
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    agent = DevAgent(ai_adapter=MockAdapter())

    plan = {
        "instruction": "Crie app.py",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('OK')",
                "reason": 123,
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="Motivo da alteração deve ser uma string",
    ):
        agent.build_transaction_from_approved_plan(plan)


def test_build_transaction_from_approved_plan_preserves_plan_metadata():
    from agent import DevAgent
    from core.adapters.mock import MockAdapter

    agent = DevAgent(ai_adapter=MockAdapter())

    plan = {
        "instruction": "Crie app.py",
        "objective": "Criar aplicação principal",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('OK')",
                "reason": "Arquivo principal",
            }
        ],
        "tests": ["pytest -q"],
        "risks": ["baixo"],
    }

    transaction = agent.build_transaction_from_approved_plan(plan)

    assert transaction.metadata == {
        "instruction": "Crie app.py",
        "objective": "Criar aplicação principal",
        "tests": ["pytest -q"],
        "risks": ["baixo"],
    }

def test_task_history_persists_transaction_metadata(tmp_path):
    from core.memory.task_history import TaskHistory

    history = TaskHistory(
        storage_path=tmp_path / "tasks.json"
    )

    approval_id = "approval-metadata-1"

    history.create(
        approval_id=approval_id,
        instruction="Crie app.py",
        plan={
            "instruction": "Crie app.py",
            "changes": [],
        },
    )

    metadata = {
        "instruction": "Crie app.py",
        "objective": "Criar aplicação principal",
        "tests": ["pytest -q"],
        "risks": ["baixo"],
    }

    history.update(
        approval_id,
        extra={
            "metadata": metadata,
        },
    )

    reloaded = TaskHistory(
        storage_path=tmp_path / "tasks.json"
    )

    task = reloaded.get(approval_id)

    assert task["metadata"] == metadata


# ============================================================
# REPAIR ENGINE — NORMALIZAÇÃO E CONTRATO DA RESPOSTA DA IA
# ============================================================

def test_repair_engine_accepts_valid_json(monkeypatch):
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro simples",'
                '"correction":"corrigir arquivo",'
                '"risk":"baixo",'
                '"action":"modify",'
                '"path":"app.py",'
                '"content":"print(\\"ok\\")"}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["risk"] == "baixo"
    assert result["action"] == "modify"
    assert result["path"] == "app.py"
    assert result["content"] == 'print("ok")'


def test_repair_engine_rejects_invalid_json():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return "não é json"

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"
    assert result["path"] == ""
    assert result["content"] == ""


def test_repair_engine_rejects_non_object_json():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return '["invalid"]'

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"


def test_repair_engine_rejects_incomplete_json():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro",'
                '"correction":"corrigir",'
                '"risk":"baixo",'
                '"action":"modify",'
                '"path":"app.py"}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"


def test_repair_engine_normalizes_invalid_risk():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro",'
                '"correction":"corrigir",'
                '"risk":"critico",'
                '"action":"modify",'
                '"path":"app.py",'
                '"content":"print(\\"ok\\")"}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["risk"] == "alto"
    assert result["action"] == "modify"


def test_repair_engine_normalizes_invalid_action():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro",'
                '"correction":"corrigir",'
                '"risk":"baixo",'
                '"action":"delete",'
                '"path":"app.py",'
                '"content":"print(\\"ok\\")"}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"


def test_repair_engine_rejects_create_without_content():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro",'
                '"correction":"criar arquivo",'
                '"risk":"baixo",'
                '"action":"create",'
                '"path":"app.py",'
                '"content":"   "}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="crie app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"


def test_repair_engine_rejects_modify_without_content():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            return (
                '{"diagnosis":"erro",'
                '"correction":"corrigir",'
                '"risk":"baixo",'
                '"action":"modify",'
                '"path":"app.py",'
                '"content":""}'
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"


def test_repair_engine_rejects_oversized_content():
    from core.engine.repair_engine import RepairEngine

    class FakeAI:
        def generate(self, prompt):
            import json

            return json.dumps(
                {
                    "diagnosis": "erro",
                    "correction": "corrigir",
                    "risk": "baixo",
                    "action": "modify",
                    "path": "app.py",
                    "content": "x" * 1_000_001,
                }
            )

    engine = RepairEngine(FakeAI())

    result = engine.analyze_failure(
        instruction="corrija app.py",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"
    assert result["path"] == ""
    assert result["content"] == ""
