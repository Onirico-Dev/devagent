import json

from core.engine.repair_engine import RepairEngine


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
