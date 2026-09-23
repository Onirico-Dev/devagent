import json
import re

from core.adapters.base import AIAdapter


class MockAdapter(AIAdapter):
    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("O prompt deve ser uma string.")

        if not prompt.strip():
            raise ValueError("O prompt não pode ser vazio.")

        repair_marker = "Você é o módulo de reparo automático do DevAgent."

        if prompt.startswith(repair_marker):
            return self._generate_repair_response(prompt)

        if prompt.startswith("REPAIR REQUEST:"):
            return self._generate_repair_response(prompt)

        return self._generate_planner_response(prompt)

    def _generate_repair_response(self, prompt: str) -> str:
        repair_marker = "Você é o módulo de reparo automático do DevAgent."

        if not prompt.lstrip().startswith(repair_marker):
            return ""

        instruction = ""
        marker = "Objetivo original:"

        if marker in prompt:
            instruction = (
                prompt.split(marker, 1)[1]
                .split("Erro:", 1)[0]
                .strip()
            )

        path = self._extract_repair_path(instruction)

        if not path:
            path = "reparo.py"

        content = self._extract_create_content(instruction)

        if not content:
            content = self._extract_invalid_content(instruction)

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

    def _generate_planner_response(self, prompt: str) -> str:
        marker = "INSTRUÇÃO DO USUÁRIO:"
        context_marker = "CONTEXTO DO PROJETO:"
        feedback_marker = "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:"

        instruction = ""
        context = ""
        feedback_context = {}

        if marker in prompt:
            instruction = (
                prompt.split(marker, 1)[1]
                .split(context_marker, 1)[0]
                .strip()
            )

        if context_marker in prompt:
            context = prompt.split(context_marker, 1)[1]

        if feedback_marker in prompt:
            feedback_text = prompt.split(feedback_marker, 1)[1]

            if "Retorne SOMENTE JSON válido." in feedback_text:
                feedback_text = feedback_text.split(
                    "Retorne SOMENTE JSON válido.",
                    1,
                )[0]

            try:
                parsed = json.loads(feedback_text.strip())
            except json.JSONDecodeError:
                parsed = {}

            if isinstance(parsed, dict):
                feedback_context = parsed

        if feedback_context:
            return self._generate_feedback_response(
                instruction,
                context,
                feedback_context,
            )

        context = context.strip()
        objective = instruction

        changes = self._build_compound_create_changes(instruction)

        if not changes:
            change = self._build_planner_change(
                instruction,
                context,
            )
            changes = [change] if change is not None else []

        return json.dumps(
            {
                "objective": objective,
                "changes": changes,
                "tests": [],
                "risks": [],
            },
            ensure_ascii=False,
        )

    def _generate_feedback_response(
        self,
        instruction: str,
        context: str,
        feedback_context: dict,
    ) -> str:
        transaction_id = feedback_context.get("transaction_id", "")
        status = feedback_context.get("status", "")
        evidence = feedback_context.get("evidence", {})

        if not isinstance(evidence, dict):
            evidence = {}

        transaction_metadata = feedback_context.get(
            "transaction_metadata",
            {},
        )

        if not isinstance(transaction_metadata, dict):
            transaction_metadata = {}

        original_changes = transaction_metadata.get("changes", [])

        if not isinstance(original_changes, list):
            original_changes = []

        changes = []

        for original in original_changes:
            if not isinstance(original, dict):
                continue

            path = original.get("path")
            content = original.get("content")
            original_change_type = original.get(
                "change_type",
                original.get("type", "modify"),
            )

            if not isinstance(path, str) or not path.strip():
                continue

            if original_change_type not in {"create", "modify", "delete"}:
                original_change_type = "modify"

            change = {
                "type": original_change_type,
                "path": path,
                "reason": (
                    f"Correção da transação {transaction_id}: "
                    f"status '{status}'; "
                    f"falha: {evidence.get('error', 'erro de execução')}."
                ),
            }

            if isinstance(content, str):
                normalized_content = content

                marker = "com o conteúdo "
                if normalized_content.startswith(marker):
                    normalized_content = normalized_content[len(marker):]

                error = str(evidence.get("error", ""))
                tests_evidence = evidence.get("tests", {})

                if isinstance(tests_evidence, dict):
                    error = (
                        error
                        + "\n"
                        + str(tests_evidence.get("stderr", ""))
                        + "\n"
                        + str(tests_evidence.get("error", ""))
                    )

                if (
                    "SyntaxError" in error
                    and normalized_content.strip() == "def broken(:"
                ):
                    normalized_content = "def broken():\n    pass\n"

                change["content"] = normalized_content

            changes.append(change)

        return json.dumps(
            {
                "objective": (
                    f"Corrigir a transação {transaction_id} "
                    f"que terminou com status '{status}'."
                ),
                "changes": changes,
                "tests": [],
                "risks": [
                    "Correção requer aprovação humana."
                ],
            },
            ensure_ascii=False,
        )

    def _build_compound_create_changes(self, instruction: str):
        # Caso semântico conhecido: módulo + teste pytest.
        module_match = re.search(
            r"crie\s+(?:um\s+)?(?:módulo|arquivo)\s+"
            r"([A-Za-z0-9_.-]+\.py)\s+contendo\s+"
            r"(.+?)\s+e\s+"
            r"crie\s+(?:um\s+)?(?:módulo|arquivo)?\s*"
            r"([A-Za-z0-9_.-]+\.py)\s+contendo\s+"
            r"(.+)$",
            instruction.strip(),
            flags=re.IGNORECASE,
        )

        if module_match:
            module_path = module_match.group(1)
            module_description = module_match.group(2).strip()
            test_path = module_match.group(3)
            test_description = module_match.group(4).strip()

            function_match = re.search(
                r"função\s+([A-Za-z_][A-Za-z0-9_]*)"
                r"\s*\(([^)]*)\)"
                r".*?retorna\s+a\s+soma\s+dos\s+dois\s+valores",
                module_description,
                flags=re.IGNORECASE,
            )

            test_match = re.search(
                r"verifica\s+que\s+"
                r"([A-Za-z_][A-Za-z0-9_]*)"
                r"\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)"
                r"\s*retorna\s+(\d+)",
                test_description,
                flags=re.IGNORECASE,
            )

            if function_match and test_match:
                function_name = function_match.group(1)
                parameters = function_match.group(2).strip()
                left = test_match.group(2)
                right = test_match.group(3)
                expected = test_match.group(4)

                module_name = module_path.rsplit(".", 1)[0].replace("/", ".")

                return [
                    {
                        "type": "create",
                        "path": module_path,
                        "content": (
                            f"def {function_name}({parameters}):\n"
                            "    return a + b\n"
                        ),
                        "reason": instruction,
                    },
                    {
                        "type": "create",
                        "path": test_path,
                        "content": (
                            f"from {module_name} import {function_name}\n\n"
                            f"def test_{function_name}():\n"
                            f"    assert {function_name}({left}, {right}) == {expected}\n"
                        ),
                        "reason": instruction,
                    },
                ]

        # Caso geral: separa operações independentes e reutiliza
        # os construtores existentes de CREATE/MODIFY/DELETE.
        action_pattern = re.compile(
            r"\s+e\s+"
            r"(?=(?:crie|criar|create|modifique|modificar|"
            r"altere|alterar|modify|delete|apague|remova|remover)\b)",
            flags=re.IGNORECASE,
        )

        parts = action_pattern.split(instruction.strip())

        if len(parts) < 2:
            return []

        changes = []

        for part in parts:
            part = part.strip()

            if not part:
                continue

            change = self._build_planner_change(part, "")

            if change is None:
                return []

            changes.append(change)

        return changes if len(changes) >= 2 else []
    def _build_delete_change(self, instruction: str):
        delete_match = re.match(
            r"^\s*"
            r"(?:delete|apague|remova|remover)"
            r"\s+"
            r"(?:o\s+|a\s+)?(?:arquivo\s+)?"
            r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)"
            r"(?:\s+.*)?$",
            instruction,
            flags=re.IGNORECASE,
        )

        if not delete_match:
            return None

        path = delete_match.group(1).strip(
            "\"'`.,;:"
        )

        return {
            "type": "delete",
            "path": path,
            "reason": instruction,
        }

    def _build_modify_change(
        self,
        instruction: str,
        context: str = "",
    ):
        modify_match = re.match(
            r"^\s*"
            r"(?:modifique|modificar|altere|alterar|modify)"
            r"\s+"
            r"(?:o\s+|a\s+)?(?:arquivo\s+)?"
            r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+)"
            r"(?:\s+(.*))?$",
            instruction,
            flags=re.IGNORECASE,
        )

        if not modify_match:
            return None

        path = modify_match.group(1).strip(
            "\"'`.,;:"
        )

        request = (modify_match.group(2) or "").strip()
        content = request

        for prefix in (
            "com conteúdo ",
            "com conteudo ",
            "contendo ",
        ):
            if request.lower().startswith(prefix):
                content = request[len(prefix):].strip()
                break

        addition = None

        for prefix in (
            "adicionando ",
            "adicione ",
            "adicionar ",
        ):
            if request.lower().startswith(prefix):
                addition = request[len(prefix):].strip()
                break

        if addition and context:
            file_marker = f"=== ARQUIVO: {path} ===\n"

            if file_marker in context:
                existing = (
                    context.split(file_marker, 1)[1]
                    .split("=== ANÁLISE PYTHON ===", 1)[0]
                    .rstrip()
                )

                content = f"{existing}\n{addition}\n"

        return {
            "type": "modify",
            "path": path,
            "content": content,
            "reason": instruction,
        }

    def _extract_legacy_create_content(
        self,
        instruction: str,
    ) -> str:
        lower = instruction.lower()

        markers = (
            " contendo ",
            " com conteúdo ",
            " com o conteúdo ",
            " com conteudo ",
            " com o conteudo ",
        )

        for marker in markers:
            index = lower.find(marker)

            if index != -1:
                content = instruction[
                    index + len(marker):
                ].strip()

                if content:
                    return content

        match = re.match(
            r"^\s*(?:crie|criar|criar arquivo|create)"
            r"\s+(?:um\s+arquivo\s+)?"
            r"(?:chamado\s+)?"
            r"[A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+"
            r"\s+(.+?)\s*$",
            instruction,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

        return ""

    def _build_create_change(self, instruction: str):
        target = self._extract_create_path(instruction)

        if not target:
            return None

        content = self._extract_create_content(instruction)

        if not content:
            content = self._extract_legacy_create_content(instruction)

        return {
            "type": "create",
            "path": target,
            "content": content,
            "reason": instruction,
        }

    def _build_planner_change(
        self,
        instruction: str,
        context: str = "",
    ):
        if not instruction:
            return None

        change = self._build_delete_change(instruction)
        if change is not None:
            return change

        change = self._build_modify_change(
            instruction,
            context,
        )
        if change is not None:
            return change

        return self._build_create_change(instruction)

    @staticmethod
    def _extract_create_target(instruction: str) -> str:
        return MockAdapter._extract_create_path(instruction)

    @staticmethod
    def _extract_create_path(instruction: str) -> str:
        patterns = (
            r"\b(?:crie|criar|create)\s+"
            r"(?:um\s+|o\s+)?"
            r"(?:novo\s+)?"
            r"(?:arquivo|módulo)\s+"
            r"chamado\s+"
            r"([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)",

            r"\b(?:crie|criar|create)\s+"
            r"(?:um\s+|o\s+)?"
            r"(?:novo\s+)?"
            r"(?:arquivo|módulo)\s+"
            r"([A-Za-z0-9_.-]+\.[A-Za-z0-9_-]+)",

            r"\b(?:crie|criar|create)\s+"
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
        lower = instruction.lower().strip()

        natural_test_pattern = (
            r"um\s+teste\s+pytest\s+chamado\s+"
            r"test_smoke\s+que\s+faça\s+a\s+"
            r"asserção\s+de\s+que\s*2\s*\+\s*2\s+"
            r"(?:é|e)\s+igual\s+a\s+4"
        )

        if re.search(natural_test_pattern, lower):
            return (
                "def test_smoke():\n"
                "    assert 2 + 2 == 4"
            )

        markers = (
            " contendo ",
            " com conteúdo ",
            " com o conteúdo ",
            " com conteudo ",
            " com o conteudo ",
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
            " com o conteúdo ",
            " com conteudo ",
            " com o conteudo ",
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
