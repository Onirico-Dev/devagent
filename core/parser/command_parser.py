from dataclasses import dataclass
import re


@dataclass
class Command:
    raw: str
    action: str
    target: str
    instruction: str


class CommandParser:

    ACTIONS = {
        "crie": "create",
        "criar": "create",
        "modifique": "modify",
        "modificar": "modify",
        "altere": "modify",
        "alterar": "modify",
        "delete": "delete",
        "apague": "delete",
        "remova": "delete",
        "remover": "delete",
    }

    ANALYZE_WORDS = {
        "analise",
        "análise",
    }

    def parse(self, text: str) -> Command:
        text = text.strip()

        if not text:
            raise ValueError("Comando vazio.")

        words = text.split(maxsplit=1)
        first = words[0].lower()

        # ---------------------------------------------------------
        # ANÁLISE
        # ---------------------------------------------------------
        if first in self.ANALYZE_WORDS:
            if len(words) == 1:
                return Command(
                    raw=text,
                    action="analyze",
                    target="",
                    instruction="",
                )

            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction=text,
            )

        # ---------------------------------------------------------
        # OPERAÇÃO
        # ---------------------------------------------------------
        action = self.ACTIONS.get(first)

        if action is None:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction=text,
            )

        # "Crie", "Modifique", "Delete", etc., sem alvo:
        # não constituem uma operação executável.
        if len(words) == 1:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction="",
            )

        remainder = words[1].strip()

        if not remainder:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction=text,
            )

        target, instruction = self._extract_target_and_instruction(
            remainder,
            action,
        )

        # Operação sem alvo também não é executável.
        if not target:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction=text,
            )

        return Command(
            raw=text,
            action=action,
            target=target,
            instruction=instruction,
        )

    @classmethod
    def _extract_target_and_instruction(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str]:

        patterns = [
            r"^um\s+arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^um\s+arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+([^\s\"'`]+)(?:\s+(.*))?$",
        ]

        for pattern in patterns:
            match = re.match(
                pattern,
                remainder,
                flags=re.IGNORECASE,
            )

            if match:
                target = cls._clean(match.group(1))

                if target.lower() in {
                    "de",
                    "do",
                    "da",
                    "dos",
                    "das",
                    "para",
                    "por",
                    "com",
                    "contendo",
                }:
                    continue

                instruction = cls._clean_instruction(
                    match.group(2) or ""
                )

                if action == "delete":
                    instruction = ""

                return target, instruction

        words = remainder.split(maxsplit=1)

        target = cls._clean(words[0])

        instruction = ""
        if len(words) > 1:
            instruction = cls._clean_instruction(words[1])

        if action == "delete":
            instruction = ""

        return target, instruction

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip("\"'`.,;:")

    @staticmethod
    def _clean_instruction(value: str) -> str:
        return value.strip()
