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
