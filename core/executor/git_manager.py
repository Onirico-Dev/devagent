from enum import Enum
from pathlib import Path
import re
import subprocess


class GitStatus(str, Enum):
    ERROR = "error"
    COMMITTED = "committed"


class GitManager:
    def __init__(self, root):
        self.root = Path(root).resolve()

        if not self.root.exists():
            raise ValueError("GitManager exige um root existente.")

        if not self.root.is_dir():
            raise ValueError("GitManager exige um root que seja diretório.")

        # Compatibilidade interna.
        self.project_root = self.root

    def _run_git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _ensure_git_repository(self):
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or result.stdout.strip() != "true":
            raise ValueError(
                "O diretório do projeto não é um repositório Git."
            )

    def status(self):
        self._ensure_git_repository()

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )

        return result.stdout

    def _normalize_paths(self, paths):
        if paths is None:
            return None

        if isinstance(paths, (str, Path)):
            paths = [paths]

        if not isinstance(paths, (list, tuple, set)):
            raise ValueError(
                "paths deve ser uma sequência de caminhos."
            )

        normalized = []

        for path in paths:
            if not isinstance(path, (str, Path)):
                raise ValueError(
                    "Cada caminho em paths deve ser string ou Path."
                )

            raw = str(path).strip()

            if not raw:
                continue

            candidate = (self.root / raw).resolve()

            try:
                candidate.relative_to(self.root)
            except ValueError:
                raise ValueError(
                    f"Caminho fora do projeto não permitido: {path}"
                )

            normalized.append(
                candidate.relative_to(self.root).as_posix()
            )

        return list(dict.fromkeys(normalized))

    def _infer_paths_from_instruction(self, instruction):
        """
        Compatibilidade com chamadas antigas que não fornecem paths.

        A inferência é deliberadamente restritiva:
        nunca usamos 'git add .' nem adicionamos todo o working tree.
        """

        candidates = set()

        # Arquivos explícitos com extensão.
        pattern = re.compile(
            r"(?<![\w./-])"
            r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+)"
            r"(?![\w./-])"
        )

        for match in pattern.findall(instruction):
            candidates.add(match)

        # Caminhos dentro de aspas.
        quoted_pattern = re.compile(
            r"""["'`]([^"'`]+)["'`]"""
        )

        for match in quoted_pattern.findall(instruction):
            candidate = match.strip()

            if "/" in candidate or "." in Path(candidate).name:
                candidates.add(candidate)

        valid = []

        for candidate in candidates:
            try:
                normalized = self._normalize_paths(
                    [candidate]
                )[0]
            except (ValueError, IndexError):
                continue

            valid.append(normalized)

        return list(dict.fromkeys(valid))

    def _infer_new_files_from_worktree(self):
        """
        Compatibilidade para alterações não rastreadas.

        Não adiciona indiscriminadamente o working tree:
        somente arquivos novos que possam ser identificados
        como arquivos de projeto.
        """

        result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )

        paths = []

        for line in result.stdout.splitlines():
            if not line.startswith("?? "):
                continue

            path = line[3:].strip()

            if path:
                paths.append(path)

        return paths

    def _path_has_changes(self, path):
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", path],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )

        return bool(result.stdout.strip())

    def _stage_paths(self, paths):
        if not paths:
            return []

        changed = []

        for path in paths:
            if self._path_has_changes(path):
                changed.append(path)

        if not changed:
            return []

        self._run_git("add", "--", *changed)

        return changed

    def _unstage_all(self):
        subprocess.run(
            ["git", "reset", "--quiet"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def commit_transaction(
        self,
        transaction_id,
        instruction,
        paths=None,
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

        if paths is None:
            paths = self._infer_paths_from_instruction(
                instruction
            )

            # Compatibilidade com chamadas antigas que não
            # especificam o arquivo, incluindo criação de arquivo.
            if not paths:
                paths = self._infer_new_files_from_worktree()
        else:
            paths = self._normalize_paths(paths)

        if not paths:
            return {
                "status": "no_changes",
                "transaction_id": transaction_id,
                "commit_hash": None,
                "files": [],
                "message": None,
            }

        changed_paths = self._stage_paths(paths)

        if not changed_paths:
            return {
                "status": "no_changes",
                "transaction_id": transaction_id,
                "commit_hash": None,
                "files": [],
                "message": None,
            }

        message = (
            f"DevAgent: transação {transaction_id} — "
            f"{instruction.strip()}"
        )

        try:
            commit = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.root,
                capture_output=True,
                text=True,
            )

            if commit.returncode != 0:
                self._unstage_all()

                return {
                    "status": GitStatus.ERROR.value,
                    "transaction_id": transaction_id,
                    "commit_hash": None,
                    "files": [],
                    "message": commit.stderr.strip(),
                }

            commit_hash = self._run_git(
                "rev-parse",
                "HEAD",
            ).stdout.strip()

            committed_files = self._run_git(
                "show",
                "--format=",
                "--name-only",
                "HEAD",
            ).stdout.splitlines()

            committed_files = [
                path.strip()
                for path in committed_files
                if path.strip()
            ]

            return {
                "status": GitStatus.COMMITTED.value,
                "transaction_id": transaction_id,
                "commit_hash": commit_hash,
                "files": committed_files,
                "message": message,
            }

        except Exception:
            self._unstage_all()
            raise
