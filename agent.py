import os

from core.pipeline import DevAgentPipeline
from core.adapters.mock import MockAdapter
from core.adapters.groq import GroqAdapter
from core.memory.session import Session
from core.schemas.models import Transaction


class DevAgent:

    def __init__(self, root="."):
        self.root = root
        self.pipeline = DevAgentPipeline(root)
        self.session = Session()

        self.ai = self._create_ai_adapter()

    def _create_ai_adapter(self):

        api_key = os.getenv("GROQ_API_KEY")

        if api_key:
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

            result["changes"].append({
                "type": change.change_type.value,
                "path": change.path,
                "reason": change.reason,
            })

        self.session.add_plan(
            result
        )

        return result

    def build_transaction(self, instruction):

        plan = self.pipeline.process(
            instruction
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
