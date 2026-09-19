from dataclasses import dataclass
from typing import Any

from core.loop_controller import LoopController
from core.worker import Proposal, Worker


@dataclass(frozen=True)
class LoopResult:
    proposals: list[Proposal]
    stopped: bool
    metadata: dict[str, Any]


class AutonomyLoop(LoopController):
    """Orquestra rodadas de observação sem atravessar a barreira de aprovação."""

    def __init__(self, worker: Worker):
        if not isinstance(worker, Worker):
            raise ValueError("Worker inválido.")

        super().__init__()
        self.worker = worker

    def run_once(self) -> LoopResult:
        if self._stopped:
            return LoopResult(
                proposals=[],
                stopped=True,
                metadata={"iterations": self._iterations},
            )

        proposals = self.worker.run_once()
        self._iterations += 1

        return LoopResult(
            proposals=proposals,
            stopped=False,
            metadata={
                "iterations": self._iterations,
                "proposal_count": len(proposals),
            },
        )
