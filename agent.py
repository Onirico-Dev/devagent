import os

from core.pipeline import DevAgentPipeline
from core.adapters.mock import MockAdapter
from core.adapters.groq import GroqAdapter
from core.memory.session import Session
from core.schemas.models import Change, ChangeType, Transaction


class DevAgent:
    def __init__(self, root=".", ai_adapter=None):
        self.root = root
        self.session = Session()
        self.ai = ai_adapter or self._create_ai_adapter()
        self.pipeline = DevAgentPipeline(
            root=root,
            ai_adapter=self.ai,
        )

    def _create_ai_adapter(self):
        provider = os.getenv(
            "DEVAGENT_AI",
            "mock",
        ).strip().lower()

        if provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "DEVAGENT_AI=groq exige GROQ_API_KEY configurada."
                )

            return GroqAdapter(
                api_key=api_key
            )

        return MockAdapter()

    def process(self, instruction):
        self.session.add_instruction(
            instruction
        )

        plan = self.pipeline.process(
            instruction
        )

        result = {
            "instruction": instruction,
            "objective": plan.objective,
            "changes": [],
            "tests": plan.tests,
            "risks": plan.risks,
        }

        for change in plan.changes:
            result["changes"].append(
                {
                    "change_type": change.change_type.value,
                    "path": change.path,
                    "content": change.content,
                    "reason": change.reason,
                }
            )

        self.session.add_plan(
            result
        )

        return result


    def build_transaction_from_approved_plan(
        self,
        plan,
    ):
        if not isinstance(plan, dict):
            raise ValueError(
                "Plano aprovado inválido."
            )

        instruction = plan.get("instruction")

        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError(
                "Plano aprovado não possui instrução válida."
            )

        changes = plan.get("changes")

        if not isinstance(changes, list) or not changes:
            raise ValueError(
                "Plano aprovado não possui alterações."
            )

        converted_changes = []

        for change in changes:
            if not isinstance(change, dict):
                raise ValueError(
                    "Alteração inválida no plano aprovado."
                )

            change_type = change.get("change_type")
            path = change.get("path")
            content = change.get("content")
            reason = change.get("reason", "")

            if not isinstance(change_type, str):
                raise ValueError(
                    "Tipo de alteração inválido."
                )

            if not isinstance(path, str) or not path:
                raise ValueError(
                    "Alteração sem caminho."
                )

            try:
                change_type_enum = ChangeType(change_type)
            except ValueError as error:
                raise ValueError(
                    f"Tipo de alteração desconhecido: {change_type}"
                ) from error

            if change_type_enum != ChangeType.DELETE:
                if not isinstance(content, str):
                    raise ValueError(
                        f"Conteúdo inválido para alteração: {path}"
                    )

            converted_changes.append(
                Change(
                    change_type=change_type_enum,
                    path=path,
                    content=content,
                    reason=reason,
                )
            )

        transaction = Transaction(
            transaction_id="",
            changes=converted_changes,
        )

        return transaction

    def _transaction_from_plan(self, plan):
        if not plan.changes:
            raise ValueError(
                "Não é possível criar uma transação "
                "sem alterações."
            )

        transaction = Transaction(
            transaction_id="",
            changes=plan.changes,
        )

        return transaction

    def ask_ai(self, prompt):
        return self.ai.generate(
            prompt
        )


if __name__ == "__main__":
    agent = DevAgent()

    result = agent.process(
        "Crie app.py sistema de clientes"
    )

    print(result)
