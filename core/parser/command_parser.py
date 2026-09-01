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

        # ---------------------------------------------------------
        # 1. Formas explícitas com "chamado" / "de nome"
        #
        # Essas regras precisam vir ANTES de qualquer interpretação
        # genérica de "arquivo <palavra>".
        # ---------------------------------------------------------
        explicit_patterns = [
            r"^um\s+arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^um\s+arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+chamado\s+([^\s\"'`]+)(?:\s+(.*))?$",
            r"^arquivo\s+de\s+nome\s+([^\s\"'`]+)(?:\s+(.*))?$",
        ]

        for pattern in explicit_patterns:
            match = re.match(
                pattern,
                remainder,
                flags=re.IGNORECASE,
            )

            if match:
                target = cls._clean(match.group(1))
                instruction = cls._clean_instruction(
                    match.group(2) or ""
                )

                if action == "delete":
                    instruction = ""

                return target, instruction

        # ---------------------------------------------------------
        # 2. Alvo entre aspas/crases
        #
        # Ex.:
        #   arquivo "teste.py", conteúdo
        # ---------------------------------------------------------
        quoted_patterns = [
            r'^arquivo\s+["\']([^"\']+)["\']\s*,?\s*(.*)?$',
            r"^arquivo\s+`([^`]+)`\s*,?\s*(.*)?$",
        ]

        for pattern in quoted_patterns:
            match = re.match(
                pattern,
                remainder,
                flags=re.IGNORECASE,
            )

            if match:
                target = cls._clean(match.group(1))
                instruction = cls._clean_instruction(
                    match.group(2) or ""
                )

                if action == "delete":
                    instruction = ""

                return target, instruction

        # ---------------------------------------------------------
        # 3. Forma especial preservada pelos testes:
        #
        #   "arquivo de arquivo.py conteúdo"
        #
        # Aqui o "de" é tratado como alvo literal.
        #
        # Importante: esta regra vem DEPOIS de "arquivo de nome",
        # portanto não captura:
        #
        #   arquivo de nome teste.py
        # ---------------------------------------------------------
        reserved_after_arquivo = re.match(
            r"^arquivo\s+"
            r"(de|do|da|dos|das|para|por|com|contendo)"
            r"(?:\s+(.*))?$",
            remainder,
            flags=re.IGNORECASE,
        )

        if reserved_after_arquivo:
            target = cls._clean(
                reserved_after_arquivo.group(1)
            )
            instruction = cls._clean_instruction(
                reserved_after_arquivo.group(2) or ""
            )

            if action == "delete":
                instruction = ""

            return target, instruction

        # ---------------------------------------------------------
        # 4. Forma genérica:
        #
        #   arquivo teste.py conteúdo
        #
        # "arquivo" é apenas o marcador linguístico; o segundo
        # token é o alvo.
        # ---------------------------------------------------------
        generic_file = re.match(
            r"^arquivo\s+([^\s\"'`]+)(?:\s+(.*))?$",
            remainder,
            flags=re.IGNORECASE,
        )

        if generic_file:
            target = cls._clean(generic_file.group(1))
            instruction = cls._clean_instruction(
                generic_file.group(2) or ""
            )

            if action == "delete":
                instruction = ""

            return target, instruction

        # ---------------------------------------------------------
        # 5. Forma iniciada diretamente por uma palavra reservada.
        #
        # Ex.:
        #   de arquivo.py conteúdo
        #
        # O comportamento esperado pelos testes é preservar a
        # palavra reservada como alvo.
        # ---------------------------------------------------------
        words = remainder.split(maxsplit=1)

        target = cls._clean(words[0])

        if len(words) > 1:
            instruction = cls._clean_instruction(words[1])
        else:
            instruction = ""

        if action == "delete":
            instruction = ""

        return target, instruction
