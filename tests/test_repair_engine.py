import json
from core.adapters.mock import MockAdapter

from core.engine.repair_engine import RepairEngine


def test_repair_engine_with_mock_adapter_uses_explicit_operands():
    from core.adapters.mock import MockAdapter
    from core.engine.repair_engine import RepairEngine

    engine = RepairEngine(MockAdapter())

    result = engine.analyze_failure(
        instruction=(
            "crie o arquivo core/adapters/integration_probe.py "
            "contendo def multiplicar(a, b): return a + b "
            "e crie um teste pytest correspondente "
            "que exija que multiplicar(2, 3) == 6"
        ),
        error="AssertionError",
        test_output="E       assert 5 == 6",
    )

    assert result["action"] == "modify"
    assert result["path"].endswith("integration_probe.py")
    assert result["content"] == (
        "def multiplicar(a, b):\n"
        "    return a * b"
    )


def test_repair_engine_with_mock_adapter_rejects_binary_inference_without_operands():
    from core.adapters.mock import MockAdapter
    from core.engine.repair_engine import RepairEngine

    engine = RepairEngine(MockAdapter())

    result = engine.analyze_failure(
        instruction=(
            "crie o arquivo core/adapters/integration_no_operands.py "
            "contendo def multiplicar(a, b): return a + b "
            "e crie um teste pytest correspondente"
        ),
        error="AssertionError",
        test_output="E       assert 5 == 6",
    )

    assert result["action"] == "none"
    assert result["path"] == ""
    assert result["content"] == ""


class FakeAI:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


def test_repair_engine_returns_valid_response():
    response = json.dumps({
        "diagnosis": "Erro de sintaxe",
        "correction": "Corrigir a sintaxe",
        "risk": "baixo",
        "action": "modify",
        "path": "app.py",
        "content": "print('ok')",
    })

    ai = FakeAI(response)
    engine = RepairEngine(ai)

    result = engine.analyze_failure(
        instruction="corrigir app.py",
        error="SyntaxError",
        test_output="falha no teste",
    )

    assert result["diagnosis"] == "Erro de sintaxe"
    assert result["correction"] == "Corrigir a sintaxe"
    assert result["risk"] == "baixo"
    assert result["action"] == "modify"
    assert result["path"] == "app.py"
    assert result["content"] == "print('ok')"


def test_repair_engine_sends_complete_context_to_ai():
    ai = FakeAI("{}")
    engine = RepairEngine(ai)

    engine.analyze_failure(
        instruction="corrigir parser",
        error="ValueError",
        test_output="teste falhou",
    )

    assert len(ai.prompts) == 1

    prompt = ai.prompts[0]

    assert "corrigir parser" in prompt
    assert "ValueError" in prompt
    assert "teste falhou" in prompt
    assert "Retorne SOMENTE JSON válido" in prompt


def test_repair_engine_invalid_json_returns_safe_failure():
    ai = FakeAI("isto não é JSON")

    result = RepairEngine(ai).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "isto não é JSON",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_repair_engine_incomplete_json_returns_safe_failure():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "baixo",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "Resposta incompleta do modelo.",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_repair_engine_invalid_risk_becomes_high():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "critico",
        "action": "modify",
        "path": "app.py",
        "content": "novo conteúdo",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result["risk"] == "alto"
    assert result["action"] == "modify"


def test_repair_engine_invalid_action_becomes_none():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "medio",
        "action": "delete",
        "path": "app.py",
        "content": "conteúdo",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result["risk"] == "medio"
    assert result["action"] == "none"


def test_repair_engine_accepts_create_action():
    response = json.dumps({
        "diagnosis": "arquivo inexistente",
        "correction": "criar arquivo",
        "risk": "medio",
        "action": "create",
        "path": "novo.py",
        "content": "print('novo')",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="criar novo.py",
        error="FileNotFoundError",
        test_output="arquivo ausente",
    )

    assert result["action"] == "create"
    assert result["path"] == "novo.py"
    assert result["content"] == "print('novo')"


def test_repair_engine_accepts_none_action():
    response = json.dumps({
        "diagnosis": "não foi possível determinar a causa",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir problema",
        error="erro desconhecido",
        test_output="falha",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"

def test_repair_engine_rejects_empty_content_for_modify():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "corrigir arquivo",
        "risk": "medio",
        "action": "modify",
        "path": "app.py",
        "content": "",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir app.py",
        error="SyntaxError",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "Resposta do modelo não contém conteúdo de reparo.",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_repair_engine_rejects_whitespace_content_for_create():
    response = json.dumps({
        "diagnosis": "arquivo ausente",
        "correction": "criar arquivo",
        "risk": "baixo",
        "action": "create",
        "path": "novo.py",
        "content": "   \n\t  ",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="criar novo.py",
        error="FileNotFoundError",
        test_output="arquivo ausente",
    )

    assert result["action"] == "none"
    assert result["risk"] == "alto"
    assert result["path"] == ""
    assert result["content"] == ""


def test_repair_engine_non_dict_json_returns_safe_failure():
    result = RepairEngine(FakeAI("[]")).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "Resposta do modelo não é um objeto JSON.",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_repair_engine_non_string_risk_becomes_high():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": 123,
        "action": "modify",
        "path": "app.py",
        "content": "novo conteúdo",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result["risk"] == "alto"


def test_repair_engine_non_string_action_becomes_none():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "baixo",
        "action": 123,
        "path": "app.py",
        "content": "novo conteúdo",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result["action"] == "none"


def test_repair_engine_non_string_path_becomes_empty():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "baixo",
        "action": "none",
        "path": 123,
        "content": "",
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result["path"] == ""


def test_repair_engine_non_string_content_becomes_safe_failure():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "baixo",
        "action": "modify",
        "path": "app.py",
        "content": 123,
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir",
        error="erro",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "Resposta do modelo não contém conteúdo de reparo.",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_repair_engine_rejects_oversized_repair_content():
    response = json.dumps({
        "diagnosis": "causa",
        "correction": "correção",
        "risk": "baixo",
        "action": "modify",
        "path": "app.py",
        "content": "x" * 1_000_001,
    })

    result = RepairEngine(FakeAI(response)).analyze_failure(
        instruction="corrigir app.py",
        error="erro",
        test_output="falhou",
    )

    assert result == {
        "diagnosis": "Conteúdo de reparo excede o limite permitido.",
        "correction": "",
        "risk": "alto",
        "action": "none",
        "path": "",
        "content": "",
    }


def test_mock_adapter_repairs_natural_language_pytest_request():
    import json

    from core.adapters.mock import MockAdapter

    instruction = (
        "crie um arquivo chamado smoke_test.py na raiz do projeto "
        "contendo um teste pytest chamado test_smoke que faça a "
        "asserção de que 2 + 2 é igual a 4"
    )

    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        f"Objetivo original: {instruction}\n"
        "Erro: SyntaxError\n"
        "Saída dos testes: SyntaxError: invalid syntax"
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "smoke_test.py"
    assert result["content"] == (
        "def test_smoke():\n"
        "    assert 2 + 2 == 4"
    )


def test_repair_engine_sends_failure_type_to_ai():
    response = json.dumps({
        "diagnosis": "Erro de sintaxe",
        "correction": "Corrigir sintaxe",
        "risk": "baixo",
        "action": "modify",
        "path": "app.py",
        "content": "print('ok')",
    })

    ai = FakeAI(response)
    engine = RepairEngine(ai)

    engine.analyze_failure(
        instruction="corrigir app.py",
        error="SyntaxError",
        test_output="falhou",
        failure_type="syntax_error",
    )

    assert len(ai.prompts) == 1
    assert "Tipo de falha classificado:" in ai.prompts[0]
    assert "syntax_error" in ai.prompts[0]


def test_mock_adapter_extracts_content_from_natural_language_create_request():
    adapter = MockAdapter()
    response = json.loads(
        adapter.generate(
            "INSTRUÇÃO DO USUÁRIO: crie o arquivo cli_content_smoke.py "
            "com print('CLI CONTENT OK')\n"
            "CONTEXTO DO PROJETO:"
        )
    )

    assert response["changes"][0]["path"] == "cli_content_smoke.py"
    assert response["changes"][0]["content"] == "print('CLI CONTENT OK')"


def test_build_prompt_without_diagnostic_omits_diagnostic_context():
    from core.engine.repair_engine import RepairEngine

    engine = RepairEngine(ai_adapter=None)

    prompt = engine._build_prompt(
        instruction="corrigir arquivo.py",
        error="erro de sintaxe",
        test_output="pytest failed",
        diagnostic=None,
    )

    assert "Diagnóstico estruturado da falha:" not in prompt
    assert "Objetivo original:" in prompt
    assert "Erro:" in prompt
    assert "Saída dos testes:" in prompt
