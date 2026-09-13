
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
