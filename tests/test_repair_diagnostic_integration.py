import json

from core.engine.diagnostic_engine import DiagnosticEngine
from core.engine.repair_engine import RepairEngine


class FakeAI:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


class FakeDiagnosticEngine:
    def __init__(self):
        self.calls = []

    def diagnose(self, test_result):
        self.calls.append(test_result)
        return {
            "success": False,
            "error_type": "SyntaxError",
            "message": "SyntaxError: erro de sintaxe",
            "file": "app.py",
            "line": 42,
            "raw": "SyntaxError: erro de sintaxe",
        }


def test_repair_engine_integrates_structured_diagnostic():
    response = json.dumps(
        {
            "diagnosis": "erro de sintaxe",
            "correction": "corrigir linha 42",
            "risk": "baixo",
            "action": "modify",
            "path": "app.py",
            "content": "print('ok')",
        }
    )

    ai = FakeAI(response)
    diagnostic = FakeDiagnosticEngine()

    engine = RepairEngine(
        ai,
        diagnostic_engine=diagnostic,
    )

    result = engine.analyze_failure(
        instruction="corrigir app.py",
        error='File "app.py", line 42\nSyntaxError: erro de sintaxe',
        test_output="teste falhou",
    )

    assert result["action"] == "modify"
    assert result["path"] == "app.py"

    assert diagnostic.calls == [
        {
            "success": False,
            "stderr": 'File "app.py", line 42\nSyntaxError: erro de sintaxe',
            "stdout": "teste falhou",
        }
    ]

    assert len(ai.prompts) == 1
    prompt = ai.prompts[0]

    assert "Diagnóstico estruturado da falha:" in prompt
    assert '"error_type": "SyntaxError"' in prompt
    assert '"file": "app.py"' in prompt
    assert '"line": 42' in prompt


def test_repair_engine_uses_default_diagnostic_engine():
    response = json.dumps(
        {
            "diagnosis": "erro de sintaxe",
            "correction": "corrigir",
            "risk": "baixo",
            "action": "modify",
            "path": "app.py",
            "content": "print('ok')",
        }
    )

    ai = FakeAI(response)
    engine = RepairEngine(ai)

    assert isinstance(engine.diagnostic_engine, DiagnosticEngine)

    engine.analyze_failure(
        instruction="corrigir",
        error='File "app.py", line 12\nSyntaxError: erro',
        test_output="falhou",
    )

    prompt = ai.prompts[0]

    assert "Diagnóstico estruturado da falha:" in prompt
    assert '"error_type": "SyntaxError"' in prompt
    assert '"file": "app.py"' in prompt
    assert '"line": 12' in prompt
