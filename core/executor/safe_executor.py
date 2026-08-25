from pathlib import Path

from core.schemas.models import ChangeType, TransactionStatus


class SafeExecutor:
    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()

    def _safe_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        target = (self.root / relative).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        return target

    def execute_change(self, change):
        target = self._safe_path(change.path)

        if change.change_type == ChangeType.CREATE:
            if target.exists():
                raise FileExistsError(
                    f"Arquivo já existe: {change.path}"
                )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                change.content or "",
                encoding="utf-8",
            )

        elif change.change_type == ChangeType.MODIFY:
            if not target.exists():
                raise FileNotFoundError(
                    f"Arquivo não encontrado: {change.path}"
                )

            if not target.is_file():
                raise ValueError(
                    f"Caminho não é um arquivo: {change.path}"
                )

            target.write_text(
                change.content or "",
                encoding="utf-8",
            )

        elif change.change_type == ChangeType.DELETE:
            if not target.exists():
                raise FileNotFoundError(
                    f"Arquivo não encontrado: {change.path}"
                )

            if not target.is_file():
                raise ValueError(
                    f"Caminho não é um arquivo: {change.path}"
                )

            target.unlink()

        else:
            raise ValueError(
                f"Tipo de alteração não suportado: {change.change_type}"
            )

    def execute(self, transaction):
        transaction.status = TransactionStatus.EXECUTING

        try:
            for change in transaction.changes:
                self.execute_change(change)

        except Exception:
            transaction.status = TransactionStatus.FAILED
            raise

        # IMPORTANTE:
        # A execução física das alterações NÃO significa que a
        # transação foi commitada.
        #
        # O commit somente ocorre depois que:
        # 1. os testes passam;
        # 2. o Git confirma o commit.
        #
        # Portanto, mantemos o estado EXECUTING aqui.
        return transaction
