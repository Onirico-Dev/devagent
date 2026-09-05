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

    RESERVED_TARGET_WORDS = {
        "de",
        "do",
        "da",
        "dos",
        "das",
        "para",
        "por",
        "com",
        "contendo",
    }

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip("\"'`.,;:")

    @staticmethod
    def _clean_instruction(value: str) -> str:
        # Remove pontuação separadora antes da instrução.
        # Ex.: '"teste.py",   conteúdo' -> 'conteúdo'
        return value.lstrip(" \t.,;:").strip()

    @staticmethod
    def _clear_instruction_for_delete(action: str, instruction: str) -> str:
        if action == "delete":
            return ""
        return instruction

    @classmethod
    def _extract_explicit_target(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str] | None:
        patterns = [
            r"^um\s+arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^um\s+arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
        ]

        for pattern in patterns:
            match = re.match(
                pattern,
                remainder,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            target = cls._clean(match.group(1))
            instruction = cls._clean_instruction(
                match.group(2) or ""
            )
            instruction = cls._clear_instruction_for_delete(
                action,
                instruction,
            )
            return target, instruction

        return None

    @classmethod
    def _extract_quoted_target(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str] | None:
        patterns = [
            r'^arquivo\s+[\"\']([^\"\']+)[\"\']\s*,?\s*(.*)?$',
            r"^arquivo\s+`([^`]+)`\s*,?\s*(.*)?$",
        ]

        for pattern in patterns:
            match = re.match(
                pattern,
                remainder,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            target = cls._clean(match.group(1))
            instruction = cls._clean_instruction(
                match.group(2) or ""
            )
            instruction = cls._clear_instruction_for_delete(
                action,
                instruction,
            )
            return target, instruction

        return None

    @classmethod
    def _extract_reserved_after_arquivo(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str] | None:
        pattern = (
            r"^arquivo\s+"
            r"(de|do|da|dos|das|para|por|com|contendo)"
            r"(?:\s+(.*))?$"
        )

        match = re.match(
            pattern,
            remainder,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        target = cls._clean(match.group(1))
        instruction = cls._clean_instruction(
            match.group(2) or ""
        )
        instruction = cls._clear_instruction_for_delete(
            action,
            instruction,
        )
        return target, instruction

    @classmethod
    def _extract_generic_file_target(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str] | None:
        match = re.match(
            r"^arquivo\s+([^\s\"'`]+)(?:\s+(.*))?$",
            remainder,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        target = cls._clean(match.group(1))
        instruction = cls._clean_instruction(
            match.group(2) or ""
        )
        instruction = cls._clear_instruction_for_delete(
            action,
            instruction,
        )
        return target, instruction

    @classmethod
    def _extract_fallback_target(
        cls,
        remainder: str,
        action: str,
    ) -> tuple[str, str]:
        words = remainder.split(maxsplit=1)

        target = cls._clean(words[0])

        if len(words) > 1:
            instruction = cls._clean_instruction(words[1])
        else:
            instruction = ""

        instruction = cls._clear_instruction_for_delete(
            action,
            instruction,
        )
        return target, instruction

    def parse(self, text: str) -> Command:
        if not isinstance(text, str):
            raise ValueError("Comando deve ser uma string.")

        text = text.strip()

        if not text:
            raise ValueError("Comando vazio.")

        words = text.split(maxsplit=1)
        first = words[0].lower()

        # ANÁLISE
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

        # OPERAÇÃO
        action = self.ACTIONS.get(first)

        if action is None:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction=text,
            )

        if len(words) == 1:
            return Command(
                raw=text,
                action="analyze",
                target="",
                instruction="",
            )

        remainder = words[1].strip()

        target, instruction = self._extract_target_and_instruction(
            remainder,
            action,
        )

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
        result = cls._extract_explicit_target(
            remainder,
            action,
        )
        if result is not None:
            return result

        result = cls._extract_quoted_target(
            remainder,
            action,
        )
        if result is not None:
            return result

        result = cls._extract_reserved_after_arquivo(
            remainder,
            action,
        )
        if result is not None:
            return result

        result = cls._extract_generic_file_target(
            remainder,
            action,
        )
        if result is not None:
            return result

        return cls._extract_fallback_target(
            remainder,
            action,
        )
