import json

import pytest

from core.adapters.mock import MockAdapter
from core.planner.ai_planner import AIPlanner
from core.schemas.models import ChangeType


class FixedAdapter:
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt
        return self.response


def test_ai_planner_creates_plan_from_valid_json():
    response = json.dumps({
        "objective": "Criar sistema de clientes",
        "changes": [
            {
                "type": "create",
                "path": "app.py",
                "content": "print('hello')",
                "reason": "Criar arquivo principal",
            }
        ],
        "tests": ["tests/test_ai_planner.py"],
        "risks": ["Baixo"],
    })

    adapter = FixedAdapter(response)
    planner = AIPlanner(adapter)

    plan = planner.create_plan(
        instruction="Crie app.py",
        context="Projeto Python",
    )

    assert plan.objective == "Criar sistema de clientes"
    assert len(plan.changes) == 1
    assert plan.changes[0].change_type == ChangeType.CREATE
    assert plan.changes[0].path == "app.py"
    assert plan.changes[0].content == "print('hello')"
    assert plan.changes[0].reason == "Criar arquivo principal"
    assert plan.tests == ["tests/test_ai_planner.py"]
    assert plan.risks == ["Baixo"]


def test_ai_planner_supports_multiple_change_types():
    response = json.dumps({
        "objective": "Atualizar projeto",
        "changes": [
            {
                "type": "create",
                "path": "novo.py",
                "content": "x = 1",
                "reason": "Novo módulo",
            },
            {
                "type": "modify",
                "path": "app.py",
                "content": "x = 2",
                "reason": "Atualizar módulo",
            },
            {
                "type": "delete",
                "path": "antigo.py",
                "content": None,
                "reason": "Arquivo obsoleto",
            },
        ],
        "tests": [],
        "risks": [],
    })

    plan = AIPlanner(FixedAdapter(response)).create_plan(
        "Atualize o projeto"
    )

    assert len(plan.changes) == 3
    assert plan.changes[0].change_type == ChangeType.CREATE
    assert plan.changes[1].change_type == ChangeType.MODIFY
    assert plan.changes[2].change_type == ChangeType.DELETE


def test_ai_planner_rejects_invalid_json():
    adapter = FixedAdapter("isto não é JSON")

    with pytest.raises(
        ValueError,
        match="não é JSON válido",
    ):
        AIPlanner(adapter).create_plan("Crie app.py")


def test_ai_planner_rejects_non_text_ai_response():
    class NonTextAdapter:
        def generate(self, prompt):
            return {"invalid": "response"}

    planner = AIPlanner(NonTextAdapter())

    with pytest.raises(
        ValueError,
        match="A IA retornou um plano que não é JSON válido.",
    ):
        planner.create_plan("criar arquivo.py")


def test_ai_planner_rejects_non_object_json():
    adapter = FixedAdapter("[]")

    with pytest.raises(
        ValueError,
        match="deve ser um objeto JSON",
    ):
        AIPlanner(adapter).create_plan("Crie app.py")


def test_ai_planner_rejects_non_list_changes():
    response = json.dumps({
        "objective": "teste",
        "changes": {},
        "tests": [],
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="changes.*lista",
    ):
        AIPlanner(FixedAdapter(response)).create_plan("teste")


def test_ai_planner_rejects_invalid_change_object():
    response = json.dumps({
        "objective": "teste",
        "changes": ["invalido"],
        "tests": [],
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="Cada alteração",
    ):
        AIPlanner(FixedAdapter(response)).create_plan("teste")


def test_ai_planner_rejects_invalid_change_type():
    response = json.dumps({
        "objective": "teste",
        "changes": [
            {
                "type": "invalid",
                "path": "app.py",
                "content": "",
                "reason": "",
            }
        ],
        "tests": [],
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="Tipo de alteração inválido",
    ):
        AIPlanner(FixedAdapter(response)).create_plan("teste")


def test_ai_planner_rejects_invalid_path():
    response = json.dumps({
        "objective": "teste",
        "changes": [
            {
                "type": "create",
                "path": 123,
                "content": "",
                "reason": "",
            }
        ],
        "tests": [],
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="Caminho da alteração inválido",
    ):
        AIPlanner(FixedAdapter(response)).create_plan("teste")


def test_ai_planner_sends_instruction_and_context_to_adapter():
    response = json.dumps({
        "objective": "teste",
        "changes": [],
        "tests": [],
        "risks": [],
    })

    adapter = FixedAdapter(response)

    AIPlanner(adapter).create_plan(
        instruction="Analise o projeto",
        context="Python 3.14",
    )

    assert "Analise o projeto" in adapter.last_prompt
    assert "Python 3.14" in adapter.last_prompt


def test_ai_planner_rejects_invalid_objective_type():
    response = json.dumps({
        "objective": 123,
        "changes": [],
        "tests": [],
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="Objetivo inválido",
    ):
        AIPlanner(
            FixedAdapter(response)
        ).create_plan("teste")


def test_ai_planner_rejects_invalid_tests_type():
    response = json.dumps({
        "objective": "teste",
        "changes": [],
        "tests": "nao é lista",
        "risks": [],
    })

    with pytest.raises(
        ValueError,
        match="Campo 'tests' deve ser uma lista",
    ):
        AIPlanner(
            FixedAdapter(response)
        ).create_plan("teste")


def test_ai_planner_rejects_invalid_risks_type():
    response = json.dumps({
        "objective": "teste",
        "changes": [],
        "tests": [],
        "risks": "nao é lista",
    })

    with pytest.raises(
        ValueError,
        match="Campo 'risks' deve ser uma lista",
    ):
        AIPlanner(
            FixedAdapter(response)
        ).create_plan("teste")


def test_ai_planner_rejects_empty_objective():
    response = {
        "objective": "",
        "changes": [],
        "tests": [],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(ValueError, match="Objetivo"):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_rejects_absolute_change_path():
    response = {
        "objective": "Criar arquivo",
        "changes": [
            {
                "type": "create",
                "path": "/tmp/perigoso.py",
                "content": "print('x')",
                "reason": "teste",
            }
        ],
        "tests": [],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    plan = AIPlanner(FixedAdapter()).create_plan("Crie arquivo")

    assert plan.changes[0].path == "/tmp/perigoso.py"


def test_ai_planner_rejects_non_string_test():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": [123],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="Cada teste deve ser uma string",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_rejects_non_string_risk():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": [],
        "risks": [123],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="Cada risco deve ser uma string",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_normalizes_non_string_context():
    class Adapter:
        def generate(self, prompt):
            assert "CONTEXTO DO PROJETO:" in prompt
            return '{"objective": "teste", "changes": [], "tests": [], "risks": []}'

    planner = AIPlanner(Adapter())

    plan = planner.create_plan("apenas analisar", context=None)

    assert plan.objective == "teste"
    assert plan.changes == []


def test_ai_planner_truncates_oversized_context():
    class Adapter:
        def generate(self, prompt):
            assert "=== CONTEXTO TRUNCADO ===" in prompt
            assert "A" * AIPlanner.MAX_CONTEXT_CHARS in prompt
            return '{"objective": "teste", "changes": [], "tests": [], "risks": []}'

    planner = AIPlanner(Adapter())
    context = "A" * (AIPlanner.MAX_CONTEXT_CHARS + 100)

    plan = planner.create_plan("apenas analisar", context=context)

    assert plan.objective == "teste"


def test_ai_planner_rejects_non_string_reason():
    class Adapter:
        def generate(self, prompt):
            return (
                '{"objective": "teste", "changes": ['
                '{"type": "create", "path": "arquivo.py", '
                '"content": "VALUE = 1\\n", "reason": 123}'
                '], "tests": [], "risks": []}'
            )

    planner = AIPlanner(Adapter())

    with pytest.raises(
        ValueError,
        match="Motivo da alteração deve ser uma string",
    ):
        planner.create_plan("criar arquivo.py")


def test_ai_planner_rejects_delete_with_content():
    class Adapter:
        def generate(self, prompt):
            return (
                '{"objective": "teste", "changes": ['
                '{"type": "delete", "path": "arquivo.py", '
                '"content": "não deveria existir", "reason": "teste"}'
                '], "tests": [], "risks": []}'
            )

    planner = AIPlanner(Adapter())

    with pytest.raises(
        ValueError,
        match="DELETE não pode possuir conteúdo",
    ):
        planner.create_plan("deletar arquivo.py")


def test_ai_planner_rejects_create_without_text_content():
    class Adapter:
        def generate(self, prompt):
            return (
                '{"objective": "teste", "changes": ['
                '{"type": "create", "path": "arquivo.py", '
                '"content": null, "reason": "teste"}'
                '], "tests": [], "risks": []}'
            )

    planner = AIPlanner(Adapter())

    with pytest.raises(
        ValueError,
        match="CREATE exige conteúdo textual",
    ):
        planner.create_plan("criar arquivo.py")


def test_ai_planner_rejects_required_change_without_changes():
    class Adapter:
        def generate(self, prompt):
            return '{"objective": "teste", "changes": [], "tests": [], "risks": []}'

    planner = AIPlanner(Adapter())

    with pytest.raises(
        ValueError,
        match="A solicitação exige alteração no projeto",
    ):
        planner.create_plan("criar o arquivo novo.py")


def test_ai_planner_rejects_empty_test_reference():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": [""],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="Cada teste deve ser um caminho de arquivo pytest",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_rejects_absolute_test_reference():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": ["/tmp/test_version.py"],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_rejects_test_path_escape():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": ["../tests/test_version.py"],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")


def test_ai_planner_rejects_invalid_test_filename():
    response = {
        "objective": "teste",
        "changes": [],
        "tests": ["tests/version.py"],
        "risks": [],
    }

    class FixedAdapter:
        def generate(self, prompt):
            return json.dumps(response)

    with pytest.raises(
        ValueError,
        match="test_\\*\\.py ou \\*_test\\.py",
    ):
        AIPlanner(FixedAdapter()).create_plan("teste")
