import pytest

from core.security import SecurityPolicy


@pytest.mark.parametrize("extension", ["html", "js", "css"])
def test_frontend_files_inside_project_are_allowed(tmp_path, extension):
    assert SecurityPolicy(tmp_path).validate_path(f"web/view.{extension}")


@pytest.mark.parametrize("extension", ["html", "js", "css"])
@pytest.mark.parametrize("directory", [".git", ".ssh", ".env", "secrets"])
def test_frontend_extensions_do_not_unlock_protected_paths(tmp_path, extension, directory):
    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        SecurityPolicy(tmp_path).validate_path(f"{directory}/view.{extension}")


@pytest.mark.parametrize("extension", ["html", "js", "css"])
def test_frontend_paths_cannot_escape_project(tmp_path, extension):
    with pytest.raises(PermissionError, match="fora do projeto"):
        SecurityPolicy(tmp_path).validate_path(f"../outside.{extension}")


@pytest.mark.parametrize("extension", ["html", "js", "css"])
def test_frontend_symlink_escape_is_blocked(tmp_path, extension):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.{extension}"
    outside.write_text("outside")
    (tmp_path / f"link.{extension}").symlink_to(outside)
    with pytest.raises(PermissionError, match="fora do projeto"):
        SecurityPolicy(tmp_path).validate_path(f"link.{extension}")


@pytest.mark.parametrize("content", ["eval('1')", "exec('1')", "import subprocess", "rm -rf /tmp/data"])
def test_frontend_support_preserves_content_risk_rejection(tmp_path, content):
    with pytest.raises(PermissionError, match="alto risco"):
        SecurityPolicy(tmp_path).validate_content(content)


@pytest.mark.parametrize("extension", ["sh", "exe", "bat", "pem", "png"])
def test_unrelated_extensions_remain_blocked(tmp_path, extension):
    with pytest.raises(PermissionError, match="Extensão não permitida"):
        SecurityPolicy(tmp_path).validate_path(f"file.{extension}")
