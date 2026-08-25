import subprocess
from pathlib import Path


class GitManager:
    def __init__(self, root="."):
        self.root = Path(root).resolve()

        if not self.root.exists():
            raise ValueError(
                f"Diretório raiz não existe: {self.root}"
            )

        if not self.root.is_dir():
            raise ValueError(
                f"Root não é um diretório: {self.root}"
            )

    def _ensure_git_repository(self):
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--is-inside-work-tree",
            ],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )

        if (
            result.returncode != 0
            or result.stdout.strip() != "true"
        ):
            raise ValueError(
                f"Root não é um repositório Git: {self.root}"
            )

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
        self._ensure_git_repository()

        result = self._run(
            "status",
            "--short",
        )

        return result.stdout

    def add_all(self):
        self._ensure_git_repository()

        self._run(
            "add",
            ".",
        )

    def commit(self, message):
        self._ensure_git_repository()

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
        if not isinstance(transaction_id, str):
            raise ValueError(
                "transaction_id deve ser uma string."
            )

        if not transaction_id.strip():
            raise ValueError(
                "transaction_id não pode ser vazio."
            )

        if not isinstance(instruction, str):
            raise ValueError(
                "instruction deve ser uma string."
            )

        if not instruction.strip():
            raise ValueError(
                "instruction não pode ser vazia."
            )

        self._ensure_git_repository()

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

        commit_hash = self._run(
            "rev-parse",
            "HEAD",
        ).stdout.strip()

        return {
            "transaction_id": transaction_id,
            "message": message,
            "status": "committed",
            "commit": commit_hash,
            "commit_hash": commit_hash,
        }
