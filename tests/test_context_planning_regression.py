"""Regression tests for context actually delivered to the planning adapter."""

import json
from pathlib import Path

import pytest

from core.context.project_context import ProjectContext
from core.pipeline import DevAgentPipeline
from core.planner.ai_planner import AIPlanner


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("extension", ["js", "jsx", "ts", "tsx", "html", "css"])
def test_frontend_sources_are_included_as_complete_text(tmp_path, extension):
    name = f"web/view.{extension}"
    content = "FRONTEND_CONTENT_END\n"
    write(tmp_path, name, content)
    context = ProjectContext(tmp_path).build([name])
    assert f"=== ARQUIVO: {name} ===" in context
    assert content in context


def test_discovery_prunes_ignored_and_symlink_trees(tmp_path):
    write(tmp_path, "src/app.py", "APP = 1\n")
    write(tmp_path, "logs/session.json", '{"secret": "health"}')
    write(tmp_path, "node_modules/package/index.js", "SECRET_HEALTH")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    write(outside, "external.js", "EXTERNAL_SECRET_HEALTH")
    (tmp_path / "external").symlink_to(outside, target_is_directory=True)
    (tmp_path / "alias.py").symlink_to(tmp_path / "src/app.py")
    (tmp_path / "outside.js").symlink_to(outside / "external.js")
    context = ProjectContext(tmp_path)
    assert context.list_files() == [Path("src/app.py")]
    result = context.build(["outside.js", "alias.py"])
    assert "EXTERNAL_SECRET_HEALTH" not in result
    assert "alias.py" not in result
    assert context.select_relevant_paths("GET /health") == []


def test_explicit_paths_keep_request_order_and_are_validated(tmp_path):
    write(tmp_path, "web/app.js", "const ready = true;\n")
    write(tmp_path, "api.py", "READY = True\n")
    write(tmp_path, ".env.local", "SECRET=yes")
    write(tmp_path, "photo.png", "secret")
    context = ProjectContext(tmp_path)
    paths = context.select_relevant_paths(
        "Modifique web/app.js e api.py, preserve web/app.js. "
        "Não leia ../outside.py, .env.local, photo.png ou missing.py."
    )
    assert paths == ["web/app.js", "api.py"]
    result = context.build(paths)
    assert result.index("=== ARQUIVO: web/app.js ===") < result.index("=== ARQUIVO: api.py ===")


def test_routes_ui_labels_and_identifiers_select_sources_before_tests(tmp_path):
    write(tmp_path, "api.py", 'route = "/health"\n')
    write(tmp_path, "core/service.py", "def health():\n    return {}\n")
    write(tmp_path, "web/app.js", 'fetch("/health");\n')
    write(tmp_path, "web/index.html", "<h2>Estado do serviço</h2>\n")
    write(tmp_path, "core/provider.py", "ai_provider = 'Mock'\n")
    write(tmp_path, "tests/test_api.py", 'route = "/health"\n')
    write(tmp_path, "web/app.test.js", 'fetch("/health");\n')
    write(tmp_path, "unrelated.py", "IRRELEVANT = True\n")
    context = ProjectContext(tmp_path)
    paths = context.select_relevant_paths(
        'Acrescente ai_provider ao GET /health e ao painel “Estado do serviço”.'
    )
    assert set(paths) == {
        "api.py", "core/service.py", "web/app.js", "web/index.html",
        "core/provider.py", "tests/test_api.py", "web/app.test.js",
    }
    assert max(paths.index(name) for name in paths if name not in {
        "tests/test_api.py", "web/app.test.js",
    }) < min(paths.index("tests/test_api.py"), paths.index("web/app.test.js"))


def test_selection_bypasses_general_inventory_limit(tmp_path):
    write(tmp_path, "a.py", "OTHER = 1\n")
    write(tmp_path, "web/app.js", 'fetch("/health")\n')
    context = ProjectContext(tmp_path, max_files=1)
    assert context.list_files() == [Path("a.py")]
    selected = context.select_relevant_paths("GET /health")
    assert selected == ["web/app.js"]
    result = context.build(selected)
    assert 'fetch("/health")' in result


def test_matching_test_files_rank_before_other_tests_and_documentation(tmp_path):
    write(tmp_path, "web/app.js", 'fetch("/health");')
    write(tmp_path, "web/app.test.js", '// /health')
    write(tmp_path, "tests/test_other.py", '# /health')
    write(tmp_path, "README.md", 'GET /health')
    context = ProjectContext(tmp_path)
    assert context.select_relevant_paths("GET /health") == [
        "web/app.js", "web/app.test.js", "tests/test_other.py", "README.md",
    ]


def test_discovery_respects_file_and_search_limits(tmp_path, monkeypatch):
    write(tmp_path, "large.js", "health" * 20)
    context = ProjectContext(tmp_path, max_file_size=5)
    assert context.select_relevant_paths("GET /health") == []
    write(tmp_path, "small.js", "x")
    monkeypatch.setattr(context, "_source_files", lambda: iter([Path("small.js")] * 1002))
    reads = []
    monkeypatch.setattr(context, "read_file", lambda path: reads.append(path) or "x")
    assert context.select_relevant_paths("GET /health") == []
    assert len(reads) == 1000


def test_custom_context_budget_never_splits_source_files(tmp_path):
    first = "// FIRST\n" + "x" * 1500 + "\n// FIRST_END"
    second = "// SECOND\n" + "y" * 1500 + "\n// SECOND_END"
    write(tmp_path, "a.js", first)
    write(tmp_path, "b.js", second)
    context = ProjectContext(tmp_path, max_context_chars=2200)
    result = context.build(["b.js", "a.js"])
    assert len(result) <= 2200
    assert second in result
    assert "=== ARQUIVO: a.js ===" not in result
    assert "// FIRST" not in result


class RecordingAdapter:
    def generate(self, prompt):
        self.prompt = prompt
        return json.dumps({
            "objective": "Criar resultado",
            "changes": [{"type": "create", "path": "result.py", "content": "OK = True\n"}],
            "tests": [], "risks": [],
        })


def test_pipeline_delivers_large_backend_and_frontend_sources_without_truncation(tmp_path):
    app = 'fetch("/health");\n' + "// pad\n" * 4000 + "// APP_END\n"
    api = 'route = "/health"\n' + "# pad\n" * 4000 + "API_END = True\n"
    tests = '# /health\n' + "# pad\n" * 17000 + "TEST_END = True\n"
    write(tmp_path, "web/app.js", app)
    write(tmp_path, "api.py", api)
    write(tmp_path, "tests/test_api.py", tests)
    write(tmp_path, "web/index.html", "<h2>Estado do serviço</h2>")
    adapter = RecordingAdapter()
    pipeline = DevAgentPipeline(tmp_path, ai_adapter=adapter)
    pipeline.process('Acrescente ai_provider em GET /health e no painel “Estado do serviço”.')
    assert app in adapter.prompt
    assert api in adapter.prompt
    assert tests in adapter.prompt
    assert "<h2>Estado do serviço</h2>" in adapter.prompt
    assert "=== CONTEXTO TRUNCADO ===" not in adapter.prompt
    assert pipeline.context.max_context_chars == AIPlanner.MAX_CONTEXT_CHARS
    assert not (tmp_path / "result.py").exists()


def test_pipeline_keeps_all_explicit_modify_targets_in_same_prompt(tmp_path):
    write(tmp_path, "web/app.js", "// FIRST_ORIGINAL\n" + "// pad\n" * 4000)
    write(tmp_path, "web/index.html", "<h2>SECOND_ORIGINAL</h2>")
    adapter = RecordingAdapter()
    pipeline = DevAgentPipeline(tmp_path, ai_adapter=adapter)
    # Observe the prompt without imposing a different plan on the validators.
    adapter.generate = lambda prompt: setattr(adapter, "prompt", prompt) or json.dumps({
        "objective": "Atualizar interface", "changes": [
            {"type": "modify", "path": "web/app.js", "content": "// updated\n"},
            {"type": "modify", "path": "web/index.html", "content": "<h2>updated</h2>"},
        ], "tests": [], "risks": [],
    })
    pipeline.process("Modifique web/app.js e web/index.html preservando o restante.")
    assert "FIRST_ORIGINAL" in adapter.prompt
    assert "SECOND_ORIGINAL" in adapter.prompt
    assert (tmp_path / "web/index.html").read_text() == "<h2>SECOND_ORIGINAL</h2>"
