from typing import Any

from core.observation import Observation


class ExecutionFeedback:
    SOURCE = "transaction_result"

    FINAL_STATUSES = {
        "committed",
        "rolled_back",
        "failed",
    }

    def build(self, result: dict[str, Any]) -> Observation | None:
        if not isinstance(result, dict):
            raise ValueError("Resultado de execução inválido.")

        status = result.get("status")
        transaction_id = result.get("transaction_id")

        if status not in self.FINAL_STATUSES:
            return None

        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise ValueError("Resultado sem transaction_id.")

        metadata = {
            "source": self.SOURCE,
            "transaction_id": transaction_id,
            "approval_id": result.get("approval_id"),
            "status": status,
            "tests": result.get("tests"),
            "repair_attempts": result.get("repair_attempts", 0),
        }

        transaction_metadata = result.get("metadata")
        if transaction_metadata is not None:
            if not isinstance(transaction_metadata, dict):
                raise ValueError("Metadata da transação inválida.")
            metadata["transaction_metadata"] = dict(transaction_metadata)

        if "git" in result:
            metadata["git"] = result["git"]

        if "repair" in result:
            metadata["repair"] = result["repair"]

        if "error" in result:
            metadata["error"] = result["error"]

        if "rollback_error" in result:
            metadata["rollback_error"] = result["rollback_error"]

        return Observation(
            instruction="Avaliar resultado da transação.",
            metadata=metadata,
        )
