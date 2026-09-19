from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SupervisedLoopResult:
    proposals: list[Any]
    stopped: bool
    metadata: dict[str, Any]


class SupervisedLoop:
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

        self.worker = worker
        self.gateway = gateway
        self.state_store = state_store
        self._stopped = False
        self._iterations = 0

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
                "pending_count": pending_count,
            },
        )

    def run(self, max_iterations: int) -> list[SupervisedLoopResult]:
        if not isinstance(max_iterations, int) or isinstance(
            max_iterations, bool
        ):
            raise ValueError(
                "max_iterations deve ser um inteiro positivo."
            )

        if max_iterations <= 0:
            raise ValueError(
                "max_iterations deve ser um inteiro positivo."
            )

        results = []

        for _ in range(max_iterations):
            if self._stopped:
                break
            results.append(self.run_once())

        return results

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

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def iterations(self) -> int:
        return self._iterations
