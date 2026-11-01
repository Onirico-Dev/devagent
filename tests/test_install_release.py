"""Testes de contrato do instalador de releases do DevAgent."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "install_release.py"
)

SPEC = importlib.util.spec_from_file_location(
    "devagent_install_release",
    SCRIPT,
)

if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Não foi possível carregar install_release.py")

INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


COMMIT = "eb8df26c970014abe5acceebea6fda90b205a73f"


def make_run(
    *,
    sha=COMMIT,
    status="completed",
    conclusion="success",
    branch="master",
    workflow="CI",
    event="push",
    created="2026-11-01T13:38:13Z",
    database_id=100,
):
    return {
        "databaseId": database_id,
        "headSha": sha,
        "status": status,
        "conclusion": conclusion,
        "headBranch": branch,
        "workflowName": workflow,
        "event": event,
        "createdAt": created,
    }


def make_artifact(tmp_path, *, commit=COMMIT, wheel_content=b"valid wheel"):
    artifact_dir = tmp_path / "artifact"
    wheel_dir = artifact_dir / "wheel"
    wheel_dir.mkdir(parents=True)

    wheel = wheel_dir / "devagent-0.6.8-py3-none-any.whl"
    wheel.write_bytes(wheel_content)

    report = {
        "overall": "PASS",
        "commit": commit,
        "version": "0.6.8",
        "wheel": "wheel/devagent-0.6.8-py3-none-any.whl",
        "wheel_size": wheel.stat().st_size,
        "sha256": hashlib.sha256(wheel_content).hexdigest(),
    }

    (artifact_dir / "release-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    return artifact_dir, wheel


def test_select_run_accepts_latest_successful_master_ci():
    runs = [
        make_run(
            sha="a" * 40,
            created="2026-10-31T10:00:00Z",
        ),
        make_run(
            sha=COMMIT,
            created="2026-11-01T13:38:13Z",
        ),
    ]

    selected = INSTALLER.select_run(runs)

    assert selected["headSha"] == COMMIT


@pytest.mark.parametrize(
    "run",
    [
        make_run(status="in_progress", conclusion=None),
        make_run(conclusion="failure"),
        make_run(branch="feature/test"),
        make_run(workflow="Other workflow"),
        make_run(event="pull_request"),
    ],
)
def test_select_run_rejects_invalid_runs(run):
    with pytest.raises(ValueError):
        INSTALLER.select_run([run])


@pytest.mark.parametrize(
    "overrides",
    [
        {"databaseId": None},
        {"databaseId": 0},
        {"databaseId": -1},
        {"databaseId": True},
        {"databaseId": "123"},
        {"createdAt": None},
        {"createdAt": ""},
        {"createdAt": "data-invalida"},
        {"createdAt": "2026-11-01T13:38:13"},
    ],
)
def test_select_run_ignores_invalid_identity_or_timestamp(overrides):
    invalid = make_run()
    invalid.update(overrides)

    with pytest.raises(ValueError):
        INSTALLER.select_run([invalid])


def test_select_run_ignores_invalid_newer_run_and_selects_valid_older():
    valid = make_run(
        sha=COMMIT,
        created="2026-10-31T10:00:00Z",
        database_id=101,
    )
    invalid_newer = make_run(
        sha="a" * 40,
        created="2026-11-01T13:38:13Z",
        database_id=True,
    )

    selected = INSTALLER.select_run([valid, invalid_newer])

    assert selected["databaseId"] == 101
    assert selected["headSha"] == COMMIT


def test_select_run_orders_timestamps_by_instant():
    earlier = make_run(
        sha="a" * 40,
        created="2026-11-01T09:30:00-03:00",
        database_id=101,
    )
    later = make_run(
        sha=COMMIT,
        created="2026-11-01T13:00:00Z",
        database_id=102,
    )

    selected = INSTALLER.select_run([earlier, later])

    assert selected["databaseId"] == 102


def test_select_run_matches_requested_commit():
    runs = [
        make_run(sha="a" * 40),
        make_run(sha=COMMIT),
    ]

    selected = INSTALLER.select_run(runs, commit=COMMIT)

    assert selected["headSha"] == COMMIT


def test_select_run_rejects_unknown_commit():
    with pytest.raises(ValueError):
        INSTALLER.select_run(
            [make_run()],
            commit="f" * 40,
        )


def test_validate_artifact_accepts_valid_report_and_wheel(tmp_path):
    artifact_dir, wheel = make_artifact(tmp_path)

    result = INSTALLER.validate_artifact(
        artifact_dir,
        expected_commit=COMMIT,
    )

    assert result == wheel.resolve()


@pytest.mark.parametrize(
    "field,value",
    [
        ("overall", "FAIL"),
        ("commit", "f" * 40),
        ("wheel_size", 999),
        ("sha256", "0" * 64),
        ("wheel", "../outside.whl"),
    ],
)
def test_validate_artifact_rejects_invalid_report(
    tmp_path,
    field,
    value,
):
    artifact_dir, _ = make_artifact(tmp_path)

    report_path = artifact_dir / "release-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report[field] = value
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises((ValueError, AssertionError)):
        INSTALLER.validate_artifact(
            artifact_dir,
            expected_commit=COMMIT,
        )


def test_validate_artifact_rejects_external_symlink(tmp_path):
    artifact_dir, _ = make_artifact(tmp_path)
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"external wheel")

    link = artifact_dir / "wheel" / "external.whl"
    link.symlink_to(outside)

    report_path = artifact_dir / "release-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["wheel"] = "wheel/external.whl"
    report["wheel_size"] = outside.stat().st_size
    report["sha256"] = hashlib.sha256(
        outside.read_bytes()
    ).hexdigest()
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises((ValueError, AssertionError)):
        INSTALLER.validate_artifact(
            artifact_dir,
            expected_commit=COMMIT,
        )


def test_validate_install_dir_accepts_new_destination(tmp_path):
    destination = tmp_path / "releases" / "0.6.8"

    result = INSTALLER.validate_install_dir(destination)

    assert result == destination.resolve()
    assert not destination.exists()


def test_validate_install_dir_rejects_existing_directory(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()

    with pytest.raises(ValueError):
        INSTALLER.validate_install_dir(destination)


def test_validate_install_dir_rejects_existing_file(tmp_path):
    destination = tmp_path / "existing"
    destination.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError):
        INSTALLER.validate_install_dir(destination)

    assert destination.read_text(encoding="utf-8") == "preserve"


def test_validate_install_dir_rejects_symlink(tmp_path):
    destination = tmp_path / "existing"
    target = tmp_path / "target"
    target.mkdir()
    destination.symlink_to(target)

    with pytest.raises(ValueError):
        INSTALLER.validate_install_dir(destination)


def _prepare_main_install(monkeypatch, tmp_path, failure=None):
    from types import SimpleNamespace

    artifact_dir, wheel = make_artifact(tmp_path)
    calls = []

    def fake_run(command, capture=True):
        calls.append((list(command), capture))

        if command[:3] == ["gh", "auth", "status"]:
            return SimpleNamespace(stdout="")

        if command[:3] == ["gh", "run", "list"]:
            selected_run = make_run()
            selected_run["databaseId"] = 12345
            return SimpleNamespace(stdout=json.dumps([selected_run]))

        if "-m" in command and "pip" in command:
            if failure == "pip":
                raise RuntimeError("falha simulada no pip")
            if failure == "pip_interrupt":
                raise KeyboardInterrupt()
            return SimpleNamespace(stdout="")

        return SimpleNamespace(stdout="")

    class FakeBuilder:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create(self, destination):
            if failure == "venv":
                raise RuntimeError("falha simulada na criação do venv")
            if failure == "venv_interrupt":
                raise KeyboardInterrupt()

            binary_dir = destination / "bin"
            binary_dir.mkdir(parents=True)
            python = binary_dir / "python"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o700)

    monkeypatch.setattr(INSTALLER, "run", fake_run)
    monkeypatch.setattr(
        INSTALLER,
        "find_artifact_root",
        lambda download_dir: artifact_dir,
    )
    monkeypatch.setattr(
        INSTALLER,
        "validate_artifact",
        lambda root, expected_commit: wheel,
    )
    monkeypatch.setattr(
        INSTALLER,
        "validate_wheel_metadata",
        lambda wheel_path, expected_version: None,
    )
    monkeypatch.setattr(INSTALLER.venv, "EnvBuilder", FakeBuilder)

    if failure == "validation":
        def fail_validation(python_executable, expected_version):
            raise RuntimeError("falha simulada na validação final")

        monkeypatch.setattr(
            INSTALLER,
            "validate_installed_environment",
            fail_validation,
        )
    else:
        monkeypatch.setattr(
            INSTALLER,
            "validate_installed_environment",
            lambda python_executable, expected_version: expected_version,
        )

    destination = tmp_path / "installations" / "devagent-test"
    return destination, calls


@pytest.mark.parametrize(
    "failure",
    ["venv", "pip", "validation"],
)
def test_main_removes_partial_installation_after_failure(
    monkeypatch,
    tmp_path,
    failure,
):
    destination, calls = _prepare_main_install(
        monkeypatch,
        tmp_path,
        failure=failure,
    )

    result = INSTALLER.main([
        "--latest",
        "--install-dir",
        str(destination),
    ])

    assert result == 1
    assert not destination.exists()
    assert destination.parent.is_dir()
    assert any(command[:3] == ["gh", "run", "list"] for command, _ in calls)


@pytest.mark.parametrize(
    "failure",
    ["venv_interrupt", "pip_interrupt"],
)
def test_main_cleans_partial_installation_after_keyboard_interrupt(
    monkeypatch,
    tmp_path,
    failure,
):
    destination, calls = _prepare_main_install(
        monkeypatch,
        tmp_path,
        failure=failure,
    )

    result = INSTALLER.main([
        "--latest",
        "--install-dir",
        str(destination),
    ])

    assert result == 130
    assert not destination.exists()
    assert destination.parent.is_dir()


def test_main_preserves_preexisting_installation(
    monkeypatch,
    tmp_path,
):
    calls = []
    destination = tmp_path / "existing-install"
    destination.mkdir()
    marker = destination / "important.txt"
    marker.write_text("preserve", encoding="utf-8")

    monkeypatch.setattr(
        INSTALLER,
        "run",
        lambda command, capture=True: calls.append(command),
    )

    result = INSTALLER.main([
        "--latest",
        "--install-dir",
        str(destination),
    ])

    assert result == 1
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert calls == []


def test_main_rejects_untrusted_repository_before_external_calls(
    monkeypatch,
    tmp_path,
):
    calls = []
    destination = tmp_path / "must-not-be-created"

    monkeypatch.setattr(
        INSTALLER,
        "run",
        lambda command, capture=True: calls.append(command),
    )

    result = INSTALLER.main([
        "--latest",
        "--install-dir",
        str(destination),
        "--repo",
        "attacker/devagent",
    ])

    assert result == 1
    assert calls == []
    assert not destination.exists()
