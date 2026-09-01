from core.executor.git_manager import GitStatus


def test_git_status_contract():
    assert GitStatus.ERROR.value == "error"
    assert GitStatus.COMMITTED.value == "committed"
