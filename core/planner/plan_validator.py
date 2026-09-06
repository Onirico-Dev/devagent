from pathlib import Path

from core.schemas.models import Change, ChangeType, Plan


class PlanValidator:
    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def _validate_test_path(self, test):
        if not isinstance(test, str):
            raise ValueError(
                "Cada teste deve ser uma string."
            )

        if not test.strip():
            raise ValueError(
                "Cada teste deve ser um caminho de arquivo pytest."
            )

        relative_path = Path(test)

        if relative_path.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {test}"
            )

        target = (self.root / relative_path).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {test}"
            ) from error

        name = relative_path.name

        if not name.endswith(".py"):
            raise ValueError(
                f"Teste inválido: {test}. "
                "O teste deve ser um arquivo Python."
            )

        if not (
            name.startswith("test_")
            or name.endswith("_test.py")
        ):
            raise ValueError(
                f"Teste inválido: {test}. "
                "O arquivo deve seguir o padrão "
                "test_*.py ou *_test.py."
            )

    def _validate_plan_structure(self, plan):
        if not isinstance(plan, Plan):
            raise TypeError(
                "O plano deve ser uma instância de Plan."
            )

        if not isinstance(plan.objective, str):
            raise ValueError(
                "Objetivo inválido."
            )

        if not plan.objective.strip():
            raise ValueError(
                "Objetivo não pode ser vazio."
            )

        if not isinstance(plan.changes, list):
            raise ValueError(
                "Changes deve ser uma lista"
            )

        if not isinstance(plan.tests, list):
            raise ValueError(
                "Tests deve ser uma lista."
            )

        if not isinstance(plan.risks, list):
            raise ValueError(
                "Risks deve ser uma lista."
            )

    def _validate_tests_and_risks(self, plan):
        for test in plan.tests:
            self._validate_test_path(test)

        for risk in plan.risks:
            if not isinstance(risk, str):
                raise ValueError(
                    "Cada risco deve ser uma string."
                )

    def _validate_change(self, change):
        if not isinstance(change, Change):
            raise TypeError(
                "Cada alteração deve ser uma instância de Change."
            )

        if not isinstance(change.change_type, ChangeType):
            raise ValueError(
                "Tipo de alteração inválido."
            )

        if not isinstance(change.path, str):
            raise ValueError(
                "Caminho da alteração deve ser uma string."
            )

        if not isinstance(change.reason, str):
            raise ValueError(
                "Motivo da alteração deve ser uma string."
            )

        if not change.path.strip():
            raise ValueError(
                "Alteração sem caminho."
            )

        self._validate_change_path(change)
        self._validate_change_content(change)

    def _validate_change_path(self, change):
        relative_path = Path(change.path)

        if relative_path.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {change.path}"
            )

        target = (
            self.root / relative_path
        ).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                "Caminho fora do projeto: "
                f"{change.path}"
            ) from error

    def _validate_change_content(self, change):
        if change.change_type == ChangeType.DELETE:
            if change.content is not None:
                raise ValueError(
                    "DELETE não pode possuir conteúdo."
                )
            return

        if change.change_type in (
            ChangeType.CREATE,
            ChangeType.MODIFY,
        ):
            if not isinstance(change.content, str):
                raise ValueError(
                    f"{change.change_type.value.upper()} "
                    "exige conteúdo textual."
                )

    def validate(self, plan: Plan):
        self._validate_plan_structure(plan)
        self._validate_tests_and_risks(plan)

        for change in plan.changes:
            self._validate_change(change)

        return True

    def validate_project_coherence(self, plan: Plan):
        self.validate(plan)

        for change in plan.changes:
            if change.change_type not in (
                ChangeType.MODIFY,
                ChangeType.DELETE,
            ):
                continue

            target = (
                self.root / Path(change.path)
            ).resolve()

            if not target.is_file():
                operation = change.change_type.value.upper()
                raise ValueError(
                    f"Arquivo inexistente para {operation}: "
                    f"{change.path}"
                )

        return True
