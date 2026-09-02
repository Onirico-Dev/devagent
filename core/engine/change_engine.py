from pathlib import Path

from core.schemas.models import Change, ChangeType, Plan


class ChangeEngine:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def validate_change(self, change: Change) -> None:
        target = (self.root / change.path).resolve()

        if not target.is_relative_to(self.root):
            raise ValueError(
                f"Caminho fora do projeto: {change.path}"
            )

        if change.change_type == ChangeType.CREATE:
            if target.exists():
                raise FileExistsError(
                    f"Arquivo já existe: {change.path}"
                )
            return

        if change.change_type == ChangeType.MODIFY:
            if not target.exists():
                raise FileNotFoundError(
                    f"Arquivo não encontrado: {change.path}"
                )

            if not target.is_file():
                raise IsADirectoryError(
                    f"Caminho não é um arquivo: {change.path}"
                )

            return

        if change.change_type == ChangeType.DELETE:
            if not target.exists():
                raise FileNotFoundError(
                    f"Arquivo não encontrado: {change.path}"
                )

            if not target.is_file():
                raise IsADirectoryError(
                    f"Caminho não é um arquivo: {change.path}"
                )

            return

        raise ValueError(
            f"Tipo de alteração inválido: {change.change_type}"
        )

    def prepare(self, plan: Plan) -> list[Change]:
        for change in plan.changes:
            self.validate_change(change)

        return plan.changes
