import pytest

from core.feedback_proposal_builder import FeedbackProposalBuilder


def test_committed_analysis_does_not_create_proposal():
    result = FeedbackProposalBuilder().build(
        {
            "transaction_id": "tx-1",
            "status": "committed",
            "action_required": False,
            "repair_attempts": 0,
            "evidence": {},
        }
    )

    assert result is None


def test_failed_analysis_creates_correction_proposal():
    result = FeedbackProposalBuilder().build(
        {
            "transaction_id": "tx-2",
            "status": "failed",
            "action_required": True,
            "repair_attempts": 2,
            "evidence": {
                "error": "TEST_FAILURE",
            },
        }
    )

    assert result["source"] == "transaction_feedback"
    assert result["transaction_id"] == "tx-2"
    assert result["status"] == "failed"
    assert result["repair_attempts"] == 2
    assert result["evidence"]["error"] == "TEST_FAILURE"
    assert "tx-2" in result["instruction"]
    assert "correção" in result["instruction"]


def test_rolled_back_analysis_creates_correction_proposal():
    result = FeedbackProposalBuilder().build(
        {
            "transaction_id": "tx-3",
            "status": "rolled_back",
            "action_required": True,
            "repair_attempts": 1,
            "evidence": {
                "tests": {"success": False},
            },
        }
    )

    assert result is not None
    assert result["transaction_id"] == "tx-3"


def test_invalid_analysis_is_rejected():
    with pytest.raises(ValueError, match="Análise"):
        FeedbackProposalBuilder().build(None)


def test_missing_transaction_id_is_rejected():
    with pytest.raises(ValueError, match="transaction_id"):
        FeedbackProposalBuilder().build(
            {
                "status": "failed",
                "action_required": True,
            }
        )


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError, match="Status"):
        FeedbackProposalBuilder().build(
            {
                "transaction_id": "tx-4",
                "status": "pending",
                "action_required": True,
            }
        )


@pytest.mark.parametrize("value", [None, "true", 1, 0])
def test_invalid_action_required_is_rejected(value):
    with pytest.raises(ValueError, match="action_required"):
        FeedbackProposalBuilder().build(
            {
                "transaction_id": "tx-5",
                "status": "failed",
                "action_required": value,
            }
        )


def test_invalid_evidence_is_rejected():
    with pytest.raises(ValueError, match="Evidências"):
        FeedbackProposalBuilder().build(
            {
                "transaction_id": "tx-6",
                "status": "failed",
                "action_required": True,
                "evidence": [],
            }
        )


def test_failed_analysis_preserves_failure_type():
    result = FeedbackProposalBuilder().build(
        {
            "transaction_id": "tx-7",
            "status": "failed",
            "action_required": True,
            "failure_type": "syntax_error",
            "repair_attempts": 2,
            "evidence": {
                "error": "SyntaxError: invalid syntax",
            },
        }
    )

    assert result["failure_type"] == "syntax_error"


def test_missing_failure_type_defaults_to_unknown():
    result = FeedbackProposalBuilder().build(
        {
            "transaction_id": "tx-8",
            "status": "failed",
            "action_required": True,
            "repair_attempts": 0,
            "evidence": {},
        }
    )

    assert result["failure_type"] == "unknown"
