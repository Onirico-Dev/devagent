import pytest

from core.feedback_analyzer import FeedbackAnalyzer
from core.feedback_handler import FeedbackHandler
from core.feedback_proposal_builder import FeedbackProposalBuilder
from core.observation import Observation


def test_handler_analyzes_transaction_feedback():
    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-1",
            "status": "failed",
            "repair_attempts": 2,
            "error": "TEST_FAILURE",
        },
    )

    result = FeedbackHandler().handle(observation)

    assert result["handled"] is True
    assert result["analysis"]["transaction_id"] == "tx-1"
    assert result["analysis"]["action_required"] is True
    assert result["proposal"]["transaction_id"] == "tx-1"


def test_handler_does_not_create_proposal_for_committed_feedback():
    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-2",
            "status": "committed",
        },
    )

    result = FeedbackHandler().handle(observation)

    assert result["handled"] is True
    assert result["analysis"]["action_required"] is False
    assert result["proposal"] is None


def test_handler_rejects_non_feedback_observation():
    observation = Observation(
        instruction="crie arquivo.py",
        metadata={"source": "manual"},
    )

    with pytest.raises(
        ValueError,
        match="não é um feedback de execução",
    ):
        FeedbackHandler().handle(observation)


def test_handler_rejects_invalid_observation():
    with pytest.raises(
        ValueError,
        match="Observação de feedback inválida",
    ):
        FeedbackHandler().handle(None)


def test_handler_uses_injected_components():
    class Analyzer:
        def analyze(self, feedback):
            assert feedback["transaction_id"] == "tx-original"
            return {
                "transaction_id": "tx-analyzed",
                "status": "failed",
                "action_required": True,
                "repair_attempts": 1,
                "evidence": {},
            }

    class ProposalBuilder:
        def build(self, analysis):
            assert analysis["transaction_id"] == "tx-analyzed"
            return {
                "instruction": "corrigir tx-analyzed",
                "transaction_id": "tx-analyzed",
            }

    handler = FeedbackHandler(
        analyzer=Analyzer(),
        proposal_builder=ProposalBuilder(),
    )

    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-original",
            "status": "failed",
        },
    )

    result = handler.handle(observation)

    assert result["analysis"]["transaction_id"] == "tx-analyzed"
    assert result["proposal"]["transaction_id"] == "tx-analyzed"


def test_handler_propagates_analyzer_validation_error():
    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-invalid",
            "status": "pending",
        },
    )

    with pytest.raises(ValueError, match="Status"):
        FeedbackHandler().handle(observation)


def test_handler_propagates_proposal_builder_error():
    class ProposalBuilder:
        def build(self, analysis):
            raise ValueError("builder failure")

    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-3",
            "status": "failed",
        },
    )

    with pytest.raises(ValueError, match="builder failure"):
        FeedbackHandler(
            proposal_builder=ProposalBuilder()
        ).handle(observation)
