import pytest

from agent import DevAgent
from core.schemas.models import ChangeType


def test_process_serializes_plan_and_updates_session(tmp_path):
    class FakeAI:
        def generate(self, prompt):
            return """{
                "objective": "Criar app.py",
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": "print('hello')",
                        "reason": "Criar aplicação"
                    }
                ],
                "tests": ["tests/test_agent.py"],
                "risks": []
            }"""

    agent = DevAgent(root=tmp_path, ai_adapter=FakeAI())

    result = agent.process("criar app.py")

    assert result["instruction"] == "criar app.py"
    assert result["objective"] == "Criar app.py"
    assert result["tests"] == ["tests/test_agent.py"]
    assert result["risks"] == []
    assert result["changes"] == [
        {
            "change_type": ChangeType.CREATE.value,
            "path": "app.py",
            "content": "print('hello')",
            "reason": "Criar aplicação",
        }
    ]

    assert agent.session.instructions[-1] == "criar app.py"
    assert agent.session.plans[-1] == result


def test_process_serializes_multiple_changes(tmp_path):
    class FakeAI:
        def generate(self, prompt):
            return """{
                "objective": "Criar dois arquivos",
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": "print('app')",
                        "reason": "Criar app"
                    },
                    {
                        "change_type": "create",
                        "path": "config.py",
                        "content": "DEBUG = True",
                        "reason": "Criar configuração"
                    }
                ],
                "tests": [],
                "risks": []
            }"""

    agent = DevAgent(root=tmp_path, ai_adapter=FakeAI())

    result = agent.process("criar app.py e criar config.py")

    assert result["objective"] == "Criar dois arquivos"
    assert len(result["changes"]) == 2

    assert result["changes"][0]["path"] == "app.py"
    assert result["changes"][0]["change_type"] == ChangeType.CREATE.value

    assert result["changes"][1]["path"] == "config.py"
    assert result["changes"][1]["change_type"] == ChangeType.CREATE.value


def test_create_ai_adapter_defaults_to_mock(monkeypatch, tmp_path):
    monkeypatch.delenv("DEVAGENT_AI", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    agent = DevAgent(root=tmp_path)

    assert agent.ai.__class__.__name__ == "MockAdapter"


def test_create_ai_adapter_rejects_groq_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVAGENT_AI", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="DEVAGENT_AI=groq exige GROQ_API_KEY configurada.",
    ):
        DevAgent(root=tmp_path)


def test_create_ai_adapter_accepts_groq_with_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVAGENT_AI", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    agent = DevAgent(root=tmp_path)

    assert agent.ai.__class__.__name__ == "GroqAdapter"


def test_build_transaction_from_approved_plan(tmp_path):
    agent = DevAgent(root=tmp_path)

    plan = {
        "instruction": "criar app.py",
        "objective": "Criar aplicação",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('hello')",
                "reason": "Criar app",
            }
        ],
        "tests": ["pytest"],
        "risks": [],
    }

    transaction = agent.build_transaction_from_approved_plan(plan)

    assert len(transaction.changes) == 1
    assert transaction.changes[0].change_type == ChangeType.CREATE
    assert transaction.changes[0].path == "app.py"
    assert transaction.changes[0].content == "print('hello')"
    assert transaction.metadata["instruction"] == "criar app.py"
    assert transaction.metadata["objective"] == "Criar aplicação"
    assert transaction.metadata["tests"] == ["pytest"]
    assert transaction.metadata["risks"] == []


def test_build_transaction_from_approved_plan_accepts_delete_without_content(
    tmp_path,
):
    agent = DevAgent(root=tmp_path)

    plan = {
        "instruction": "deletar app.py",
        "objective": "Remover aplicação",
        "changes": [
            {
                "change_type": "delete",
                "path": "app.py",
                "reason": "Remover arquivo",
            }
        ],
    }

    transaction = agent.build_transaction_from_approved_plan(plan)

    assert transaction.changes[0].change_type == ChangeType.DELETE
    assert transaction.changes[0].path == "app.py"
    assert transaction.changes[0].content is None


def test_build_transaction_rejects_invalid_plan_type(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(ValueError, match="Plano aprovado inválido."):
        agent.build_transaction_from_approved_plan(None)


def test_build_transaction_rejects_missing_instruction(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Plano aprovado não possui instrução válida.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": "x",
                    }
                ]
            }
        )


def test_build_transaction_rejects_empty_changes(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Plano aprovado não possui alterações.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "criar app.py",
                "changes": [],
            }
        )


def test_build_transaction_rejects_non_dict_change(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Alteração inválida no plano aprovado.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "criar app.py",
                "changes": [None],
            }
        )


def test_build_transaction_rejects_invalid_change_type(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Tipo de alteração inválido.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "alterar app.py",
                "changes": [
                    {
                        "change_type": None,
                        "path": "app.py",
                        "content": "x",
                    }
                ],
            }
        )


def test_build_transaction_rejects_empty_path(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Alteração sem caminho.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "criar arquivo",
                "changes": [
                    {
                        "change_type": "create",
                        "path": " ",
                        "content": "x",
                    }
                ],
            }
        )


def test_build_transaction_rejects_non_string_reason(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Motivo da alteração deve ser uma string.",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "criar app.py",
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": "x",
                        "reason": None,
                    }
                ],
            }
        )


def test_build_transaction_rejects_unknown_change_type(tmp_path):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Tipo de alteração desconhecido: rename",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "renomear app.py",
                "changes": [
                    {
                        "change_type": "rename",
                        "path": "app.py",
                        "content": "x",
                    }
                ],
            }
        )


def test_build_transaction_rejects_non_string_content_for_non_delete(
    tmp_path,
):
    agent = DevAgent(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Conteúdo inválido para alteração: app.py",
    ):
        agent.build_transaction_from_approved_plan(
            {
                "instruction": "criar app.py",
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": None,
                    }
                ],
            }
        )


def test_transaction_from_plan_rejects_empty_changes(tmp_path):
    agent = DevAgent(root=tmp_path)

    class FakePlan:
        changes = []

    with pytest.raises(
        ValueError,
        match="Não é possível criar uma transação sem alterações.",
    ):
        agent._transaction_from_plan(FakePlan())


def test_transaction_from_plan_preserves_changes(tmp_path):
    agent = DevAgent(root=tmp_path)

    change = object()

    class FakePlan:
        changes = [change]

    transaction = agent._transaction_from_plan(FakePlan())

    assert transaction.changes == [change]


def test_ask_ai_delegates_to_adapter(tmp_path):
    class FakeAI:
        def generate(self, prompt):
            return f"response:{prompt}"

    agent = DevAgent(root=tmp_path, ai_adapter=FakeAI())

    assert agent.ask_ai("hello") == "response:hello"
