"""Protege dados privados e backups antes de montar o prompt do planejador."""
import json
from pathlib import Path

import pytest

from core.context.project_context import ProjectContext
from core.pipeline import DevAgentPipeline


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def forbid_reads(monkeypatch, *paths):
    protected = {path.resolve() for path in paths}
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.resolve() not in protected, "Tentativa de ler arquivo protegido"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)


@pytest.mark.parametrize("folder", ["secrets", "backups", ".ssh", ".env", ".env.staging", "nested/secrets"])
def test_protected_directories_are_not_read_or_selected(tmp_path, monkeypatch, folder):
    relative = folder + "/private.json"
    private = write(tmp_path, relative, '{"route":"/health","token":"PRIVATE_SENTINEL"}')
    write(tmp_path, "app.py", 'route = "/health"\n')
    forbid_reads(monkeypatch, private)
    context = ProjectContext(tmp_path)
    assert context.list_files() == [Path("app.py")]
    assert context.select_relevant_paths(f"Altere {relative} para GET /health") == ["app.py"]
    result = context.build([relative, "app.py"])
    assert "PRIVATE_SENTINEL" not in result
    assert "=== ARQUIVO: app.py ===" in result
    assert "=== ARQUIVO: " + relative + " ===" not in result
    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(relative)


@pytest.mark.parametrize("relative", [".env", ".env.local", ".env.staging.json", "nested/.env.test.yaml"])
def test_environment_files_are_blocked_even_when_the_extension_is_allowed(tmp_path, monkeypatch, relative):
    private = write(tmp_path, relative, "ENV_SENTINEL /health")
    write(tmp_path, "web/app.js", 'fetch("/health");\n')
    forbid_reads(monkeypatch, private)
    context = ProjectContext(tmp_path)
    assert context.select_relevant_paths(f"GET /health em {relative}") == ["web/app.js"]
    assert "ENV_SENTINEL" not in context.build([relative])
    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(relative)


@pytest.mark.parametrize("folder", ["secrets", "backups"])
def test_alias_to_protected_directory_cannot_expose_its_contents(tmp_path, monkeypatch, folder):
    private = write(tmp_path, folder + "/private.json", "ALIAS_SENTINEL /health")
    (tmp_path / "alias").symlink_to(tmp_path / folder, target_is_directory=True)
    forbid_reads(monkeypatch, private)
    context = ProjectContext(tmp_path)
    assert context.select_relevant_paths("GET /health em alias/private.json") == []
    assert "ALIAS_SENTINEL" not in context.build(["alias/private.json"])
    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file("alias/private.json")


@pytest.mark.parametrize("folder", [".ssh", "secrets"])
def test_protected_path_remains_blocked_when_its_directory_is_an_alias(tmp_path, folder):
    write(tmp_path, "src/public.py", "PUBLIC = True\n")
    (tmp_path / folder).symlink_to(tmp_path / "src", target_is_directory=True)
    context = ProjectContext(tmp_path)
    assert folder + "/public.py" not in context.select_relevant_paths(folder + "/public.py")
    result = context.build([folder + "/public.py"])
    assert "=== ARQUIVO: " + folder + "/public.py ===" not in result
    assert "=== ARQUIVO: src/public.py ===" in result
    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(folder + "/public.py")


@pytest.mark.parametrize("destination", ["protected", "outside"])
def test_source_replaced_after_inventory_is_validated_before_read(tmp_path, monkeypatch, destination):
    public = write(tmp_path, "app.py", "PUBLIC = True\n")
    if destination == "protected":
        private = write(tmp_path, "secrets/private.py", "SWAP_SENTINEL = True\n")
        message = "Arquivo protegido"
    else:
        outside = tmp_path.parent / (tmp_path.name + "-outside")
        outside.mkdir()
        private = write(outside, "private.py", "SWAP_SENTINEL = True\n")
        message = "Caminho bloqueado"
    forbid_reads(monkeypatch, private)
    context = ProjectContext(tmp_path)

    def inventory():
        public.unlink()
        public.symlink_to(private)
        return [Path("app.py")]

    monkeypatch.setattr(context, "list_files", inventory)
    with pytest.raises(ValueError, match=message):
        context.build(["app.py"])


def test_pipeline_prompt_contains_public_source_and_no_private_or_backup_data(tmp_path, monkeypatch):
    public = 'route = "/health"\nPUBLIC_SOURCE = True\n'
    write(tmp_path, "app.py", public)
    files = [
        write(tmp_path, folder + "/fixture.json", '{"route":"/health","token":"PROMPT_PRIVATE_SENTINEL"}')
        for folder in ("secrets", "backups", ".ssh", ".env.staging")
    ]
    files.append(write(tmp_path, ".env.staging.json", "PROMPT_PRIVATE_SENTINEL /health"))
    forbid_reads(monkeypatch, *files)

    class RecordingAdapter:
        prompt = ""

        def generate(self, prompt):
            self.prompt = prompt
            return json.dumps({
                "objective": "Criar resultado", "changes": [
                    {"type": "create", "path": "result.py", "content": "VALUE = 1\n"},
                ], "tests": [], "risks": [],
            })

    adapter = RecordingAdapter()
    pipeline = DevAgentPipeline(str(tmp_path), ai_adapter=adapter)
    pipeline.process("Crie result.py considerando GET /health.")
    assert public in adapter.prompt
    assert "PROMPT_PRIVATE_SENTINEL" not in adapter.prompt
    assert not (tmp_path / "result.py").exists()
