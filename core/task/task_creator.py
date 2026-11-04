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
        if not isinstance(changes, list) or not changes:
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

    @staticmethod
    def _normalize_instruction(instruction):
        if not isinstance(instruction, str):
            return None
        return " ".join(instruction.split())

    @staticmethod
    def _plans_equal(left, right):
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False

        return (
            left.get("objective") == right.get("objective")
            and left.get("tests", []) == right.get("tests", [])
            and left.get("risks", []) == right.get("risks", [])
            and left.get("changes", []) == right.get("changes", [])
        )

    def _create_or_recover_task(
        self,
        approval_id,
        instruction,
        plan,
        idempotency_key=None,
    ):
        kwargs = {
            "approval_id": approval_id,
            "instruction": instruction,
            "plan": plan,
        }
        if idempotency_key is not None:
            kwargs["idempotency_key"] = idempotency_key

        try:
            self.history.create(**kwargs)
        except ValueError as exc:
            duplicate_errors = {
                "Tarefa já existe.",
                "Chave de idempotência já utilizada.",
            }
            if (
                idempotency_key is None
                or str(exc) not in duplicate_errors
            ):
                raise

            self.history.refresh()
            matches = [
                task
                for task in self.history.list_all()
                if (
                    isinstance(task, dict)
                    and task.get("idempotency_key") == idempotency_key
                )
            ]

            if len(matches) > 1:
                raise RuntimeError(
                    "Chave de idempotência associada a múltiplas tarefas."
                ) from exc

            if not matches:
                raise

            task = matches[0]

            if str(task.get("approval_id")) != str(approval_id):
                raise RuntimeError(
                    "Chave de idempotência associada a uma aprovação diferente."
                ) from exc

            if (
                self._normalize_instruction(task.get("instruction"))
                != self._normalize_instruction(instruction)
                or not self._plans_equal(task.get("plan"), plan)
            ):
                raise ValueError(
                    "Chave de idempotência reutilizada com dados diferentes."
                ) from exc

            return {
                "approval_id": task["approval_id"],
                "status": task["status"],
                "plan": task["plan"],
            }

        return {
            "approval_id": str(approval_id),
            "status": ApprovalStatus.PENDING.value,
            "plan": plan,
        }

    def _find_orphan_approval(
        self,
        result,
        instruction,
        idempotency_key=None,
    ):
        normalized_instruction = self._normalize_instruction(instruction)
        if not normalized_instruction:
            return None

        pending = self.supervisor.list_pending()
        if not isinstance(pending, dict):
            return None

        matches = []
        for approval_id, request in pending.items():
            if not isinstance(request, dict):
                continue
            if request.get("idempotency_key") != idempotency_key:
                continue

            request_instruction = self._normalize_instruction(
                request.get("instruction")
            )
            if request_instruction != normalized_instruction:
                continue
            if not self._plans_equal(request.get("plan"), result):
                continue
            matches.append((approval_id, request))

        if len(matches) > 1:
            if idempotency_key is not None:
                raise RuntimeError(
                    "Chave de idempotência associada a múltiplas aprovações."
                )
            return None
        if not matches:
            return None

        approval_id, request = matches[0]
        return {
            "approval_id": approval_id,
            "status": request["status"],
            "plan": request["plan"],
        }

    def find_existing_by_idempotency_key(self, instruction, idempotency_key):
        normalized_instruction = self._normalize_instruction(instruction)

        if not normalized_instruction:
            raise ValueError("Instrução inválida.")

        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
        ):
            raise ValueError("Chave de idempotência inválida.")

        idempotency_key = idempotency_key.strip()

        self.history._load()

        matches = [
            task
            for task in self.history.list_all()
            if (
                isinstance(task, dict)
                and task.get("idempotency_key") == idempotency_key
            )
        ]

        if len(matches) > 1:
            raise RuntimeError(
                "Chave de idempotência associada a múltiplas tarefas."
            )

        if matches:
            task = matches[0]
            task_instruction = self._normalize_instruction(
                task.get("instruction")
            )

            if task_instruction != normalized_instruction:
                raise ValueError(
                    "Chave de idempotência reutilizada com dados diferentes."
                )

            return {
                "approval_id": task["approval_id"],
                "status": task["status"],
                "plan": task["plan"],
            }

        pending = self.supervisor.list_pending()

        if not isinstance(pending, dict):
            return None

        orphan_matches = [
            (approval_id, request)
            for approval_id, request in pending.items()
            if (
                isinstance(request, dict)
                and request.get("idempotency_key") == idempotency_key
            )
        ]

        if len(orphan_matches) > 1:
            raise RuntimeError(
                "Chave de idempotência associada a múltiplas aprovações."
            )

        if not orphan_matches:
            return None

        approval_id, request = orphan_matches[0]
        request_instruction = self._normalize_instruction(
            request.get("instruction")
        )

        if request_instruction != normalized_instruction:
            raise ValueError(
                "Chave de idempotência reutilizada com dados diferentes."
            )

        plan = request.get("plan")
        if not isinstance(plan, dict):
            raise RuntimeError(
                "Plano inválido na aprovação órfã."
            )

        return self._create_or_recover_task(
            approval_id=approval_id,
            instruction=instruction,
            plan=plan,
            idempotency_key=idempotency_key,
        )

    def create_or_reuse(self, instruction, result, idempotency_key=None):
        normalized_instruction = self._normalize_instruction(instruction)
        if not normalized_instruction:
            raise ValueError("Instrução inválida.")

        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise ValueError("Chave de idempotência inválida.")
            idempotency_key = idempotency_key.strip()

        self.history._load()

        if idempotency_key is not None:
            matches = [
                task for task in self.history.list_all()
                if isinstance(task, dict)
                and task.get("idempotency_key") == idempotency_key
            ]
            if len(matches) > 1:
                raise RuntimeError(
                    "Chave de idempotência associada a múltiplas tarefas."
                )
            if matches:
                task = matches[0]
                task_instruction = self._normalize_instruction(
                    task.get("instruction")
                )
                if (
                    task_instruction != normalized_instruction
                    or not self._plans_equal(task.get("plan"), result)
                ):
                    raise ValueError(
                        "Chave de idempotência reutilizada com dados diferentes."
                    )
                return {
                    "approval_id": task["approval_id"],
                    "status": task["status"],
                    "plan": task["plan"],
                }
        else:
            for task in self.history.list_pending():
                if task.get("idempotency_key") != idempotency_key:
                    continue
                task_instruction = self._normalize_instruction(
                    task.get("instruction")
                )
                if task_instruction != normalized_instruction:
                    continue
                if not self._plans_equal(task.get("plan"), result):
                    continue
                return {
                    "approval_id": task["approval_id"],
                    "status": task["status"],
                    "plan": task["plan"],
                }

        orphan = self._find_orphan_approval(
            result,
            instruction,
            idempotency_key=idempotency_key,
        )
        if orphan is not None:
            return self._create_or_recover_task(
                approval_id=orphan["approval_id"],
                instruction=instruction,
                plan=result,
                idempotency_key=idempotency_key,
            )

        if idempotency_key is None:
            approval_id = self.supervisor.request_approval(
                result,
                instruction=instruction,
            )
        else:
            approval_id = self.supervisor.request_approval(
                result,
                instruction=instruction,
                idempotency_key=idempotency_key,
            )

        return self._create_or_recover_task(
            approval_id=approval_id,
            instruction=instruction,
            plan=result,
            idempotency_key=idempotency_key,
        )
