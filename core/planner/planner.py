from core.parser.command_parser import Command
from core.schemas.models import Change, ChangeType, Plan


class Planner:

    def create_plan(self, command: Command) -> Plan:

        if command.action == "create":

            change = Change(
                change_type=ChangeType.CREATE,
                path=command.target,
                reason=command.instruction,
            )

            return Plan(
                objective=command.raw,
                changes=[change],
                tests=[],
                risks=[],
            )

        if command.action == "modify":

            change = Change(
                change_type=ChangeType.MODIFY,
                path=command.target,
                reason=command.instruction,
            )

            return Plan(
                objective=command.raw,
                changes=[change],
                tests=[],
                risks=[],
            )

        if command.action == "delete":

            change = Change(
                change_type=ChangeType.DELETE,
                path=command.target,
                reason=command.instruction,
            )

            return Plan(
                objective=command.raw,
                changes=[change],
                tests=[],
                risks=["Operação destrutiva"],
            )

        return Plan(
            objective=command.raw,
            changes=[],
            tests=[],
            risks=[],
        )

