from core.execution_feedback import ExecutionFeedback
from core.observation import Observation


def test_build_committed_result():
    result = {
        "approval_id": "12",
        "status": "committed",
        "transaction_id": "tx-123",
        "tests": {"success": True},
        "git": {"status": "committed"},
        "repair_attempts": 0,
    }

    observation = ExecutionFeedback().build(result)

    assert isinstance(observation, Observation)
    assert observation.instruction == "Avaliar resultado da transação."
    assert observation.metadata["source"] == "transaction_result"
    assert observation.metadata["transaction_id"] == "tx-123"
    assert observation.metadata["status"] == "committed"
    assert observation.metadata["tests"] == {"success": True}
    assert observation.metadata["git"] == {"status": "committed"}


def test_build_rolled_back_result():
    result = {
        "approval_id": "12",
        "status": "rolled_back",
        "transaction_id": "tx-456",
        "tests": {"success": False},
        "repair_attempts": 2,
        "error": "test failure",
    }

    observation = ExecutionFeedback().build(result)

    assert observation.metadata["status"] == "rolled_back"
    assert observation.metadata["transaction_id"] == "tx-456"
    assert observation.metadata["repair_attempts"] == 2
    assert observation.metadata["error"] == "test failure"


def test_build_failed_result():
    result = {
        "approval_id": "12",
        "status": "failed",
        "transaction_id": "tx-789",
        "rollback_error": "rollback failed",
    }

    observation = ExecutionFeedback().build(result)

    assert observation.metadata["status"] == "failed"
    assert observation.metadata["rollback_error"] == "rollback failed"


def test_non_final_result_returns_none():
    result = {
        "status": "executing",
        "transaction_id": "tx-123",
    }

    assert ExecutionFeedback().build(result) is None


def test_invalid_result_is_rejected():
    try:
        ExecutionFeedback().build(None)
    except ValueError as exc:
        assert str(exc) == "Resultado de execução inválido."
    else:
        raise AssertionError("Era esperado ValueError.")


def test_missing_transaction_id_is_rejected():
    result = {
        "status": "committed",
    }

    try:
        ExecutionFeedback().build(result)
    except ValueError as exc:
        assert str(exc) == "Resultado sem transaction_id."
    else:
        raise AssertionError("Era esperado ValueError.")
