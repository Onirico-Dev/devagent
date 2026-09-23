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

    def process(self, text: str, feedback_context: dict | None = None):
        command = self.parser.parse(text)

        if feedback_context is None:
            feedback_context = {}

        if not isinstance(feedback_context, dict):
            raise ValueError("Contexto de feedback inválido.")

        relevant_paths = []

        if command.action == "modify" and command.target:
            relevant_paths.append(command.target)

        transaction_metadata = feedback_context.get(
            "transaction_metadata",
            {},
        )

        if isinstance(transaction_metadata, dict):
            original_changes = transaction_metadata.get("changes", [])

            if isinstance(original_changes, list):
                for change in original_changes:
                    if not isinstance(change, dict):
                        continue

                    path = change.get("path")

                    if (
                        isinstance(path, str)
                        and path.strip()
                        and path not in relevant_paths
                    ):
                        relevant_paths.append(path)

        context = self.context.build(
            relevant_paths=relevant_paths,
        )

        if self.ai_planner is not None:
            plan = self.ai_planner.create_plan(
                instruction=text,
                context=context,
                feedback_context=feedback_context,
            )
        else:
            plan = self.planner.create_plan(
                command
            )

        self.validator.validate_project_coherence(
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
