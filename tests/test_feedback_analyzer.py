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


def test_committed_feedback_has_no_failure_type():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-1",
            "status": "committed",
        }
    )

    assert result["failure_type"] == "none"


def test_syntax_error_is_classified_from_test_stderr():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-2",
            "status": "rolled_back",
            "repair_attempts": 2,
            "tests": {
                "success": False,
                "stderr": "SyntaxError: invalid syntax",
            },
        }
    )

    assert result["failure_type"] == "syntax_error"


def test_syntax_error_is_classified_from_test_stdout():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-stdout",
            "status": "failed",
            "repair_attempts": 1,
            "tests": {
                "success": False,
                "stdout": "SyntaxError: invalid syntax",
                "stderr": "",
            },
        }
    )

    assert result["failure_type"] == "syntax_error"


def test_syntax_error_is_classified_from_error():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-3",
            "status": "failed",
            "repair_attempts": 1,
            "error": "SyntaxError: invalid syntax",
        }
    )

    assert result["failure_type"] == "syntax_error"


def test_test_failure_is_classified():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-4",
            "status": "failed",
            "repair_attempts": 1,
            "tests": {
                "success": False,
                "stderr": "AssertionError",
            },
        }
    )

    assert result["failure_type"] == "test_failure"


def test_rollback_error_is_classified():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-5",
            "status": "failed",
            "repair_attempts": 1,
            "rollback_error": "ROLLBACK_FAILURE",
        }
    )

    assert result["failure_type"] == "rollback_error"


def test_repair_limit_is_classified_without_specific_cause():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-6",
            "status": "rolled_back",
            "repair_attempts": 2,
        }
    )

    assert result["failure_type"] == "repair_limit_reached"


def test_execution_error_is_classified():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-7",
            "status": "failed",
            "repair_attempts": 1,
            "error": "PROCESS_FAILED",
        }
    )

    assert result["failure_type"] == "execution_error"


def test_unknown_failure_is_classified():
    result = FeedbackAnalyzer().analyze(
        {
            "transaction_id": "tx-class-8",
            "status": "failed",
            "repair_attempts": 0,
        }
    )

    assert result["failure_type"] == "unknown"


def test_classify_test_result_returns_unknown_for_non_dict():
    analyzer = FeedbackAnalyzer()

    assert analyzer.classify_test_result("resultado-invalido") == "unknown"


def test_classify_test_result_includes_error_evidence():
    analyzer = FeedbackAnalyzer()

    result = analyzer.classify_test_result(
        {"passed": False},
        error="AssertionError",
    )

    assert result == "execution_error"
