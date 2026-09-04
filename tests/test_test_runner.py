import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from core.executor.test_runner import TestRunner as Runner


def test_compile_file_returns_failure_when_file_does_not_exist(tmp_path):
    runner = Runner(tmp_path)

    result = runner._compile_file("missing.py")

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert "Arquivo não encontrado: missing.py" in result["stderr"]


def test_compile_file_returns_success_for_valid_python(tmp_path):
    target = tmp_path / "valid.py"
    target.write_text("VALUE = 42\n", encoding="utf-8")

    runner = Runner(tmp_path)

    result = runner._compile_file("valid.py")

    assert result["success"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "Syntax OK: valid.py"
    assert result["stderr"] == ""


def test_compile_file_returns_failure_for_invalid_python(tmp_path):
    target = tmp_path / "invalid.py"
    target.write_text("def broken(:\n", encoding="utf-8")

    runner = Runner(tmp_path)

    result = runner._compile_file("invalid.py")

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert result["stderr"]


def test_compile_file_handles_pycompile_error(tmp_path, monkeypatch):
    runner = Runner(tmp_path)
    target = tmp_path / "app.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    def fake_compile(*args, **kwargs):
        raise py_compile.PyCompileError(
            SyntaxError,
            SyntaxError("broken"),
            "app.py",
        )

    monkeypatch.setattr(py_compile, "compile", fake_compile)

    result = runner._compile_file("app.py")

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert "SyntaxError" in result["stderr"]


def test_run_pytest_returns_success(tmp_path, monkeypatch):
    runner = Runner(tmp_path)

    class Result:
        returncode = 0
        stdout = "2 passed"
        stderr = ""

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner._run_pytest(["tests/test_app.py"])

    assert result == {
        "success": True,
        "returncode": 0,
        "stdout": "2 passed",
        "stderr": "",
    }

    assert calls[0][0][0][0] == sys.executable
    assert calls[0][0][0][1:4] == ["-m", "pytest", "-q"]
    assert calls[0][0][0][-1] == "tests/test_app.py"


def test_run_pytest_returns_failure(tmp_path, monkeypatch):
    runner = Runner(tmp_path)

    class Result:
        returncode = 1
        stdout = "1 failed"
        stderr = "failure"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    result = runner._run_pytest(["tests/test_app.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == "1 failed"
    assert result["stderr"] == "failure"


def test_run_without_files_runs_full_pytest(tmp_path, monkeypatch):
    runner = Runner(tmp_path)

    class Result:
        returncode = 0
        stdout = "10 passed"
        stderr = ""

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.run()

    assert result == {
        "success": True,
        "returncode": 0,
        "stdout": "10 passed",
        "stderr": "",
    }

    command = calls[0][0][0]
    assert command == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
    ]


def test_run_without_files_returns_failure_when_pytest_fails(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    class Result:
        returncode = 2
        stdout = "pytest output"
        stderr = "pytest error"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: Result(),
    )

    result = runner.run()

    assert result["success"] is False
    assert result["returncode"] == 2
    assert result["stdout"] == "pytest output"
    assert result["stderr"] == "pytest error"


def test_run_compiles_normal_python_files_and_runs_test_files(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    compile_results = []

    def fake_compile(path):
        compile_results.append(path)
        return {
            "success": True,
            "returncode": 0,
            "stdout": f"Syntax OK: {path}",
            "stderr": "",
        }

    pytest_results = []

    def fake_pytest(files):
        pytest_results.append(files)
        return {
            "success": True,
            "returncode": 0,
            "stdout": "2 passed",
            "stderr": "",
        }

    monkeypatch.setattr(runner, "_compile_file", fake_compile)
    monkeypatch.setattr(runner, "_run_pytest", fake_pytest)

    result = runner.run(
        [
            "core/app.py",
            "tests/test_app.py",
            "tests/app_test.py",
            "README.txt",
            "script.sh",
        ]
    )

    assert result["success"] is True
    assert result["returncode"] == 0
    assert "Syntax OK: core/app.py" in result["stdout"]
    assert "2 passed" in result["stdout"]
    assert result["stderr"] == ""

    assert compile_results == ["core/app.py"]
    assert pytest_results == [
        ["tests/test_app.py", "tests/app_test.py"]
    ]


def test_run_ignores_non_python_files(tmp_path, monkeypatch):
    runner = Runner(tmp_path)

    compile_calls = []
    pytest_calls = []

    monkeypatch.setattr(
        runner,
        "_compile_file",
        lambda path: compile_calls.append(path) or {
            "success": True,
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        runner,
        "_run_pytest",
        lambda files: pytest_calls.append(files) or {
            "success": True,
            "returncode": 0,
            "stdout": "tests ok",
            "stderr": "",
        },
    )

    result = runner.run(["README.md", "script.sh", "data.json"])

    assert result["success"] is True
    assert result["returncode"] == 0
    assert compile_calls == []
    assert pytest_calls == []
    assert result["stdout"] == ""


def test_run_returns_failure_when_normal_file_compile_fails(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    monkeypatch.setattr(
        runner,
        "_compile_file",
        lambda path: {
            "success": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"erro em {path}",
        },
    )

    result = runner.run(["broken.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == ""
    assert result["stderr"] == "erro em broken.py"


def test_run_returns_failure_when_test_file_fails(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    monkeypatch.setattr(
        runner,
        "_run_pytest",
        lambda files: {
            "success": False,
            "returncode": 1,
            "stdout": "1 failed",
            "stderr": "failure",
        },
    )

    result = runner.run(["tests/test_app.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == "1 failed"
    assert result["stderr"] == "failure"


def test_run_combines_multiple_results(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    monkeypatch.setattr(
        runner,
        "_compile_file",
        lambda path: {
            "success": True,
            "returncode": 0,
            "stdout": f"compiled {path}",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        runner,
        "_run_pytest",
        lambda files: {
            "success": True,
            "returncode": 0,
            "stdout": "3 passed",
            "stderr": "",
        },
    )

    result = runner.run(
        [
            "app.py",
            "tests/test_app.py",
        ]
    )

    assert result["success"] is True
    assert result["returncode"] == 0
    assert "compiled app.py" in result["stdout"]
    assert "3 passed" in result["stdout"]
    assert result["stderr"] == ""


def test_run_combines_stderr_from_failed_results(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    monkeypatch.setattr(
        runner,
        "_compile_file",
        lambda path: {
            "success": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "compile failure",
        },
    )

    monkeypatch.setattr(
        runner,
        "_run_pytest",
        lambda files: {
            "success": False,
            "returncode": 1,
            "stdout": "pytest output",
            "stderr": "pytest failure",
        },
    )

    result = runner.run(
        [
            "app.py",
            "tests/test_app.py",
        ]
    )

    assert result["success"] is False
    assert result["returncode"] == 1
    assert result["stdout"] == "pytest output"
    assert "compile failure" in result["stderr"]
    assert "pytest failure" in result["stderr"]


def test_compile_file_rejects_path_outside_root(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside.py"

    root.mkdir()
    outside.write_text("x = 1\n", encoding="utf-8")

    runner = Runner(root)

    result = runner._compile_file("../outside.py")

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "fora do projeto" in result["stderr"]


def test_run_rejects_path_outside_root(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside.py"

    root.mkdir()
    outside.write_text("x = 1\n", encoding="utf-8")

    runner = Runner(root)

    result = runner.run(["../outside.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "fora do projeto" in result["stderr"]


def test_compile_file_rejects_absolute_path(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside.py"

    root.mkdir()
    outside.write_text("x = 1\n", encoding="utf-8")

    runner = Runner(root)

    result = runner._compile_file(str(outside))

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "absoluto" in result["stderr"]


def test_safe_path_rejects_invalid_type(tmp_path):
    runner = Runner(tmp_path)

    with pytest.raises(ValueError, match="Caminho de teste inválido"):
        runner._safe_path(123)


def test_run_pytest_rejects_invalid_path(tmp_path):
    runner = Runner(tmp_path)

    result = runner._run_pytest(["../outside.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "fora do projeto" in result["stderr"]


def test_run_pytest_rejects_absolute_path(tmp_path):
    runner = Runner(tmp_path)
    outside = tmp_path.parent / "outside_test.py"

    result = runner._run_pytest([outside])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "absoluto" in result["stderr"]


def test_run_pytest_rejects_relative_path_escape_after_resolution(
    tmp_path,
    monkeypatch,
):
    runner = Runner(tmp_path)

    class FakeTarget:
        def relative_to(self, root):
            raise ValueError("forced containment failure")

    monkeypatch.setattr(
        runner,
        "_safe_path",
        lambda _: FakeTarget(),
    )

    result = runner._run_pytest(["test_fake.py"])

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "fora do projeto" in result["stderr"]
