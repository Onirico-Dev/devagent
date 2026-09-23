from typing import Any


class FeedbackAnalyzer:
    """Analisa feedback de transações sem executar ações."""

    FINAL_STATUSES = {
        "committed",
        "rolled_back",
        "failed",
    }

    MAX_REPAIR_ATTEMPTS = 2

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
            "transaction_metadata",
        ):
            if key in feedback:
                evidence[key] = feedback[key]

        action_required = status in {"rolled_back", "failed"}
        failure_type = self._classify_failure(
            status=status,
            repair_attempts=repair_attempts,
            evidence=evidence,
        )

        return {
            "transaction_id": transaction_id,
            "status": status,
            "action_required": action_required,
            "repair_attempts": repair_attempts,
            "failure_type": failure_type,
            "evidence": evidence,
        }

    def _classify_failure(
        self,
        *,
        status: str,
        repair_attempts: int,
        evidence: dict[str, Any],
    ) -> str:
        if status == "committed":
            return "none"

        rollback_error = evidence.get("rollback_error")
        if rollback_error:
            return "rollback_error"

        error = evidence.get("error")
        tests = evidence.get("tests")

        if not isinstance(tests, dict):
            tests = {}

        stderr = tests.get("stderr")
        test_error = tests.get("error")
        test_success = tests.get("success")

        diagnostic_text = " ".join(
            str(value)
            for value in (error, stderr, test_error)
            if value is not None
        ).lower()

        if "syntaxerror" in diagnostic_text or "syntax error" in diagnostic_text:
            return "syntax_error"

        if test_success is False:
            return "test_failure"

        if repair_attempts >= self.MAX_REPAIR_ATTEMPTS:
            return "repair_limit_reached"

        if error:
            return "execution_error"

        return "unknown"
