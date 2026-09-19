from core.supervisor import ApprovalStatus


class TaskCreator:
    def __init__(self, security, history, supervisor):
        self.security = security
        self.history = history
        self.supervisor = supervisor

    def validate_plan(self, result):
        if not isinstance(result, dict):
            raise ValueError("Plano inválido retornado pelo agente.")

        changes = result.get("changes")

        if not isinstance(changes, list):
            raise ValueError("Plano não possui lista de alterações.")

        for change in changes:
            if not isinstance(change, dict):
                raise ValueError("Alteração inválida no plano.")

            path = change.get("path")

            if not path:
                raise ValueError("Alteração sem caminho.")

            self.security.validate_path(path)

            content = change.get("content")

            if change.get("change_type") != "delete":
                if not isinstance(content, str):
                    raise ValueError(
                        f"Conteúdo inválido para alteração: {path}"
                    )

                self.security.validate_content(content)

    def create_or_reuse(self, instruction, result):
        normalized_instruction = " ".join(instruction.split())

        self.history._load()

        for task in self.history.list_pending():
            task_instruction = task.get("instruction")

            if not isinstance(task_instruction, str):
                continue

            if " ".join(task_instruction.split()) != normalized_instruction:
                continue

            return {
                "approval_id": task["approval_id"],
                "status": task["status"],
                "plan": task["plan"],
            }

        approval_id = self.supervisor.request_approval(result)

        self.history.create(
            approval_id=approval_id,
            instruction=instruction,
            plan=result,
        )

        return {
            "approval_id": approval_id,
            "status": ApprovalStatus.PENDING.value,
            "plan": result,
        }
