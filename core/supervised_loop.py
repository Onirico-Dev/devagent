from dataclasses import dataclass
from typing import Any

from core.loop_controller import LoopController


@dataclass(frozen=True)
class SupervisedLoopResult:
    proposals: list[Any]
    stopped: bool
    metadata: dict[str, Any]


class SupervisedLoop(LoopController):
    """Coordena observação e propostas sem atravessar a barreira de aprovação."""

    _TERMINAL_STATUSES = {
        "committed",
        "rejected",
        "rolled_back",
        "failed",
    }

    def __init__(self, worker, gateway, state_store=None):
        if not hasattr(worker, "run_once"):
            raise ValueError("Worker inválido.")

        if not hasattr(gateway, "list_tasks"):
            raise ValueError("Gateway inválido.")

        if state_store is not None and not hasattr(state_store, "load"):
            raise ValueError("Armazenamento de estado inválido.")

        if state_store is not None and not hasattr(state_store, "save"):
            raise ValueError("Armazenamento de estado inválido.")

        super().__init__()

        self.worker = worker
        self.gateway = gateway
        self.state_store = state_store

        if self.state_store is not None:
            self.restore_state(self.state_store.load())

    def _persist_state(self) -> None:
        if self.state_store is not None:
            self.state_store.save(self.export_state())

    def stop(self) -> None:
        self._stopped = True
        self._persist_state()

    def run_once(self) -> SupervisedLoopResult:
        if self._stopped:
            return SupervisedLoopResult(
                proposals=[],
                stopped=True,
                metadata={"iterations": self._iterations},
            )

        proposals = self.worker.run_once()
        self._iterations += 1

        auto_approved_count = 0

        for proposal in proposals:
            if isinstance(proposal, dict):
                autonomy_decision = proposal.get(
                    "autonomy_decision"
                )
                status = proposal.get("status")
                approval_id = proposal.get("approval_id")
            else:
                autonomy_decision = getattr(
                    proposal,
                    "autonomy_decision",
                    None,
                )
                status = getattr(
                    proposal,
                    "status",
                    None,
                )
                approval_id = getattr(
                    proposal,
                    "approval_id",
                    None,
                )

            if (
                autonomy_decision == "auto_approve"
                and status == "pending"
                and approval_id is not None
            ):
                self.gateway.approve(approval_id)
                auto_approved_count += 1

        tasks = self.gateway.list_tasks()
        pending_count = sum(
            1
            for task in tasks
            if task.get("status") == "pending"
        )

        self._persist_state()

        return SupervisedLoopResult(
            proposals=proposals,
            stopped=False,
            metadata={
                "iterations": self._iterations,
                "proposal_count": len(proposals),
                "auto_approved_count": auto_approved_count,
                "pending_count": pending_count,
            },
        )

    def export_state(self) -> dict[str, Any]:
        return {
            "stopped": self._stopped,
            "iterations": self._iterations,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict):
            raise ValueError("Estado inválido.")

        stopped = state.get("stopped", False)
        iterations = state.get("iterations", 0)

        if not isinstance(stopped, bool):
            raise ValueError("Estado inválido.")

        if not isinstance(iterations, int) or isinstance(iterations, bool):
            raise ValueError("Estado inválido.")

        if iterations < 0:
            raise ValueError("Estado inválido.")

        self._stopped = stopped
        self._iterations = iterations
