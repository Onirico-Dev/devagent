from enum import Enum
from pathlib import Path

from core.schemas.models import ChangeType


class PostExecutionStatus(str, Enum):
    MISSING = "missing"
    NOT_FILE = "not_file"
    CONTENT_MISMATCH = "content_mismatch"
    VERIFIED = "verified"


class PostExecutionVerifier:
    """Verifica se uma alteração executada produziu o estado esperado."""

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

    def verify_path(self, path, expected_content=None):
        target = (self.project_root / path).resolve()

        try:
            target.relative_to(self.project_root)
        except ValueError as exc:
            raise PermissionError(
                "Caminho inválido: fora do projeto."
            ) from exc

        if not target.exists():
            return {
                "success": False,
                "status": PostExecutionStatus.MISSING.value,
                "path": str(path),
            }

        if not target.is_file():
            return {
                "success": False,
                "status": PostExecutionStatus.NOT_FILE.value,
                "path": str(path),
            }

        if expected_content is not None:
            actual = target.read_text(encoding="utf-8")
            if actual != expected_content:
                return {
                    "success": False,
                    "status": PostExecutionStatus.CONTENT_MISMATCH.value,
                    "path": str(path),
                }

        return {
            "success": True,
            "status": PostExecutionStatus.VERIFIED.value,
            "path": str(path),
        }

    def verify_change(self, change):
        """Verifica o estado físico produzido por uma Change executada."""

        if change.change_type == ChangeType.DELETE:
            target = (self.project_root / change.path).resolve()

            try:
                target.relative_to(self.project_root)
            except ValueError as exc:
                raise PermissionError(
                    "Caminho inválido: fora do projeto."
                ) from exc

            if target.exists():
                return {
                    "success": False,
                    "status": PostExecutionStatus.CONTENT_MISMATCH.value,
                    "path": str(change.path),
                }

            return {
                "success": True,
                "status": PostExecutionStatus.VERIFIED.value,
                "path": str(change.path),
            }

        return self.verify_path(
            change.path,
            expected_content=change.content,
        )

    def verify_transaction(self, transaction):
        """Verifica todas as alterações de uma transação."""

        results = [
            self.verify_change(change)
            for change in transaction.changes
        ]

        failed = next(
            (result for result in results if not result["success"]),
            None,
        )

        if failed is not None:
            return {
                "success": False,
                "status": failed["status"],
                "path": failed["path"],
                "changes": results,
            }

        return {
            "success": True,
            "status": PostExecutionStatus.VERIFIED.value,
            "changes": results,
        }
