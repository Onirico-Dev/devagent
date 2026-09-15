from dataclasses import dataclass
from typing import Any

from core.worker import Proposal, Worker


@dataclass(frozen=True)
class LoopResult:
    proposals: list[Proposal]
    stopped: bool
    metadata: dict[str, Any]


class AutonomyLoop:
    """Orquestra rodadas de observação sem atravessar a barreira de aprovação."""

    def __init__(self, worker: Worker):
        if not isinstance(worker, Worker):
            raise ValueError("Worker inválido.")
        self.worker = worker
        self._stopped = False
        self._iterations = 0

    def stop(self) -> None:
        self._stopped = True

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

    def run(self, max_iterations: int) -> list[LoopResult]:
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
            raise ValueError("max_iterations deve ser um inteiro positivo.")
        if max_iterations <= 0:
            raise ValueError("max_iterations deve ser um inteiro positivo.")

        results = []

        for _ in range(max_iterations):
            if self._stopped:
                break
            results.append(self.run_once())

        return results

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def iterations(self) -> int:
        return self._iterations
