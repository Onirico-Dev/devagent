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
        "tests": ["python -m pytest"],
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
    assert plan.tests == ["python -m pytest"]
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
