import json

import pytest

from core.adapters.mock import MockAdapter
from core.planner.ai_planner import AIPlanner
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
                    "tests/test_ai_pipeline.py"
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


def test_ai_planner_rejects_empty_changes_for_create_request(tmp_path):
    class EmptyAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "Criar arquivo",
                "changes": [],
                "tests": [],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=EmptyAdapter(),
    )

    with pytest.raises(
        ValueError,
        match="sem alterações",
    ):
        pipeline.process(
            "Crie operacao_teste.txt contendo DevAgent OK"
        )


def test_devagent_uses_change_type_contract(tmp_path):
    from agent import DevAgent

    agent = DevAgent(
        root=str(tmp_path),
        ai_adapter=MockAdapter(),
    )

    result = agent.process(
        'Crie um arquivo chamado operacao_teste.txt contendo "DevAgent OK"'
    )

    assert len(result["changes"]) == 1

    change = result["changes"][0]

    assert change["change_type"] == "create"
    assert change["path"] == "operacao_teste.txt"
    assert change["content"] == '"DevAgent OK"'


def test_ai_planner_propagates_adapter_runtime_error():
    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("falha no provedor de IA")

    planner = AIPlanner(FailingAdapter())

    with pytest.raises(RuntimeError, match="falha no provedor de IA"):
        planner.create_plan("Crie app.py")


def test_ai_planner_does_not_convert_adapter_error_to_json_error():
    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("falha no provedor de IA")

    planner = AIPlanner(FailingAdapter())

    with pytest.raises(RuntimeError, match="falha no provedor de IA"):
        planner.create_plan("Crie app.py")
    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("HTTP 429")

    planner = AIPlanner(FailingAdapter())

    with pytest.raises(RuntimeError, match="HTTP 429"):
        planner.create_plan("Crie app.py")


def test_devagent_propagates_ai_adapter_runtime_error(tmp_path):
    from agent import DevAgent

    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("falha no provedor de IA")

    agent = DevAgent(
        root=str(tmp_path),
        ai_adapter=FailingAdapter(),
    )

    with pytest.raises(RuntimeError, match="falha no provedor de IA"):
        agent.process("Crie app.py")


def test_devagent_propagates_ai_adapter_http_error(tmp_path):
    from agent import DevAgent

    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("HTTP 429")

    agent = DevAgent(
        root=str(tmp_path),
        ai_adapter=FailingAdapter(),
    )

    with pytest.raises(RuntimeError, match="HTTP 429"):
        agent.process("Crie app.py")


def test_pipeline_sends_project_context_to_ai_planner(tmp_path):
    existing = tmp_path / "existing.py"
    existing.write_text(
        "def hello():\n    return 'hello'\n",
        encoding="utf-8",
    )

    class ContextAdapter:
        def __init__(self):
            self.prompt = None

        def generate(self, prompt):
            self.prompt = prompt
            return json.dumps({
                "objective": "Criar novo arquivo",
                "changes": [
                    {
                        "type": "create",
                        "path": "new.py",
                        "content": "print('new')",
                        "reason": "Novo arquivo",
                    }
                ],
                "tests": [],
                "risks": [],
            })

    adapter = ContextAdapter()

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=adapter,
    )

    pipeline.process("Crie new.py")

    assert "existing.py" in adapter.prompt
    assert "def hello():" in adapter.prompt
    assert "FUNÇÕES:" in adapter.prompt


def test_pipeline_accepts_multi_file_plan_with_existing_and_new_files(tmp_path):
    modify_file = tmp_path / "modify.py"
    delete_file = tmp_path / "delete.py"

    modify_file.write_text(
        "def old():\n    return 'old'\n",
        encoding="utf-8",
    )
    delete_file.write_text(
        "print('delete me')\n",
        encoding="utf-8",
    )

    class MultiFileAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "Atualizar projeto em múltiplos arquivos",
                "changes": [
                    {
                        "type": "modify",
                        "path": "modify.py",
                        "content": "def new():\n    return 'new'\n",
                        "reason": "Atualizar implementação",
                    },
                    {
                        "type": "create",
                        "path": "create.py",
                        "content": "print('created')\n",
                        "reason": "Adicionar novo módulo",
                    },
                    {
                        "type": "delete",
                        "path": "delete.py",
                        "content": None,
                        "reason": "Remover arquivo obsoleto",
                    },
                ],
                "tests": [],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=MultiFileAdapter(),
    )

    plan = pipeline.process(
        "Atualize modify.py, crie create.py e remova delete.py"
    )

    assert len(plan.changes) == 3
    assert [change.path for change in plan.changes] == [
        "modify.py",
        "create.py",
        "delete.py",
    ]


def test_pipeline_rejects_multi_file_plan_with_missing_modify_target(tmp_path):
    class MissingFileAdapter:
        def generate(self, prompt):
            return json.dumps({
                "objective": "Atualizar arquivo inexistente",
                "changes": [
                    {
                        "type": "modify",
                        "path": "missing.py",
                        "content": "print('new')\n",
                        "reason": "Arquivo ausente",
                    },
                    {
                        "type": "create",
                        "path": "create.py",
                        "content": "print('created')\n",
                        "reason": "Criar arquivo",
                    },
                ],
                "tests": [],
                "risks": [],
            })

    pipeline = DevAgentPipeline(
        root=str(tmp_path),
        ai_adapter=MissingFileAdapter(),
    )

    with pytest.raises(
        ValueError,
        match="Arquivo inexistente para MODIFY: missing.py",
    ):
        pipeline.process(
            "Atualize missing.py e crie create.py"
        )


def test_pipeline_uses_classic_planner_without_ai_adapter(tmp_path):
    pipeline = DevAgentPipeline(
        root=str(tmp_path),
    )

    plan = pipeline.process(
        "Crie classic.py com conteúdo print('classic')"
    )

    assert len(plan.changes) == 1
    assert plan.changes[0].path == "classic.py"
    assert plan.changes[0].content
