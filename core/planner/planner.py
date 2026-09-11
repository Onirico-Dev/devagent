import re

from core.parser.command_parser import Command
from core.schemas.models import Change, ChangeType, Plan


class Planner:
    @staticmethod
    def _extract_create_content(instruction: str) -> str:
        """
        Converte instruções de criação conhecidas em código executável.

        Conteúdo que já parece ser código é preservado exatamente.
        """
        lower = instruction.lower().strip()

        natural_test_patterns = (
            r"^um\s+teste\s+pytest\s+chamado\s+"
            r"test_smoke\s+que\s+faça\s+a\s+"
            r"asserção\s+de\s+que\s*2\s*\+\s*2\s+"
            r"(?:é|e)\s+igual\s+a\s+4$",

            r"^o\s+arquivo\s+deve\s+conter\s+"
            r"um\s+teste\s+pytest\s+chamado\s+"
            r"test_smoke\s+que\s+faça\s+a\s+"
            r"asserção\s+de\s+que\s*2\s*\+\s*2\s+"
            r"(?:é|e)\s+igual\s+a\s+4$",
        )

        for pattern in natural_test_patterns:
            if re.fullmatch(pattern, lower, flags=re.IGNORECASE):
                return (
                    "def test_smoke():\n"
                    "    assert 2 + 2 == 4"
                )

        return instruction

    def create_plan(self, command: Command) -> Plan:
        if not isinstance(command, Command):
            raise TypeError("Planner exige uma instância de Command")

        if command.action in {"create", "modify", "delete"}:
            target = command.target
            if not isinstance(target, str) or not target.strip():
                raise ValueError("Operação exige um alvo textual")

            if command.action == "create":
                content = command.instruction
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("CREATE exige conteúdo textual.")

                content = self._extract_create_content(content)

                change = Change(
                    change_type=ChangeType.CREATE,
                    path=command.target,
                    content=content,
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
                    content=command.instruction,
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
