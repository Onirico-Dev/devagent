from core.parser.command_parser import CommandParser
from core.planner.planner import Planner
from core.planner.ai_planner import AIPlanner
from core.planner.plan_validator import PlanValidator
from core.engine.change_engine import ChangeEngine
from core.context.project_context import ProjectContext
from core.memory.memory import Memory


class DevAgentPipeline:
    def __init__(
        self,
        root: str = ".",
        ai_adapter=None,
    ):
        self.root = root

        self.parser = CommandParser()
        self.planner = Planner()

        self.ai_planner = (
            AIPlanner(ai_adapter)
            if ai_adapter is not None
            else None
        )

        self.engine = ChangeEngine(root)
        self.validator = PlanValidator(root)
        self.context = ProjectContext(root)
        self.memory = Memory()

    def process(self, text: str):
        command = self.parser.parse(text)

        context = self.context.build()

        if self.ai_planner is not None:
            plan = self.ai_planner.create_plan(
                instruction=text,
                context=context,
            )
        else:
            plan = self.planner.create_plan(
                command
            )

        self.validator.validate(
            plan
        )

        changes = self.engine.prepare(
            plan
        )

        self.memory.add(
            "plan_created",
            {
                "command": command.raw,
                "action": command.action,
                "changes": len(changes),
                "ai_planner": (
                    self.ai_planner is not None
                ),
            },
        )

        return plan
