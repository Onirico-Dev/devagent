from core.pipeline import DevAgentPipeline
from core.adapters.mock import MockAdapter


class DevAgent:

    def __init__(self, root="."):
        self.pipeline = DevAgentPipeline(root)
        self.ai = MockAdapter()

    def understand(self, instruction):

        plan = self.pipeline.process(instruction)

        return {
            "instruction": instruction,
            "objective": plan.objective,
            "changes": [
                {
                    "type": change.change_type.value,
                    "path": change.path,
                    "reason": change.reason,
                }
                for change in plan.changes
            ],
            "risks": plan.risks,
        }

    def ask_ai(self, prompt):

        return self.ai.generate(prompt)


if __name__ == "__main__":

    agent = DevAgent()

    result = agent.understand(
        "Crie app.py sistema de clientes"
    )

    print(result)
