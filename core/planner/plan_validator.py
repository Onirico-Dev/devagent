from pathlib import Path

from core.schemas.models import (
    ChangeType,
    Plan,
)


class PlanValidator:
    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def validate(self, plan: Plan):
        if not isinstance(plan, Plan):
            raise TypeError(
                "O plano deve ser uma instância de Plan."
            )

        if not isinstance(plan.objective, str):
            raise ValueError(
                "Objetivo inválido."
            )

        if not isinstance(plan.changes, list):
            raise ValueError(
                "Changes deve ser uma lista."
            )

        for change in plan.changes:
            if not change.path:
                raise ValueError(
                    "Alteração sem caminho."
                )

            target = (
                self.root / change.path
            ).resolve()

            try:
                target.relative_to(
                    self.root
                )
            except ValueError as error:
                raise ValueError(
                    "Caminho fora do projeto: "
                    f"{change.path}"
                ) from error

            if change.change_type == ChangeType.DELETE:
                if change.content is not None:
                    raise ValueError(
                        "DELETE não pode possuir conteúdo."
                    )

            elif change.change_type in (
                ChangeType.CREATE,
                ChangeType.MODIFY,
            ):
                if not isinstance(
                    change.content,
                    str,
                ):
                    raise ValueError(
                        f"{change.change_type.value.upper()} "
                        "exige conteúdo textual."
                    )

        return True
