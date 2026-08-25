import json
import re

from core.adapters.base import AIAdapter


class MockAdapter(AIAdapter):
    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError(
                "O prompt deve ser uma string."
            )

        if not prompt.strip():
            raise ValueError(
                "O prompt não pode ser vazio."
            )

        # ---------------------------------------------------------
        # Contrato do RepairEngine
        # ---------------------------------------------------------
        #
        # O RepairEngine usa um prompt diferente do AIPlanner.
        # O MockAdapter precisa reconhecer esse contrato e devolver
        # exatamente os campos esperados por RepairEngine.
        #
        # O conteúdo retornado aqui permanece inválido de propósito.
        # Isso permite testar o ciclo completo:
        #
        # falha -> análise -> tentativa -> teste -> falha ->
        # nova análise -> segunda tentativa -> limite -> rollback.
        #
        if "Você é o módulo de reparo automático do DevAgent." in prompt:
            instruction = ""

            marker = "Objetivo original:"
            if marker in prompt:
                instruction = prompt.split(
                    marker,
                    1,
                )[1].split(
                    "Erro:",
                    1,
                )[0].strip()

            path = self._extract_repair_path(instruction)

            if not path:
                path = "reparo.py"

            content = self._extract_invalid_content(instruction)

            return json.dumps(
                {
                    "diagnosis": "O arquivo contém conteúdo que não constitui Python válido.",
                    "correction": (
                        "O conteúdo precisa ser substituído por código Python válido."
                    ),
                    "risk": "baixo",
                    "action": "modify",
                    "path": path,
                    "content": content,
                },
                ensure_ascii=False,
            )

        # ---------------------------------------------------------
        # Contrato do AIPlanner
        # ---------------------------------------------------------

        marker = "INSTRUÇÃO DO USUÁRIO:"
        instruction = ""

        if marker in prompt:
            instruction = prompt.split(
                marker,
                1,
            )[1].split(
                "CONTEXTO DO PROJETO:",
                1,
            )[0].strip()

        objective = instruction
        changes = []

        words = instruction.split()
        target = None

        for index, word in enumerate(words):
            if word.lower() in (
                "crie",
                "criar",
                "create",
            ) and index + 1 < len(words):
                target = words[index + 1]
                break

        if target:
            target = target.strip(
                "\"'`.,;:"
            )

        content = ""

        lower = instruction.lower()

        if " contendo " in lower:
            content = instruction[
                lower.index(" contendo ") + 10:
            ]
        elif " com conteúdo " in lower:
            content = instruction[
                lower.index(" com conteúdo ") + 13:
            ]

        if target:
            changes.append(
                {
                    "type": "create",
                    "path": target,
                    "content": content,
                    "reason": instruction,
                }
            )

        return json.dumps(
            {
                "objective": objective,
                "changes": changes,
                "tests": [],
                "risks": [],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _extract_repair_path(instruction: str) -> str:
        """
        Extrai o primeiro nome de arquivo mencionado na instrução.
        """

        match = re.search(
            r"\b([A-Za-z0-9_.-]+\.py)\b",
            instruction,
        )

        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _extract_invalid_content(instruction: str) -> str:
        """
        Mantém o conteúdo originalmente problemático para que o mock
        possa exercitar o caminho de reparo que continua falhando.

        Exemplos:
            'Crie api_falha.py contendo isto não é Python válido'
        -> 'isto não é Python válido'

        Caso não seja possível extrair o conteúdo, utiliza uma
        expressão Python deliberadamente inválida.
        """

        lower = instruction.lower()

        if " contendo " in lower:
            content = instruction[
                lower.index(" contendo ") + 10:
            ].strip()

            if content:
                return content

        if " com conteúdo " in lower:
            content = instruction[
                lower.index(" com conteúdo ") + 13:
            ].strip()

            if content:
                return content

        return "isto não é Python válido"
