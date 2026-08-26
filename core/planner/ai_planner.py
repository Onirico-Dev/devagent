import json

from core.schemas.models import (
    Change,
    ChangeType,
    Plan,
)


class AIPlanner:

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    def create_plan(
        self,
        instruction: str,
        context: str = "",
    ) -> Plan:

        prompt = f"""
Você é o planejador de um agente autônomo de programação.

Sua função é transformar a solicitação do usuário em um plano
estruturado de alterações no projeto.

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
    "teste que deve ser executado"
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
7. Não execute comandos.
8. Não altere o projeto.
9. Não inclua markdown.
10. Retorne somente o JSON.
11. Se a solicitação exigir uma alteração no projeto,
    "changes" NÃO pode ser uma lista vazia.
"""

        response = self.ai.generate(prompt)

        try:
            data = json.loads(response)
        except json.JSONDecodeError as error:
            raise ValueError(
                "A IA retornou um plano que não é JSON válido."
            ) from error

        return self._build_plan(
            data,
            instruction,
        )

    def _build_plan(
        self,
        data,
        instruction="",
    ):
        if not isinstance(data, dict):
            raise ValueError(
                "Plano da IA deve ser um objeto JSON."
            )

        objective = data.get(
            "objective",
            "",
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

        changes = []

        for item in changes_data:

            if not isinstance(item, dict):
                raise ValueError(
                    "Cada alteração deve ser um objeto."
                )

            change_type = item.get("type")
            path = item.get("path")
            content = item.get("content")
            reason = item.get(
                "reason",
                "",
            )

            try:
                change_type = ChangeType(
                    change_type
                )
            except ValueError as error:
                raise ValueError(
                    f"Tipo de alteração inválido: {change_type}"
                ) from error

            if not isinstance(path, str) or not path.strip():
                raise ValueError(
                    "Caminho da alteração inválido."
                )

            changes.append(
                Change(
                    change_type=change_type,
                    path=path,
                    content=content,
                    reason=reason,
                )
            )

        # Uma solicitação operacional não pode virar
        # silenciosamente uma transação vazia.
        if (
            isinstance(instruction, str)
            and instruction.strip()
            and self._requires_change(instruction)
            and not changes
        ):
            raise ValueError(
                "A IA retornou um plano sem alterações "
                "para uma solicitação que exige alteração."
            )

        return Plan(
            objective=objective,
            changes=changes,
            tests=tests,
            risks=risks,
        )

    @staticmethod
    def _requires_change(instruction: str) -> bool:
        lowered = instruction.strip().lower()

        prefixes = (
            "crie ",
            "criar ",
            "modifique ",
            "modificar ",
            "altere ",
            "alterar ",
            "delete ",
            "apague ",
            "remova ",
            "remover ",
        )

        return lowered.startswith(prefixes)
