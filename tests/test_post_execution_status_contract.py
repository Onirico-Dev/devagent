from core.engine.post_execution import PostExecutionStatus


def test_post_execution_status_contract():
    assert PostExecutionStatus.MISSING.value == "missing"
    assert PostExecutionStatus.NOT_FILE.value == "not_file"
    assert PostExecutionStatus.CONTENT_MISMATCH.value == "content_mismatch"
    assert PostExecutionStatus.VERIFIED.value == "verified"
