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

        if change.change_type == ChangeType.DELETE:
            if not target.exists():
                raise FileNotFoundError(
                    f"Arquivo não encontrado: {change.path}"
                )

    def prepare(self, plan: Plan) -> list[Change]:
        for change in plan.changes:
            self.validate_change(change)

        return plan.changes
