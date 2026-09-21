import math
import time
from collections.abc import Callable
from typing import Any


class LoopController:
    """Controla estado e execução iterativa comum aos loops do DevAgent."""

    def __init__(self):
        self._stopped = False
        self._iterations = 0

    def stop(self) -> None:
        self._stopped = True

    def start(self) -> None:
        self._stopped = False

    def run(self, max_iterations: int):
        if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
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

    def run_continuous(
        self,
        interval_seconds: float = 1.0,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], Any] = time.sleep,
    ):
        if (
            not isinstance(interval_seconds, (int, float))
            or isinstance(interval_seconds, bool)
            or not math.isfinite(interval_seconds)
            or interval_seconds < 0
        ):
            raise ValueError(
                "interval_seconds deve ser um número finito não negativo."
            )

        if max_iterations is not None:
            if (
                not isinstance(max_iterations, int)
                or isinstance(max_iterations, bool)
                or max_iterations <= 0
            ):
                raise ValueError(
                    "max_iterations deve ser um inteiro positivo."
                )

        if not callable(sleep_fn):
            raise ValueError("sleep_fn deve ser chamável.")

        results = []

        while not self._stopped:
            results.append(self.run_once())

            if self._stopped:
                break

            if (
                max_iterations is not None
                and len(results) >= max_iterations
            ):
                break

            if interval_seconds > 0:
                sleep_fn(interval_seconds)

        return results

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def iterations(self) -> int:
        return self._iterations
