from typing import Any

from core.feedback_analyzer import FeedbackAnalyzer
from core.feedback_proposal_builder import FeedbackProposalBuilder
from core.observation import Observation


class FeedbackHandler:
    """Processa e analisa observações produzidas por resultados de transações."""

    SOURCE = "transaction_result"

    def __init__(
        self,
        analyzer: FeedbackAnalyzer | None = None,
        proposal_builder: FeedbackProposalBuilder | None = None,
    ):
        self.analyzer = analyzer or FeedbackAnalyzer()
        self.proposal_builder = proposal_builder or FeedbackProposalBuilder()

    def handle(self, observation: Observation) -> dict[str, Any]:
        if not isinstance(observation, Observation):
            raise ValueError("Observação de feedback inválida.")

        if observation.metadata.get("source") != self.SOURCE:
            raise ValueError("Observação não é um feedback de execução.")

        analysis = self.analyzer.analyze(observation.metadata)
        proposal = self.proposal_builder.build(analysis)

        return {
            "handled": True,
            "analysis": analysis,
            "proposal": proposal,
        }
