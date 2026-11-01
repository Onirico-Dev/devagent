import importlib.util
import io
import zipfile
import zlib
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "install_release.py"
)
SPEC = importlib.util.spec_from_file_location(
    "devagent_install_release_metadata",
    SCRIPT,
)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def make_wheel(
    path,
    *,
    name="devagent",
    version="0.6.8",
    dist_info="devagent-0.6.8.dist-info",
):
    metadata = (
        f"Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
    )
    metadata_path = f"{dist_info}/METADATA"

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(metadata_path, metadata)

    return path

def test_validate_wheel_metadata_accepts_devagent_wheel(tmp_path):
    wheel = make_wheel(
        tmp_path / "devagent-0.6.8-py3-none-any.whl"
    )

    INSTALLER.validate_wheel_metadata(wheel, "0.6.8")


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("other-package", "0.6.8"),
        ("devagent", "9.9.9"),
    ],
)
def test_validate_wheel_metadata_rejects_wrong_identity(
    tmp_path,
    name,
    version,
):
    wheel = make_wheel(
        tmp_path / "devagent-0.6.8-py3-none-any.whl",
        name=name,
        version=version,
    )

    with pytest.raises(ValueError):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")



@pytest.mark.parametrize(
    "filename",
    [
        "invalid.whl",
        "other-0.6.8-py3-none-any.whl",
        "devagent-9.9.9-py3-none-any.whl",
        "devagent-0.6.8-invalid.whl",
    ],
)
def test_validate_wheel_metadata_rejects_invalid_wheel_filename(
    tmp_path,
    filename,
):
    wheel = make_wheel(tmp_path / filename)

    with pytest.raises(ValueError):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")


def test_validate_wheel_metadata_rejects_mismatched_dist_info(tmp_path):
    wheel = make_wheel(
        tmp_path / "devagent-0.6.8-py3-none-any.whl",
        dist_info="other-0.6.8.dist-info",
    )

    with pytest.raises(ValueError):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")

def test_validate_wheel_metadata_rejects_corrupt_zip(tmp_path):
    wheel = tmp_path / "corrupt.whl"
    wheel.write_bytes(b"not a zip archive")

    with pytest.raises(ValueError):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")


def test_validate_wheel_metadata_handles_zlib_corruption(tmp_path, monkeypatch):
    wheel = make_wheel(
        tmp_path / "devagent-0.6.8-py3-none-any.whl"
    )

    def raise_zlib_error(self):
        raise zlib.error("compressed wheel member is corrupted")

    monkeypatch.setattr(zipfile.ZipFile, "testzip", raise_zlib_error)

    with pytest.raises(ValueError, match="Wheel não é um ZIP válido"):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")


def test_validate_wheel_metadata_rejects_missing_metadata(tmp_path):
    wheel = tmp_path / "missing.whl"

    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("devagent/module.py", "VALUE = 1")

    with pytest.raises(ValueError):
        INSTALLER.validate_wheel_metadata(wheel, "0.6.8")


def test_validate_installed_environment_checks_isolated_imports(
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    python = tmp_path / "bin" / "python"
    executable = tmp_path / "bin" / "devagent"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o700)
    executable.write_text("", encoding="utf-8")

    calls = []

    def fake_run(command, capture=True):
        calls.append(command)
        if command[-1] == "0.6.8":
            return SimpleNamespace(stdout="0.6.8\n")
        if command[-1] == "--version":
            return SimpleNamespace(stdout="0.6.8\n")
        if command[-1] == "--help":
            return SimpleNamespace(stdout="DevAgent\nUso:\n")
        raise AssertionError(f"Comando inesperado: {command}")

    monkeypatch.setattr(INSTALLER, "run", fake_run)

    result = INSTALLER.validate_installed_environment(
        python,
        "0.6.8",
    )

    assert result == "0.6.8"
    assert len(calls) == 3
    assert calls[0][1] == "-I"
    assert calls[1][-1] == "--version"
    assert calls[2][-1] == "--help"


def test_validate_installed_environment_rejects_missing_python(tmp_path):
    with pytest.raises(RuntimeError):
        INSTALLER.validate_installed_environment(
            tmp_path / "missing-python",
            "0.6.8",
        )


def test_validate_installed_environment_accepts_python_symlink(
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    target = tmp_path / "python-base"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    target.chmod(0o700)

    python = tmp_path / "bin" / "python"
    executable = tmp_path / "bin" / "devagent"
    python.parent.mkdir()
    python.symlink_to(target)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    calls = []

    def fake_run(command, capture=True):
        calls.append(command)
        if command[-1] == "0.6.8":
            return SimpleNamespace(stdout="0.6.8\n")
        if command[-1] == "--version":
            return SimpleNamespace(stdout="0.6.8\n")
        if command[-1] == "--help":
            return SimpleNamespace(stdout="DevAgent\nUso:\n")
        raise AssertionError(f"Comando inesperado: {command}")

    monkeypatch.setattr(INSTALLER, "run", fake_run)

    assert INSTALLER.validate_installed_environment(
        python,
        "0.6.8",
    ) == "0.6.8"

    assert len(calls) == 3
    assert calls[0][0] == str(python)


def test_validate_installed_environment_rejects_broken_python_symlink(
    tmp_path,
):
    python = tmp_path / "bin" / "python"
    python.parent.mkdir()
    python.symlink_to(tmp_path / "missing-python")

    with pytest.raises(RuntimeError):
        INSTALLER.validate_installed_environment(
            python,
            "0.6.8",
        )


def test_cleanup_destination_removes_partial_directory(tmp_path):
    destination = tmp_path / "partial-install"
    destination.mkdir()
    (destination / "partial.txt").write_text("partial", encoding="utf-8")

    INSTALLER.cleanup_destination(destination)

    assert not destination.exists()


def test_cleanup_destination_does_not_follow_symlink(tmp_path):
    target = tmp_path / "preserved"
    target.mkdir()
    (target / "important.txt").write_text("preserve", encoding="utf-8")

    link = tmp_path / "partial-link"
    link.symlink_to(target)

    INSTALLER.cleanup_destination(link)

    assert link.is_symlink()
    assert (target / "important.txt").read_text(encoding="utf-8") == "preserve"
