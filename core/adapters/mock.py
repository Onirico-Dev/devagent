import json

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

        # O Mock simula uma resposta estruturada
        # compatível com o contrato esperado pelo AIPlanner.
        #
        # Para os testes básicos, extraímos a instrução
        # diretamente do prompt.

        instruction = ""

        marker = "INSTRUÇÃO DO USUÁRIO:"

        if marker in prompt:

            instruction = prompt.split(
                marker,
                1
            )[1].split(
                "CONTEXTO DO PROJETO:",
                1
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

            content = None

            lower = instruction.lower()

            if " contendo " in lower:

                content = instruction[
                    lower.index(" contendo ") + 10:
                ]

            elif " com conteúdo " in lower:

                content = instruction[
                    lower.index(" com conteúdo ") + 13:
                ]

            if content:
                changes.append({
                    "type": "create",
                    "path": target,
                    "content": content,
                    "reason": instruction,
                })

        return json.dumps(
            {
                "objective": objective,
                "changes": changes,
                "tests": [],
                "risks": [],
            },
            ensure_ascii=False,
        )
