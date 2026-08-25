import pytest

from core.security import SecurityPolicy


def test_security_accepts_file_inside_project(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_path("app.py") is True


def test_security_rejects_prefix_collision_outside_project(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "project_evil"

    project.mkdir()
    outside.mkdir()

    policy = SecurityPolicy(project)

    with pytest.raises(PermissionError, match="fora do projeto"):
        policy.validate_path("../project_evil/app.py")


def test_security_rejects_blocked_directory(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        policy.validate_path(".git/config")


def test_security_rejects_blocked_env_file(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        policy.validate_path(".env")


def test_security_rejects_disallowed_extension(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Extensão não permitida"):
        policy.validate_path("payload.sh")


def test_security_rejects_empty_path(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho inválido"):
        policy.validate_path("")


def test_security_rejects_directory_symlink_escape(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"

    project.mkdir()
    outside.mkdir()

    (outside / "evil.py").write_text("print('evil')", encoding="utf-8")
    (project / "link").symlink_to(outside, target_is_directory=True)

    policy = SecurityPolicy(project)

    with pytest.raises(PermissionError, match="fora do projeto"):
        policy.validate_path("link/evil.py")


def test_security_rejects_file_symlink_escape(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside.py"

    project.mkdir()
    outside.write_text("print('evil')", encoding="utf-8")
    (project / "link.py").symlink_to(outside)

    policy = SecurityPolicy(project)

    with pytest.raises(PermissionError, match="fora do projeto"):
        policy.validate_path("link.py")
