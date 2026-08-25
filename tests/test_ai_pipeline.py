import json

import pytest

from core.adapters.mock import MockAdapter
from core.pipeline import DevAgentPipeline


def test_pipeline_with_ai_planner_creates_valid_plan(tmp_path):
    adapter = MockAdapter()

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=adapter,
    )

    plan = pipeline.process(
        "Crie app.py contendo print('hello')"
    )

    assert plan.objective == "Crie app.py contendo print('hello')"
    assert len(plan.changes) == 1

    change = plan.changes[0]

    assert change.path == "app.py"
    assert change.content == "print('hello')"


def test_pipeline_with_ai_planner_does_not_modify_project(tmp_path):
    adapter = MockAdapter()

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=adapter,
    )

    pipeline.process(
        "Crie app.py contendo print('hello')"
    )

    assert not (tmp_path / "app.py").exists()


def test_pipeline_with_ai_planner_rejects_absolute_path(tmp_path):
    class UnsafeAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "teste",
                "changes": [
                    {
                        "type": "create",
                        "path": "/tmp/unsafe.py",
                        "content": "print('x')",
                        "reason": "teste",
                    }
                ],
                "tests": [],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=UnsafeAdapter(),
    )

    with pytest.raises(ValueError):
        pipeline.process("Crie arquivo inseguro")


def test_pipeline_with_ai_planner_rejects_parent_traversal(tmp_path):
    class UnsafeAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "teste",
                "changes": [
                    {
                        "type": "create",
                        "path": "../unsafe.py",
                        "content": "print('x')",
                        "reason": "teste",
                    }
                ],
                "tests": [],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=UnsafeAdapter(),
    )

    with pytest.raises(ValueError):
        pipeline.process("Crie arquivo inseguro")


def test_pipeline_with_ai_planner_accepts_multiple_changes(tmp_path):
    class MultiChangeAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "Criar estrutura",
                "changes": [
                    {
                        "type": "create",
                        "path": "app.py",
                        "content": "print('app')",
                        "reason": "Aplicação",
                    },
                    {
                        "type": "create",
                        "path": "config.py",
                        "content": "DEBUG = True",
                        "reason": "Configuração",
                    },
                ],
                "tests": [
                    "python -m pytest"
                ],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=MultiChangeAdapter(),
    )

    plan = pipeline.process("Crie a estrutura")

    assert len(plan.changes) == 2
    assert plan.changes[0].path == "app.py"
    assert plan.changes[1].path == "config.py"


def test_pipeline_records_ai_planner_usage(tmp_path):
    adapter = MockAdapter()

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=adapter,
    )

    pipeline.process(
        "Crie app.py contendo print('hello')"
    )

    event = pipeline.memory.last(1)[0]

    assert event["event"] == "plan_created"
    assert event["data"]["ai_planner"] is True
