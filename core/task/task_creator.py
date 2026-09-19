class TaskCreator:
    """Valida planos produzidos pelo agente antes da criação da tarefa."""

    def __init__(self, security):
        self.security = security

    def validate_plan(self, result):
        if not isinstance(result, dict):
            raise ValueError(
                "Plano inválido retornado pelo agente."
            )

        changes = result.get("changes")
        if not isinstance(changes, list):
            raise ValueError(
                "Plano não possui lista de alterações."
            )

        for change in changes:
            if not isinstance(change, dict):
                raise ValueError(
                    "Alteração inválida no plano."
                )

            path = change.get("path")
            if not path:
                raise ValueError(
                    "Alteração sem caminho."
                )

            self.security.validate_path(path)

            content = change.get("content")
            if change.get("change_type") != "delete":
                if not isinstance(content, str):
                    raise ValueError(
                        f"Conteúdo inválido para alteração: {path}"
                    )

                self.security.validate_content(content)

        return result
