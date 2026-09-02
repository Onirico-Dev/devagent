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

from pathlib import Path

import pytest

from core.security import SecurityPolicy


def test_validate_path_accepts_allowed_file_inside_project(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_path("app.py") is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        None,
        123,
    ],
)
def test_validate_path_rejects_invalid_path_values(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho inválido"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/outside.py",
    ],
)
def test_validate_path_rejects_paths_outside_project(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho fora do projeto"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".git/config.py",
        ".ssh/config.py",
        ".env/config.py",
        "secrets/token.py",
    ],
)
def test_validate_path_rejects_blocked_path_components(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "app.exe",
        "script.sh",
        "binary",
        "image.png",
    ],
)
def test_validate_path_rejects_unsupported_extensions(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Extensão não permitida"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "content",
    [
        "rm -rf /tmp/test",
        "import subprocess",
        "os.system('echo test')",
        "os.popen('echo test')",
        "shutil.rmtree('tmp')",
        "eval('1 + 1')",
        "exec('print(1)')",
    ],
)
def test_assess_content_risk_detects_high_risk_patterns(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "alto"


@pytest.mark.parametrize(
    "content",
    [
        "print('hello')",
        "def main():\n    return 1",
        '{"name": "devagent"}',
        "",
    ],
)
def test_assess_content_risk_accepts_low_risk_content(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "baixo"


@pytest.mark.parametrize(
    "content",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_assess_content_risk_rejects_non_string_as_high_risk(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "alto"


def test_validate_content_accepts_low_risk_content(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_content(
        "print('seguro')"
    ) is True


def test_validate_content_rejects_high_risk_content(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(
        PermissionError,
        match="Conteúdo de alto risco não autorizado",
    ):
        policy.validate_content(
            "import subprocess\n"
        )


def test_validate_path_rejects_symlink_to_outside_project(tmp_path):
    policy = SecurityPolicy(tmp_path)

    outside = tmp_path.parent / "outside_security_target.py"
    outside.write_text(
        "print('outside')\n",
        encoding="utf-8",
    )

    link = tmp_path / "link.py"

    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink não suportado neste ambiente.")

    with pytest.raises(
        PermissionError,
        match="Caminho fora do projeto",
    ):
        policy.validate_path("link.py")


def test_validate_path_accepts_nested_allowed_path(tmp_path):
    policy = SecurityPolicy(tmp_path)

    nested = tmp_path / "src" / "module.py"
    nested.parent.mkdir()

    assert policy.validate_path(
        "src/module.py"
    ) is True

from pathlib import Path

import pytest

from core.security import SecurityPolicy


def test_validate_path_accepts_allowed_file_inside_project(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_path("app.py") is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        None,
        123,
    ],
)
def test_validate_path_rejects_invalid_path_values(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho inválido"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/outside.py",
    ],
)
def test_validate_path_rejects_paths_outside_project(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho fora do projeto"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".git/config.py",
        ".ssh/config.py",
        ".env/config.py",
        "secrets/token.py",
    ],
)
def test_validate_path_rejects_blocked_path_components(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "app.exe",
        "script.sh",
        "binary",
        "image.png",
    ],
)
def test_validate_path_rejects_unsupported_extensions(tmp_path, path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="Extensão não permitida"):
        policy.validate_path(path)


@pytest.mark.parametrize(
    "content",
    [
        "rm -rf /tmp/test",
        "import subprocess",
        "os.system('echo test')",
        "os.popen('echo test')",
        "shutil.rmtree('tmp')",
        "eval('1 + 1')",
        "exec('print(1)')",
    ],
)
def test_assess_content_risk_detects_high_risk_patterns(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "alto"


@pytest.mark.parametrize(
    "content",
    [
        "print('hello')",
        "def main():\n    return 1",
        '{"name": "devagent"}',
        "",
    ],
)
def test_assess_content_risk_accepts_low_risk_content(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "baixo"


@pytest.mark.parametrize(
    "content",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_assess_content_risk_rejects_non_string_as_high_risk(
    tmp_path,
    content,
):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(content) == "alto"


def test_validate_content_accepts_low_risk_content(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_content(
        "print('seguro')"
    ) is True


def test_validate_content_rejects_high_risk_content(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(
        PermissionError,
        match="Conteúdo de alto risco não autorizado",
    ):
        policy.validate_content(
            "import subprocess\n"
        )


def test_validate_path_rejects_symlink_to_outside_project(tmp_path):
    policy = SecurityPolicy(tmp_path)

    outside = tmp_path.parent / "outside_security_target.py"
    outside.write_text(
        "print('outside')\n",
        encoding="utf-8",
    )

    link = tmp_path / "link.py"

    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink não suportado neste ambiente.")

    with pytest.raises(
        PermissionError,
        match="Caminho fora do projeto",
    ):
        policy.validate_path("link.py")


def test_validate_path_accepts_nested_allowed_path(tmp_path):
    policy = SecurityPolicy(tmp_path)

    nested = tmp_path / "src" / "module.py"
    nested.parent.mkdir()

    assert policy.validate_path(
        "src/module.py"
    ) is True
