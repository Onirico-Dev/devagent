from core.pipeline import DevAgentPipeline
from core.adapters.mock import MockAdapter
from core.memory.session import Session
from core.schemas.models import Transaction
from core.engine.repair_engine import RepairEngine


class DevAgent:

    def __init__(self, root="."):

        self.root = root

        self.pipeline = DevAgentPipeline(root)

        self.ai = MockAdapter()

        self.repair_engine = RepairEngine(
            self.ai
        )

        self.session = Session()

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

    def build_transaction(
        self,
        instruction,
    ):

        plan = self.pipeline.process(
            instruction
        )

        transaction = Transaction(
            transaction_id="",
            changes=plan.changes,
        )

        return transaction

    def analyze_failure(
        self,
        instruction,
        error,
        test_output,
    ):

        return self.repair_engine.analyze_failure(
            instruction=instruction,
            error=error,
            test_output=test_output,
        )

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
