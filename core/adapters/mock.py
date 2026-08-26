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

        # =========================================================
        # REPAIR ENGINE
        # =========================================================
        #
        # O modo de reparo só é reconhecido quando a instrução
        # estrutural aparece no início do prompt. Isso evita que
        # conteúdo do contexto do projeto acione falsamente o
        # Repair Engine.
        #
        repair_marker = (
            "Você é o módulo de reparo automático do DevAgent."
        )

        if prompt.lstrip().startswith(repair_marker):
            instruction = ""

            marker = "Objetivo original:"

            if marker in prompt:
                instruction = (
                    prompt.split(marker, 1)[1]
                    .split("Erro:", 1)[0]
                    .strip()
                )

            path = self._extract_repair_path(
                instruction
            )

            if not path:
                path = "reparo.py"

            content = self._extract_invalid_content(
                instruction
            )

            return json.dumps(
                {
                    "diagnosis": (
                        "O arquivo contém conteúdo que "
                        "não constitui Python válido."
                    ),
                    "correction": (
                        "O conteúdo precisa ser substituído "
                        "por código Python válido."
                    ),
                    "risk": "baixo",
                    "action": "modify",
                    "path": path,
                    "content": content,
                },
                ensure_ascii=False,
            )

        # =========================================================
        # AI PLANNER
        # =========================================================

        marker = "INSTRUÇÃO DO USUÁRIO:"
        instruction = ""

        if marker in prompt:
            instruction = (
                prompt.split(marker, 1)[1]
                .split("CONTEXTO DO PROJETO:", 1)[0]
                .strip()
            )

        objective = instruction

        change = self._build_planner_change(
            instruction
        )

        changes = []

        if change is not None:
            changes.append(change)

        return json.dumps(
            {
                "objective": objective,
                "changes": changes,
                "tests": [],
                "risks": [],
            },
            ensure_ascii=False,
        )

    # =============================================================
    # AI PLANNER — MOCK
    # =============================================================

    def _build_planner_change(self, instruction: str):
        if not instruction:
            return None

        # ---------------------------------------------------------
        # DELETE
        # ---------------------------------------------------------

        delete_match = re.match(
            r"^\s*"
            r"(?:delete|apague|remova|remover)"
            r"\s+"
            r"(?:o\s+|a\s+|arquivo\s+)?"
            r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)"
            r"(?:\s+.*)?$",
            instruction,
            flags=re.IGNORECASE,
        )

        if delete_match:
            path = delete_match.group(1).strip(
                "\"'`.,;:"
            )

            return {
                "type": "delete",
                "path": path,
                "reason": instruction,
            }

        # ---------------------------------------------------------
        # MODIFY
        # ---------------------------------------------------------

        modify_match = re.match(
            r"^\s*"
            r"(?:modifique|modificar|altere|alterar|modify)"
            r"\s+"
            r"(?:o\s+|a\s+|arquivo\s+)?"
            r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)"
            r"(?:\s+(.*))?$",
            instruction,
            flags=re.IGNORECASE,
        )

        if modify_match:
            path = modify_match.group(1).strip(
                "\"'`.,;:"
            )

            content = (
                modify_match.group(2)
                or ""
            ).strip()

            return {
                "type": "modify",
                "path": path,
                "content": content,
                "reason": instruction,
            }

        # ---------------------------------------------------------
        # CREATE
        # ---------------------------------------------------------

        target = self._extract_create_target(
            instruction
        )

        if target:
            content = self._extract_create_content(
                instruction
            )

            # Compatibilidade com o comportamento anterior:
            # quando não existe marcador de conteúdo, utiliza
            # o restante da instrução após o nome do arquivo.
            if not content:
                create_match = re.match(
                    r"^\s*"
                    r"(?:crie|criar|create)"
                    r"\s+"
                    r"(?:um\s+)?"
                    r"(?:arquivo\s+)?"
                    r"(?:chamado\s+)?"
                    r"[A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+"
                    r"(?:\s+(.*))?$",
                    instruction,
                    flags=re.IGNORECASE,
                )

                if create_match:
                    content = (
                        create_match.group(1)
                        or ""
                    ).strip()

            return {
                "type": "create",
                "path": target,
                "content": content,
                "reason": instruction,
            }

        return None

    @staticmethod
    def _extract_create_target(instruction: str) -> str:
        """
        Reconhece formas comuns de criação:

        Crie app.py ...
        Crie um arquivo chamado app.py ...
        Crie arquivo app.py ...
        Criar arquivo app.py ...
        """

        patterns = (
            r"\b(?:crie|criar|create)\s+"
            r"(?:um\s+)?"
            r"(?:arquivo\s+)?"
            r"chamado\s+"
            r"([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)",

            r"\b(?:crie|criar|create)\s+"
            r"(?:um\s+)?"
            r"(?:arquivo\s+)?"
            r"([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                instruction,
                flags=re.IGNORECASE,
            )

            if match:
                return match.group(1).strip(
                    "\"'`.,;:"
                )

        return ""

    @staticmethod
    def _extract_create_content(
        instruction: str,
    ) -> str:
        lower = instruction.lower()

        markers = (
            " contendo ",
            " com conteúdo ",
            " com conteudo ",
        )

        for marker in markers:
            index = lower.find(marker)

            if index != -1:
                content = instruction[
                    index + len(marker):
                ].strip()

                if content:
                    return content

        return ""

    @staticmethod
    def _extract_repair_path(
        instruction: str,
    ) -> str:
        match = re.search(
            r"\b([A-Za-z0-9_.-]+\.py)\b",
            instruction,
        )

        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _extract_invalid_content(
        instruction: str,
    ) -> str:
        lower = instruction.lower()

        markers = (
            " contendo ",
            " com conteúdo ",
            " com conteudo ",
        )

        for marker in markers:
            index = lower.find(marker)

            if index != -1:
                content = instruction[
                    index + len(marker):
                ].strip()

                if content:
                    return content

        return "isto não é Python válido"
