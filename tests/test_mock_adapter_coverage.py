import ast
import json

from core.adapters.mock import MockAdapter


def test_repair_response_normalizes_natural_function_return():
    adapter = MockAdapter()

    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original: crie broken.py com conteúdo "
        "def soma(a, b) return a + b\n"
        "Erro: SyntaxError"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["path"] == "broken.py"
    assert "def soma(a, b):" in result["content"]
    assert "return a + b" in result["content"]

def test_planner_feedback_invalid_json_is_ignored():
    adapter = MockAdapter()
    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija broken.py\n"
        "CONTEXTO DO PROJETO:\n"
        "=== ARQUIVO: broken.py ===\n"
        "def broken(:\n"
        "=== ANÁLISE PYTHON ===\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        "{json inválido\n"
        "Retorne SOMENTE JSON válido."
    )

    result = json.loads(adapter._generate_planner_response(prompt))

    assert isinstance(result, dict)
    assert "changes" in result


def test_feedback_response_normalizes_invalid_feedback_shapes():
    adapter = MockAdapter()

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija a transação",
            "",
            {
                "transaction_id": "tx-1",
                "status": "failed",
                "failure_type": "runtime_error",
                "evidence": "evidência inválida",
                "transaction_metadata": "metadata inválida",
            },
        )
    )

    assert result["objective"]
    assert result["changes"] == []


def test_feedback_response_skips_invalid_original_changes():
    adapter = MockAdapter()

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija a transação",
            "",
            {
                "transaction_id": "tx-2",
                "status": "failed",
                "evidence": {},
                "transaction_metadata": {
                    "changes": [
                        "não é dict",
                        {"path": "", "content": "x"},
                        {
                            "path": "ok.py",
                            "change_type": "invalid",
                            "content": "x",
                        },
                    ]
                },
            },
        )
    )

    assert len(result["changes"]) == 1
    assert result["changes"][0]["path"] == "ok.py"
    assert result["changes"][0]["type"] == "modify"


def test_feedback_response_strips_content_marker():
    adapter = MockAdapter()

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija",
            "",
            {
                "transaction_id": "tx-3",
                "status": "failed",
                "evidence": {},
                "transaction_metadata": {
                    "changes": [
                        {
                            "path": "app.py",
                            "change_type": "modify",
                            "content": "com o conteúdo print('ok')",
                        }
                    ]
                },
            },
        )
    )

    assert result["changes"][0]["content"] == "print('ok')"


def test_feedback_response_non_list_original_changes():
    adapter = MockAdapter()

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija",
            "",
            {
                "transaction_id": "tx-4",
                "status": "failed",
                "evidence": {},
                "transaction_metadata": {
                    "changes": "não é uma lista",
                },
            },
        )
    )

    assert result["changes"] == []


def test_feedback_response_syntax_error_with_unusable_lineno(monkeypatch):
    adapter = MockAdapter()

    def fake_parse(*args, **kwargs):
        raise SyntaxError(
            "erro sintático",
            ("broken.py", 999, 1, "x"),
        )

    monkeypatch.setattr(ast, "parse", fake_parse)

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija",
            "",
            {
                "transaction_id": "tx-5",
                "status": "failed",
                "failure_type": "syntax_error",
                "evidence": {},
                "transaction_metadata": {
                    "changes": [
                        {
                            "path": "broken.py",
                            "change_type": "modify",
                            "content": "x = (\n",
                        }
                    ]
                },
            },
        )
    )

    assert result["changes"][0]["path"] == "broken.py"


def test_feedback_response_syntax_error_normalizes_after_loop(monkeypatch):
    adapter = MockAdapter()

    def fake_parse(*args, **kwargs):
        raise SyntaxError(
            "erro sintático",
            ("broken.py", 1, 1, "x"),
        )

    monkeypatch.setattr(ast, "parse", fake_parse)

    result = json.loads(
        adapter._generate_feedback_response(
            "corrija",
            "",
            {
                "transaction_id": "tx-6",
                "status": "failed",
                "failure_type": "syntax_error",
                "evidence": {},
                "transaction_metadata": {
                    "changes": [
                        {
                            "path": "broken.py",
                            "change_type": "modify",
                            "content": "x = (\n",
                        }
                    ]
                },
            },
        )
    )

    assert result["changes"][0]["content"].endswith("\n")


def test_compound_create_ignores_empty_parts():
    adapter = MockAdapter()

    result = adapter._build_compound_create_changes(
        "crie a.py e  e crie b.py"
    )

    assert isinstance(result, list)


def test_compound_create_returns_empty_when_part_cannot_be_built():
    adapter = MockAdapter()

    original = adapter._build_planner_change
    adapter._build_planner_change = lambda part, context: None

    try:
        result = adapter._build_compound_create_changes(
            "crie a.py e crie b.py"
        )
    finally:
        adapter._build_planner_change = original

    assert result == []


def test_regression_test_addition_builds_requested_test():
    adapter = MockAdapter()

    request = (
        "novo teste chamado test_repair_cycle. "
        "O teste deve criar uma transação com metadata contendo "
        "repair_cycle com remaining igual a 0, executar o Worker e "
        "verificar que a instrução não aparece em retry_instructions."
    )

    result = adapter._build_regression_test_addition(request)

    assert result is not None
    assert "def test_repair_cycle():" in result


def test_modify_change_regression_branch():
    adapter = MockAdapter()

    instruction = (
        "modifique test_sample.py "
        "novo teste chamado test_repair_cycle. "
        "O teste deve criar uma transação com metadata contendo "
        "repair_cycle com remaining igual a 0, executar o Worker e "
        "verificar que a instrução não aparece em retry_instructions."
    )

    context = (
        "=== ARQUIVO: test_sample.py ===\n"
        "def existing():\n"
        "    pass\n"
        "=== ANÁLISE PYTHON ===\n"
    )

    result = adapter._build_modify_change(instruction, context)

    assert result is not None
    assert result["path"] == "test_sample.py"
    assert "test_repair_cycle" in result["content"]

def test_modify_change_transformation_prefix_returns_none():
    adapter = MockAdapter()

    result = adapter._build_modify_change(
        "modifique app.py para fazer algo completamente desconhecido"
    )

    assert result is None


def test_compound_create_appends_after_empty_part(monkeypatch):
    import core.adapters.mock as mock_module

    adapter = MockAdapter()
    original_compile = mock_module.re.compile

    class FakePattern:
        def split(self, instruction):
            return ["crie primeiro.py", "", "crie segundo.py"]

    def fake_compile(pattern, *args, **kwargs):
        if "crie|criar|create" in pattern:
            return FakePattern()
        return original_compile(pattern, *args, **kwargs)

    monkeypatch.setattr(mock_module.re, "compile", fake_compile)
    monkeypatch.setattr(
        adapter,
        "_build_planner_change",
        lambda part, context: {
            "type": "create",
            "path": part.split()[-1],
            "content": "",
            "reason": part,
        },
    )

    result = adapter._build_compound_create_changes(
        "crie primeiro.py e crie segundo.py"
    )

    assert len(result) == 2


def test_compound_create_appends_valid_changes():
    adapter = MockAdapter()

    original = adapter._build_planner_change

    def fake_builder(part, context):
        return {
            "type": "create",
            "path": part.split()[-1],
            "content": "",
            "reason": part,
        }

    adapter._build_planner_change = fake_builder

    try:
        result = adapter._build_compound_create_changes(
            "crie primeiro.py e crie segundo.py"
        )
    finally:
        adapter._build_planner_change = original

    assert len(result) == 2
    assert result[0]["path"] == "primeiro.py"
    assert result[1]["path"] == "segundo.py"


def test_build_function_pytest_changes_supports_alternate_create_syntax():
    from core.adapters.mock import MockAdapter

    changes = MockAdapter()._build_function_pytest_changes(
        "crie arquivo math_ops.py com função somar(a, b) "
        "que retorne a + b. inclua um teste pytest para essa função."
    )

    assert len(changes) == 2
    assert changes[0]["path"] == "math_ops.py"
    assert "def somar(a, b):" in changes[0]["content"]
    assert changes[1]["path"] == "test_math_ops.py"
    assert "somar(2, 3) == 5" in changes[1]["content"]
