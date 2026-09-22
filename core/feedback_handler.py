from typing import Any

from core.observation import Observation


class FeedbackHandler:
    """Processa observações produzidas por resultados de transações."""

    SOURCE = "transaction_result"

    def handle(self, observation: Observation) -> dict[str, Any]:
        if not isinstance(observation, Observation):
            raise ValueError("Observação de feedback inválida.")

        if observation.metadata.get("source") != self.SOURCE:
            raise ValueError("Observação não é um feedback de execução.")

        return {
            "handled": True,
            "transaction_id": observation.metadata.get("transaction_id"),
            "status": observation.metadata.get("status"),
        }
