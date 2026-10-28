import pytest


def test_find_transaction_commit_rejects_non_string_transaction_id(tmp_path):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)

    with pytest.raises(
        ValueError,
        match="transaction_id deve ser uma string",
    ):
        manager.find_transaction_commit(None)


def test_find_transaction_commit_rejects_empty_transaction_id(tmp_path):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)

    with pytest.raises(
        ValueError,
        match="transaction_id não pode ser vazio",
    ):
        manager.find_transaction_commit("   ")


def test_find_transaction_commit_ignores_blank_git_log_lines(tmp_path, monkeypatch):
    from core.executor.git_manager import GitManager

    transaction_id = "tx-blank-line"

    manager = GitManager(tmp_path)

    class Result:
        stdout = (
            "\n"
            f"abc123\x00DevAgent: transação {transaction_id} — alterar example.py\n"
        )

    monkeypatch.setattr(
        "core.executor.git_manager.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    monkeypatch.setattr(
        manager,
        "_ensure_git_repository",
        lambda: None,
    )

    result = manager.find_transaction_commit(transaction_id)

    assert result is not None
    assert result["commit_hash"] == "abc123"
    assert result["transaction_id"] == transaction_id


def test_find_transaction_commit_returns_matching_commit(tmp_path):
    import subprocess

    from core.executor.git_manager import GitManager

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "example.py"
    target.write_text("value = 1\n")

    subprocess.run(
        ["git", "add", "example.py"],
        cwd=tmp_path,
        check=True,
    )

    transaction_id = "abc-123"

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"DevAgent: transação {transaction_id} — alterar example.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    result = GitManager(tmp_path).find_transaction_commit(
        transaction_id
    )

    assert result is not None
    assert result["status"] == "committed"
    assert result["transaction_id"] == transaction_id
    assert result["commit_hash"]
    assert result["message"].startswith(
        f"DevAgent: transação {transaction_id} —"
    )


def test_find_transaction_commit_returns_none_when_missing(tmp_path):
    import subprocess

    from core.executor.git_manager import GitManager

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    result = GitManager(tmp_path).find_transaction_commit(
        "missing-transaction"
    )

    assert result is None

def test_find_transaction_commit_does_not_match_another_transaction(tmp_path):
    import subprocess
    from core.executor.git_manager import GitManager

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "example.py"
    target.write_text("value = 1\n")
    subprocess.run(
        ["git", "add", "example.py"],
        cwd=tmp_path,
        check=True,
    )

    other_transaction_id = "transaction-other"
    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"DevAgent: transação {other_transaction_id} — alterar example.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    result = GitManager(tmp_path).find_transaction_commit("transaction-target")

    assert result is None


def test_find_transaction_commit_propagates_git_log_failure(tmp_path, monkeypatch):
    import subprocess
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)

    monkeypatch.setattr(
        manager,
        "_ensure_git_repository",
        lambda: None,
    )

    error = subprocess.CalledProcessError(
        128,
        [
            "git",
            "log",
            "--all",
            "--fixed-strings",
            "--grep",
            "DevAgent: transação transaction-test —",
            "--format=%H%x00%s",
        ],
        stderr="fatal: git log failed",
    )

    def fake_run(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        "core.executor.git_manager.subprocess.run",
        fake_run,
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        manager.find_transaction_commit("transaction-test")

    assert exc_info.value.returncode == 128
    assert exc_info.value.stderr == "fatal: git log failed"

def test_unstage_paths_ignores_empty_paths(tmp_path, monkeypatch):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)
    calls = []

    monkeypatch.setattr(
        "core.executor.git_manager.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert manager._unstage_paths([]) is None
    assert calls == []


def test_find_transaction_commit_ignores_non_matching_nonblank_log_line(
    tmp_path,
    monkeypatch,
):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)
    transaction_id = "transaction-target"

    class Result:
        stdout = (
            "abc000\x00Outro commit qualquer\n"
            f"abc123\x00DevAgent: transação {transaction_id} — alterar example.py\n"
        )

    monkeypatch.setattr(
        "core.executor.git_manager.subprocess.run",
        lambda *args, **kwargs: Result(),
    )
    monkeypatch.setattr(
        manager,
        "_ensure_git_repository",
        lambda: None,
    )

    result = manager.find_transaction_commit(transaction_id)

    assert result is not None
    assert result["commit_hash"] == "abc123"
    assert result["transaction_id"] == transaction_id


def test_infer_paths_from_instruction_ignores_quoted_name_without_path_or_extension(
    tmp_path,
):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)

    result = manager._infer_paths_from_instruction(
        'modifique "arquivo"'
    )

    assert result == []


def test_infer_new_files_from_worktree_ignores_empty_untracked_path(
    tmp_path,
    monkeypatch,
):
    from core.executor.git_manager import GitManager

    manager = GitManager(tmp_path)

    class Result:
        stdout = "?? \n?? example.py\n"

    monkeypatch.setattr(
        "core.executor.git_manager.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    result = manager._infer_new_files_from_worktree()

    assert result == ["example.py"]

def test_commit_transaction_preserves_committed_git_commit_when_result_build_fails(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from core.executor.git_manager import GitManager

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "example.py"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    target.write_text("value = 2\n", encoding="utf-8")
    manager = GitManager(tmp_path)
    transaction_id = "tx-result-build-failure"

    def fail_result_build(*args, **kwargs):
        raise RuntimeError("RESULT_BUILD_FAILURE_TEST")

    monkeypatch.setattr(
        manager,
        "_build_commit_result",
        fail_result_build,
    )

    result = manager.commit_transaction(
        transaction_id,
        "alterar example.py",
        paths=["example.py"],
    )

    assert result["status"] == "committed"
    assert result["transaction_id"] == transaction_id
    assert result["commit_hash"]
    committed = manager.find_transaction_commit(transaction_id)

    assert committed is not None
    assert committed["status"] == "committed"
    assert committed["transaction_id"] == transaction_id
    assert committed["commit_hash"]
    assert target.read_text(encoding="utf-8") == "value = 2\n"
    assert manager.status() == ""

def test_commit_transaction_reraises_original_error_when_recovery_finds_no_commit(tmp_path, monkeypatch):
    import subprocess
    from core.executor.git_manager import GitManager

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "DevAgent Test"], cwd=tmp_path, check=True)
    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "example.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True, text=True)
    target.write_text("value = 2\n", encoding="utf-8")
    manager = GitManager(tmp_path)

    def fail_result_build(*args, **kwargs):
        raise RuntimeError("RESULT_BUILD_FAILURE_TEST")

    monkeypatch.setattr(manager, "_build_commit_result", fail_result_build)
    monkeypatch.setattr(manager, "find_transaction_commit", lambda transaction_id: None)

    with pytest.raises(RuntimeError, match="RESULT_BUILD_FAILURE_TEST"):
        manager.commit_transaction("tx-recovery-not-found", "alterar example.py", paths=["example.py"])
