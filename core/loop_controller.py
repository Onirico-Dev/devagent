class LoopController:
    """Controla estado e execução iterativa comum aos loops do DevAgent."""

    def __init__(self):
        self._stopped = False
        self._iterations = 0

    def stop(self) -> None:
        self._stopped = True

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

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def iterations(self) -> int:
        return self._iterations
