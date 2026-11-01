"""Testes da separação entre artefatos e workspace de validação."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_release.py"
)

SPEC = importlib.util.spec_from_file_location(
    "devagent_release_validator",
    SCRIPT,
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_custom_artifact_directory_is_separate_from_workspace(tmp_path):
    output = tmp_path / "release-output"

    wheel_dir = VALIDATOR.configure_artifact_dirs(output)

    assert VALIDATOR.ARTIFACT_DIR == output.resolve()
    assert wheel_dir == output.resolve() / "wheel"
    assert wheel_dir.is_dir()
    assert VALIDATOR.WORK_DIR.is_dir()
    assert VALIDATOR.WORK_DIR != VALIDATOR.ARTIFACT_DIR
    assert not (VALIDATOR.ARTIFACT_DIR / "venv").exists()
    assert VALIDATOR.WORK_DIR.name.startswith("devagent-validation-")


def test_default_artifact_directory_remains_temporary(
    tmp_path, monkeypatch
):
    artifact_path = tmp_path / "temporary-artifacts"
    workspace_path = tmp_path / "temporary-workspace"
    paths = iter((artifact_path, workspace_path))

    def fake_mkdtemp(**kwargs):
        path = next(paths)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    monkeypatch.setattr(
        VALIDATOR.tempfile,
        "mkdtemp",
        fake_mkdtemp,
    )

    wheel_dir = VALIDATOR.configure_artifact_dirs()

    assert VALIDATOR.ARTIFACT_DIR == artifact_path.resolve()
    assert VALIDATOR.WORK_DIR == workspace_path.resolve()
    assert wheel_dir.is_dir()
    assert VALIDATOR.ARTIFACT_DIR != VALIDATOR.WORK_DIR


def test_custom_artifact_directory_creates_missing_parents(tmp_path):
    output = tmp_path / "nested" / "release" / "artifacts"

    wheel_dir = VALIDATOR.configure_artifact_dirs(output)

    assert wheel_dir.is_dir()
    assert VALIDATOR.ARTIFACT_DIR == output.resolve()


def test_existing_wheel_is_rejected_to_prevent_stale_artifacts(tmp_path):
    output = tmp_path / "release-output"
    wheel_dir = output / "wheel"
    wheel_dir.mkdir(parents=True)
    stale_wheel = wheel_dir / "devagent-0.6.8-py3-none-any.whl"
    stale_wheel.write_bytes(b"stale")

    with pytest.raises(AssertionError, match="wheels antigos"):
        VALIDATOR.configure_artifact_dirs(output)
