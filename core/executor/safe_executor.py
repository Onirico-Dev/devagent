from pathlib import Path

from core.schemas.models import ChangeType, TransactionStatus


class SafeExecutor:

    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()

    def _safe_path(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()

        if not str(target).startswith(str(self.root)):
            raise ValueError(
                f"Caminho bloqueado: {relative_path}"
            )

        return target

    def execute(self, transaction):

        transaction.status = TransactionStatus.EXECUTING

        try:
            for change in transaction.changes:

                target = self._safe_path(change.path)

                if change.change_type == ChangeType.CREATE:
                    if target.exists():
                        raise FileExistsError(
                            f"Arquivo já existe: {change.path}"
                        )

                    target.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    target.write_text(
                        change.content or "",
                        encoding="utf-8"
                    )

                elif change.change_type == ChangeType.MODIFY:
                    if not target.exists():
                        raise FileNotFoundError(
                            f"Arquivo não encontrado: {change.path}"
                        )

                    target.write_text(
                        change.content or "",
                        encoding="utf-8"
                    )

                elif change.change_type == ChangeType.DELETE:
                    if not target.exists():
                        raise FileNotFoundError(
                            f"Arquivo não encontrado: {change.path}"
                        )

                    target.unlink()

            transaction.status = TransactionStatus.COMMITTED

        except Exception:
            transaction.status = TransactionStatus.FAILED
            raise

        return transaction
