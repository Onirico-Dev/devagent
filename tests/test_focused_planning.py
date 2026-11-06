"""Focused snapshots reduce input while preserving the approval contract."""
import json
from pathlib import Path

import pytest

from agent import DevAgent
from core.context.project_context import ProjectContext
from core.gateway import DevAgentGateway
from core.pipeline import DevAgentPipeline
from core.planner.local_edits import content_hash


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    return path


class EditAdapter:
    def __init__(self, path="app.py", old="VALUE = 1", new="VALUE = 2"):
        self.path, self.old, self.new = path, old, new

    def generate(self, prompt):
        self.prompt = prompt
        manifest = json.loads(prompt.rsplit("MANIFESTO SHA256 DAS FONTES UTF-8:\n", 1)[1])
        return json.dumps({"objective": "Atualizar valor", "changes": [
            {"type": "modify", "path": self.path, "base_sha256": manifest[self.path],
             "edits": [{"old": self.old, "new": self.new}], "reason": "Atualizar valor"}
        ], "tests": [], "risks": []})


def test_focused_context_returns_only_included_snapshots_and_preserves_crlf(tmp_path):
    original = "# ação\r\nVALUE = 1\r\nTAIL = True\r\n"
    write(tmp_path, "app.py", original)
    write(tmp_path, "other.py", "OTHER_CONTEXT_SENTINEL = True\n")
    context = ProjectContext(tmp_path)
    snapshots = {"stale.py": "old"}
    result = context.build(["app.py"], focused=True, snapshots=snapshots)
    assert original in result
    assert "OTHER_CONTEXT_SENTINEL" not in result
    assert snapshots == {"app.py": original}
    assert context.read_file("app.py") == original.replace("\r\n", "\n")


def test_budget_omissions_and_binary_placeholders_are_not_editable_snapshots(tmp_path):
    write(tmp_path, "a.py", "VALUE = 1\n")
    write(tmp_path, "large.py", "# pad\n" * 100)
    (tmp_path / "binary.py").write_bytes(b"\xff")
    context = ProjectContext(tmp_path, max_context_chars=500)
    snapshots = {}
    result = context.build(["a.py", "large.py", "binary.py"], focused=True, snapshots=snapshots)
    assert snapshots == {"a.py": "VALUE = 1\n"}
    assert "=== ARQUIVO: large.py ===" not in result


def test_empty_or_missing_focus_keeps_general_context_available(tmp_path):
    write(tmp_path, "app.py", "VALUE = 1\n")
    context = ProjectContext(tmp_path)
    snapshots = {}
    assert "VALUE = 1" in context.build(["missing.py"], focused=True, snapshots=snapshots)
    assert snapshots == {"app.py": "VALUE = 1\n"}
    assert context.select_explicit_paths("Crie missing.py") == []


def test_explicit_pipeline_does_not_read_unrelated_or_private_sources(tmp_path, monkeypatch):
    original = "VALUE = 1\nPRESERVE = True\n"
    write(tmp_path, "app.py", original)
    forbidden = [write(tmp_path, name, "PRIVATE_SENTINEL /health") for name in
                 ("unrelated.py", "secrets/private.json", "backups/old.py", ".ssh/key.py", ".env.staging.json")]
    blocked = {path.resolve() for path in forbidden}
    original_open = Path.open

    def guard(path, *args, **kwargs):
        assert path.resolve() not in blocked, "Leitura de conteúdo fora do foco"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    adapter = EditAdapter()
    plan = DevAgentPipeline(tmp_path, ai_adapter=adapter).process("Modifique app.py preservando o restante.")
    assert plan.changes[0].content == original.replace("VALUE = 1", "VALUE = 2")
    assert "PRIVATE_SENTINEL" not in adapter.prompt
    assert content_hash(original) in adapter.prompt
    assert (tmp_path / "app.py").read_text() == original


def test_named_private_alias_never_enters_context_or_manifest(tmp_path, monkeypatch):
    write(tmp_path, "app.py", "VALUE = 1\n")
    private = write(tmp_path, "secrets/private.py", "PRIVATE_ALIAS = True\n")
    (tmp_path / "alias").symlink_to(tmp_path / "secrets", target_is_directory=True)
    adapter = EditAdapter()
    DevAgentPipeline(tmp_path, ai_adapter=adapter).process("Modifique app.py; preserve alias/private.py.")
    assert "PRIVATE_ALIAS" not in adapter.prompt
    manifest = json.loads(adapter.prompt.rsplit("MANIFESTO SHA256 DAS FONTES UTF-8:\n", 1)[1])
    assert manifest == {"app.py": content_hash("VALUE = 1\n")}
    assert private.exists()


def test_semantic_selection_without_explicit_paths_still_provides_matching_files(tmp_path):
    write(tmp_path, "app.py", 'route = "/health"\nVALUE = 1\n')
    write(tmp_path, "web/app.js", 'fetch("/health")\n')
    write(tmp_path, "other.py", "OTHER_SENTINEL = True\n")
    adapter = EditAdapter()
    DevAgentPipeline(tmp_path, ai_adapter=adapter).process("Atualize GET /health.")
    assert 'fetch("/health")' in adapter.prompt
    assert "OTHER_SENTINEL" not in adapter.prompt


def test_legacy_create_response_without_matching_sources_remains_valid(tmp_path):
    write(tmp_path, "other.py", "EXISTING = True\n")

    class Adapter:
        def generate(self, prompt):
            assert "EXISTING = True" in prompt
            return json.dumps({"objective": "Criar novo", "changes": [
                {"type": "create", "path": "new.py", "content": "NEW = True\n"}
            ], "tests": [], "risks": []})

    plan = DevAgentPipeline(tmp_path, ai_adapter=Adapter()).process("Crie new.py")
    assert plan.changes[0].content == "NEW = True\n"
    assert not (tmp_path / "new.py").exists()


def test_large_source_uses_small_edit_response_without_truncation_or_unrelated_input(tmp_path):
    original = "# pad\n" * 8000 + "VALUE = 1\nTAIL = 'preservado'\n"
    write(tmp_path, "app.py", original)
    write(tmp_path, "unrelated.py", "# OUTSIDE_FOCUS\n" * 8000)

    class Adapter(EditAdapter):
        def generate(self, prompt):
            response = super().generate(prompt)
            assert original in prompt
            assert "OUTSIDE_FOCUS" not in prompt
            assert len(prompt) < len(original) + 5000
            assert len(response) < len(original) // 100
            return response

    plan = DevAgentPipeline(tmp_path, ai_adapter=Adapter()).process("Modifique app.py preservando o restante.")
    assert plan.changes[0].content == original.replace("VALUE = 1", "VALUE = 2")
    assert (tmp_path / "app.py").read_text() == original


@pytest.mark.parametrize("legacy", [False, True])
def test_changes_during_generation_are_rejected_before_task_registration(tmp_path, legacy):
    source = write(tmp_path, "app.py", "VALUE = 1\n")

    class Adapter(EditAdapter):
        def generate(self, prompt):
            result = super().generate(prompt)
            source.write_text("VALUE = 3\n")
            if legacy:
                data = json.loads(result)
                data["changes"][0] = {"type": "modify", "path": "app.py", "content": "VALUE = 2\n"}
                return json.dumps(data)
            return result

    gateway = DevAgentGateway(DevAgent(tmp_path, ai_adapter=Adapter()), tmp_path)
    with pytest.raises(ValueError, match="mudou durante o planejamento"):
        gateway.create_task("Modifique app.py")
    assert source.read_text() == "VALUE = 3\n"
    assert gateway.list_tasks() == []


def test_source_replaced_by_private_alias_during_generation_is_blocked(tmp_path, monkeypatch):
    source = write(tmp_path, "app.py", "VALUE = 1\n")
    private = write(tmp_path, "secrets/private.py", "PRIVATE_SENTINEL = True\n")
    original_open = Path.open

    def guard(path, *args, **kwargs):
        assert path.resolve() != private.resolve(), "Arquivo privado foi lido"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)

    class Adapter(EditAdapter):
        def generate(self, prompt):
            result = super().generate(prompt)
            source.unlink()
            source.symlink_to(private)
            return result

    with pytest.raises(ValueError, match="Arquivo protegido"):
        DevAgentPipeline(tmp_path, ai_adapter=Adapter()).process("Modifique app.py")


def test_gateway_reviews_and_commits_complete_reconstructed_file(isolated_project, monkeypatch):
    root = isolated_project
    original = "# cabeçalho\nVALUE = 1\nTAIL = True\n"
    source = write(root, "app.py", original)
    gateway = DevAgentGateway(DevAgent(root, ai_adapter=EditAdapter()), root)
    gateway.git._run_git("add", "--", "app.py")
    gateway.git._run_git("commit", "-m", "fixture original")
    validated = []
    original_validate = gateway.security.validate_content

    def capture(content):
        validated.append(content)
        return original_validate(content)

    monkeypatch.setattr(gateway.security, "validate_content", capture)
    task = gateway.create_task("Modifique app.py preservando o restante.")
    assert task["status"] == "pending"
    expected = original.replace("VALUE = 1", "VALUE = 2")
    approved_change = task["plan"]["changes"][0]
    assert approved_change["content"] == expected
    assert "edits" not in approved_change and "base_sha256" not in approved_change
    assert validated == [expected]
    assert source.read_text() == original
    result = gateway.approve(task["approval_id"])
    assert result["status"] == "committed"
    assert result["repair_attempts"] == 0
    assert source.read_text() == expected
    assert result["git"]["files"] == ["app.py"]


def test_gateway_still_rejects_reconstructed_content_when_policy_refuses_it(tmp_path, monkeypatch):
    source = write(tmp_path, "app.py", "VALUE = 1\n")
    gateway = DevAgentGateway(DevAgent(tmp_path, ai_adapter=EditAdapter()), tmp_path)

    def refuse(content):
        assert content == "VALUE = 2\n"
        raise PermissionError("Política recusou o conteúdo reconstruído")

    monkeypatch.setattr(gateway.security, "validate_content", refuse)
    with pytest.raises(PermissionError, match="Política recusou"):
        gateway.create_task("Modifique app.py")
    assert source.read_text() == "VALUE = 1\n"
    assert gateway.list_tasks() == []
