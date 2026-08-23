from core.parser.command_parser import CommandParser
from core.planner.planner import Planner
from core.engine.change_engine import ChangeEngine
from core.memory.memory import Memory


class DevAgentPipeline:

    def __init__(self, root: str = "."):
        self.root = root
        self.parser = CommandParser()
        self.planner = Planner()
        self.engine = ChangeEngine(root)
        self.memory = Memory()

    def process(self, text: str):

        command = self.parser.parse(text)

        plan = self.planner.create_plan(command)

        changes = self.engine.prepare(plan)

        self.memory.add(
            "plan_created",
            {
                "command": command.raw,
                "action": command.action,
                "changes": len(changes),
            },
        )

        return plan

