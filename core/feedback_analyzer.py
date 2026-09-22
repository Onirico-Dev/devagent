from typing import Any


class FeedbackAnalyzer:
    """Analisa feedback de transações sem executar ações."""

    FINAL_STATUSES = {
        "committed",
        "rolled_back",
        "failed",
    }

    def analyze(self, feedback: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feedback, dict):
            raise ValueError("Feedback inválido.")

        transaction_id = feedback.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise ValueError("Feedback sem transaction_id.")

        status = feedback.get("status")
        if status not in self.FINAL_STATUSES:
            raise ValueError("Status de feedback inválido.")

        repair_attempts = feedback.get("repair_attempts", 0)
        if (
            not isinstance(repair_attempts, int)
            or isinstance(repair_attempts, bool)
            or repair_attempts < 0
        ):
            raise ValueError("repair_attempts inválido.")

        evidence: dict[str, Any] = {}

        for key in (
            "tests",
            "repair",
            "error",
            "rollback_error",
            "git",
        ):
            if key in feedback:
                evidence[key] = feedback[key]

        action_required = status in {"rolled_back", "failed"}

        return {
            "transaction_id": transaction_id,
            "status": status,
            "action_required": action_required,
            "repair_attempts": repair_attempts,
            "evidence": evidence,
        }
