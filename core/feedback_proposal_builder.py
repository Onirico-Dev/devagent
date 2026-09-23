from typing import Any


class FeedbackProposalBuilder:
    """Converte um diagnóstico de feedback em uma proposta corretiva."""

    def build(self, analysis: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(analysis, dict):
            raise ValueError("Análise de feedback inválida.")

        transaction_id = analysis.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise ValueError("Análise sem transaction_id.")

        status = analysis.get("status")
        if status not in {"committed", "rolled_back", "failed"}:
            raise ValueError("Status de análise inválido.")

        action_required = analysis.get("action_required")
        if not isinstance(action_required, bool):
            raise ValueError("action_required inválido.")

        if not action_required:
            return None

        evidence = analysis.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("Evidências de feedback inválidas.")

        transaction_metadata = evidence.get("transaction_metadata", {})
        if not isinstance(transaction_metadata, dict):
            raise ValueError("Metadata da transação inválida.")

        instruction = (
            "Analise a transação "
            f"{transaction_id}, que terminou com status '{status}', "
            "identifique a causa da falha e proponha uma correção segura."
        )

        return {
            "instruction": instruction,
            "source": "transaction_feedback",
            "transaction_id": transaction_id,
            "status": status,
            "repair_attempts": analysis.get("repair_attempts", 0),
            "evidence": dict(evidence),
            "transaction_metadata": dict(transaction_metadata),
        }
