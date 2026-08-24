import subprocess
from pathlib import Path


class GitManager:

    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def _run(self, *args):

        result = subprocess.run(
            ["git", *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:

            raise RuntimeError(
                result.stderr.strip()
                or result.stdout.strip()
                or f"Git falhou: {' '.join(args)}"
            )

        return result

    def status(self):

        result = self._run(
            "status",
            "--short",
        )

        return result.stdout

    def add_all(self):

        self._run(
            "add",
            ".",
        )

    def commit(self, message):

        self._run(
            "commit",
            "-m",
            message,
        )

    def commit_transaction(
        self,
        transaction_id,
        instruction,
    ):

        self.add_all()

        message = (
            f"DevAgent: transação "
            f"{transaction_id} — "
            f"{instruction}"
        )

        if not self.status().strip():

            return {
                "transaction_id": transaction_id,
                "message": message,
                "status": "no_changes",
            }

        self.commit(message)

        return {
            "transaction_id": transaction_id,
            "message": message,
            "status": "committed",
        }
