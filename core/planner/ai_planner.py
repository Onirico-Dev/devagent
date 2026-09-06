import json

from core.schemas.models import (
    Change,
    ChangeType,
    Plan,
)


class AIPlanner:
    MAX_CONTEXT_CHARS = 12000

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    def create_plan(
        self,
        instruction: str,
        context: str = "",
    ) -> Plan:
        if not isinstance(context, str):
            context = ""

        if len(context) > self.MAX_CONTEXT_CHARS:
            context = (
                context[:self.MAX_CONTEXT_CHARS]
                + "\n\n=== CONTEXTO TRUNCADO ==="
            )

        prompt = f"""
Você é o planejador de um agente autônomo de programação.
Sua função é transformar a solicitação do usuário em um plano estruturado
de alterações no projeto.

INSTRUÇÃO DO USUÁRIO:
{instruction}

CONTEXTO DO PROJETO:
{context}

Retorne SOMENTE JSON válido.

Formato obrigatório:
{{
    "objective": "objetivo da tarefa",
    "changes": [
        {{
            "type": "create | modify | delete",
            "path": "caminho relativo",
            "content": "conteúdo completo quando necessário",
            "reason": "motivo da alteração"
        }}
    ],
    "tests": [
        "caminho relativo de um arquivo pytest"
    ],
    "risks": [
        "risco identificado"
    ]
}}

Regras:
1. Nunca use caminhos absolutos.
2. Nunca use ../ para sair do projeto.
3. Não invente arquivos sem necessidade.
4. Para MODIFY, forneça o conteúdo completo do arquivo.
5. Para CREATE, forneça o conteúdo completo.
6. Para DELETE, não forneça conteúdo.
7. Quando a instrução do usuário especificar conteúdo entre aspas,
   preserve as aspas como parte literal do conteúdo.
8. Não remova, interprete ou normalize aspas, acentos, pontuação ou
   delimitadores fornecidos pelo usuário quando fizerem parte do conteúdo.
9. Não execute comandos.
10. Não altere o projeto.
11. Não inclua markdown.
12. Retorne somente o JSON.
13. Se a solicitação exigir uma alteração no projeto,
    "changes" NÃO pode ser uma lista vazia.
14. O campo "tests" deve conter somente caminhos relativos de arquivos
    Python destinados ao pytest.
15. Cada teste deve seguir o padrão test_*.py ou *_test.py.
16. Não coloque comandos como "pytest -q" ou "python -m pytest" em "tests".
17. Não coloque asserções, expressões ou código Python em "tests".
18. Nunca use caminhos absolutos ou caminhos contendo ../ em "tests".
"""

        response = self.ai.generate(prompt)

        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError(
                "A IA retornou um plano que não é JSON válido."
            ) from error

        return self._build_plan(
            data,
            instruction,
        )

    @staticmethod
    def _validate_plan_data(data):
        if not isinstance(data, dict):
            raise ValueError(
                "Plano da IA deve ser um objeto JSON."
            )

        objective = data.get(
            "objective",
            "",
        )

        if not isinstance(objective, str):
            raise ValueError(
                "Objetivo inválido."
            )

        if not objective.strip():
            raise ValueError(
                "Objetivo não pode ser vazio."
            )

        changes_data = data.get(
            "changes",
            [],
        )
        tests = data.get(
            "tests",
            [],
        )
        risks = data.get(
            "risks",
            [],
        )

        if not isinstance(changes_data, list):
            raise ValueError(
                "Campo 'changes' deve ser uma lista."
            )

        if not isinstance(tests, list):
            raise ValueError(
                "Campo 'tests' deve ser uma lista."
            )

        if not isinstance(risks, list):
            raise ValueError(
                "Campo 'risks' deve ser uma lista."
            )

        return objective, changes_data, tests, risks

    def _validate_plan_tests_and_risks(
        self,
        tests,
        risks,
    ):
        for test in tests:
            self._validate_test_reference(test)

        for risk in risks:
            if not isinstance(risk, str):
                raise ValueError(
                    "Cada risco deve ser uma string."
                )

    @staticmethod
    def _validate_change_item(item):
        if not isinstance(item, dict):
            raise ValueError(
                "Cada alteração deve ser um objeto."
            )

        change_type = item.get("change_type")

        if change_type is None:
            change_type = item.get("type")

        path = item.get("path")
        content = item.get("content")
        reason = item.get(
            "reason",
            "",
        )

        try:
            change_type = ChangeType(change_type)
        except ValueError as error:
            raise ValueError(
                f"Tipo de alteração inválido: {change_type}"
            ) from error

        if not isinstance(path, str) or not path.strip():
            raise ValueError(
                "Caminho da alteração inválido."
            )

        if not isinstance(reason, str):
            raise ValueError(
                "Motivo da alteração deve ser uma string."
            )

        if change_type == ChangeType.DELETE:
            if content is not None:
                raise ValueError(
                    "DELETE não pode possuir conteúdo."
                )

        elif change_type in (
            ChangeType.CREATE,
            ChangeType.MODIFY,
        ):
            if not isinstance(content, str):
                raise ValueError(
                    f"{change_type.value.upper()} "
                    "exige conteúdo textual."
                )

        return Change(
            change_type=change_type,
            path=path,
            content=content,
            reason=reason,
        )

    def _build_changes(self, changes_data):
        return [
            self._validate_change_item(item)
            for item in changes_data
        ]

    def _validate_required_changes(
        self,
        instruction,
        changes,
    ):
        if (
            isinstance(instruction, str)
            and instruction.strip()
            and self._requires_change(instruction)
            and not changes
        ):
            raise ValueError(
                "A solicitação exige alteração no projeto, "
                "mas a IA retornou um plano sem alterações."
            )

    def _build_plan(
        self,
        data,
        instruction="",
    ):
        (
            objective,
            changes_data,
            tests,
            risks,
        ) = self._validate_plan_data(data)

        self._validate_plan_tests_and_risks(
            tests,
            risks,
        )

        changes = self._build_changes(
            changes_data,
        )

        self._validate_required_changes(
            instruction,
            changes,
        )

        return Plan(
            objective=objective,
            changes=changes,
            tests=tests,
            risks=risks,
        )

    def _validate_test_reference(
        self,
        test,
    ):
        if not isinstance(test, str):
            raise ValueError(
                "Cada teste deve ser uma string."
            )

        if not test.strip():
            raise ValueError(
                "Cada teste deve ser um caminho de arquivo pytest."
            )

        normalized = test.replace("\\", "/")

        if normalized.startswith("/"):
            raise ValueError(
                f"Caminho absoluto não permitido: {test}"
            )

        parts = normalized.split("/")

        if ".." in parts:
            raise ValueError(
                f"Caminho fora do projeto: {test}"
            )

        name = parts[-1]

        if not name.endswith(".py"):
            raise ValueError(
                f"Teste inválido: {test}. "
                "O teste deve ser um arquivo Python."
            )

        if not (
            name.startswith("test_")
            or name.endswith("_test.py")
        ):
            raise ValueError(
                f"Teste inválido: {test}. "
                "O arquivo deve seguir o padrão "
                "test_*.py ou *_test.py."
            )

    def _requires_change(
        self,
        instruction: str,
    ) -> bool:
        operational_terms = (
            "criar",
            "crie",
            "create",
            "adicionar",
            "adicione",
            "alterar",
            "altere",
            "modificar",
            "modifique",
            "editar",
            "edite",
            "corrigir",
            "corrija",
            "remover",
            "remova",
            "deletar",
            "delete",
        )

        text = instruction.lower()

        return any(
            term in text
            for term in operational_terms
        )
