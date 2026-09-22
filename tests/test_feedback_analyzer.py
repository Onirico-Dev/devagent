import pytest

from core.feedback_analyzer import FeedbackAnalyzer


def test_committed_feedback_requires_no_action():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-1",
            "status": "committed",
            "repair_attempts": 0,
            "tests": {"success": True},
        }
    )

    assert result["transaction_id"] == "tx-1"
    assert result["status"] == "committed"
    assert result["action_required"] is False
    assert result["repair_attempts"] == 0
    assert result["evidence"]["tests"] == {"success": True}


def test_rolled_back_feedback_requires_action():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-2",
            "status": "rolled_back",
            "repair_attempts": 2,
            "tests": {"success": False},
            "repair": {"status": "failed"},
        }
    )

    assert result["action_required"] is True
    assert result["repair_attempts"] == 2
    assert result["evidence"]["repair"] == {"status": "failed"}


def test_failed_feedback_requires_action_and_preserves_errors():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-3",
            "status": "failed",
            "repair_attempts": 1,
            "error": "TEST_FAILURE",
            "rollback_error": "ROLLBACK_FAILURE",
        }
    )

    assert result["action_required"] is True
    assert result["evidence"]["error"] == "TEST_FAILURE"
    assert result["evidence"]["rollback_error"] == "ROLLBACK_FAILURE"


def test_feedback_without_repair_attempts_defaults_to_zero():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-4",
            "status": "committed",
        }
    )

    assert result["repair_attempts"] == 0


@pytest.mark.parametrize(
    "feedback",
    [
        None,
        [],
        "feedback",
    ],
)
def test_invalid_feedback_is_rejected(feedback):
    with pytest.raises(ValueError, match="Feedback inválido"):
        FeedbackAnalyzer().analyze(feedback)


def test_missing_transaction_id_is_rejected():
    with pytest.raises(ValueError, match="transaction_id"):
        FeedbackAnalyzer().analyze({"status": "failed"})


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError, match="Status"):
        FeedbackAnalyzer().analyze(
            {
                "transaction_id": "tx-5",
                "status": "pending",
            }
        )


@pytest.mark.parametrize("value", [-1, True, "1", 1.5])
def test_invalid_repair_attempts_are_rejected(value):
    with pytest.raises(ValueError, match="repair_attempts"):
        FeedbackAnalyzer().analyze(
            {
                "transaction_id": "tx-6",
                "status": "failed",
                "repair_attempts": value,
            }
        )
