import json
import re
from pathlib import Path

from core.planner.local_edits import (
    LocalEditAnchorError, content_hash, copy_sources, expand_local_edits,
)
from core.planner.request_intent import has_requested_changes, is_read_only_request

from core.schemas.models import (
    Change,
    ChangeType,
    Plan,
)


class AIPlanner:
    MAX_CONTEXT_CHARS = 262144

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    @staticmethod
    def _extract_modify_target(instruction: str) -> str | None:
        match = re.search(
            r"(?:modifique|modificar|altere|alterar|modify)\s+"
            r"(?:o\s+|a\s+)?(?:arquivo\s+)?"
            r"([A-Za-z0-9_./-]+)",
            instruction,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        return match.group(1).strip("\"'`.,;:")

    def _preserve_modify_target_context(
        self,
        instruction: str,
        context: str,
    ) -> str:
        target = self._extract_modify_target(instruction)

        if target:
            marker = f"=== ARQUIVO: {target} ==="

            if marker in context:
                newline = chr(10)
                sections = []

                target_section = context.split(marker, 1)[1]
                next_marker = target_section.find(
                    newline + "=== ARQUIVO:"
                )
                if next_marker >= 0:
                    target_section = target_section[:next_marker]

                sections.append(
                    f"=== ARQUIVO: {target} ==="
                    + target_section
                )

                target_path = Path(target)
                if (
                    target_path.suffix.lower() == ".py"
                    and not target_path.name.startswith("test_")
                ):
                    test_path = target_path.with_name(
                        f"test_{target_path.name}"
                    ).as_posix()
                    test_marker = f"=== ARQUIVO: {test_path} ==="

                    if test_marker in context:
                        test_section = context.split(
                            test_marker,
                            1,
                        )[1]
                        next_marker = test_section.find(
                            newline + "=== ARQUIVO:"
                        )
                        if next_marker >= 0:
                            test_section = test_section[:next_marker]

                        sections.append(
                            f"=== ARQUIVO: {test_path} ==="
                            + test_section
                        )

                return (
                    "=== CONTEXTO DO PROJETO ==="
                    + newline
                    + f"=== ARQUIVO ALVO DO MODIFY: {target} ==="
                    + newline
                    + newline.join(sections)
                )

        if len(context) > self.MAX_CONTEXT_CHARS:
            return (
                context[: self.MAX_CONTEXT_CHARS]
                + chr(10)
                + chr(10)
                + "=== CONTEXTO TRUNCADO ==="
            )

        return context

    def create_plan(
        self,
        instruction: str,
        context: str = "",
        feedback_context: dict | None = None,
        source_files: dict | None = None,
    ) -> Plan:
        if is_read_only_request(instruction):
            raise ValueError("Consulta somente de leitura: use Consultar sem alterar no Studio.")
        sources = copy_sources(source_files)
        if not isinstance(context, str):
            context = ""

        if len(context) > self.MAX_CONTEXT_CHARS:
            context = self._preserve_modify_target_context(
                instruction,
                context,
            )

        if feedback_context is None:
            feedback_context = {}

        if not isinstance(feedback_context, dict):
            raise ValueError("Contexto de feedback inválido.")

        feedback_text = json.dumps(
            feedback_context,
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""
Você é o planejador de um agente autônomo de programação.
Sua função é transformar a solicitação do usuário em um plano estruturado
de alterações no projeto.

INSTRUÇÃO DO USUÁRIO:
{instruction}

CONTEXTO DO PROJETO:
{context}

CONTEXTO DE FEEDBACK DA TRANSAÇÃO:
{feedback_text}

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
4. Para MODIFY, forneça o conteúdo completo do arquivo; quando houver manifesto
   de fontes, a alternativa de edições localizadas descrita abaixo também é válida.
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

        if sources:
            manifest = json.dumps({path: content_hash(content) for path, content in sources.items()}, ensure_ascii=False)
            prompt += f"""

EDIÇÕES LOCALIZADAS DISPONÍVEIS (preferidas para MODIFY):
Em vez de repetir o arquivo inteiro, retorne uma alteração neste formato:
{{"type":"modify","path":"arquivo.js","base_sha256":"hash do manifesto", "edits":[{{"old":"trecho literal existente e único","new":"novo trecho"}}],"reason":"motivo"}}
Use somente arquivos completos presentes no contexto e o hash exato abaixo.
Cada old deve ocorrer exatamente uma vez no conteúdo resultante da edição anterior.
Prefira blocos com o nome da função e linhas de contexto que tornem a âncora única.
Não use apenas chaves, linhas em branco ou instruções repetidas como âncora.
As edições são literais e sequenciais, com 1 a 100 substituições por arquivo.
Não use posições, expressões regulares, comandos ou marcadores de conteúdo omitido.
Não misture content e edits na mesma alteração nem repita o mesmo arquivo.
Para inserir texto, substitua um trecho único de ancoragem pelo trecho e o acréscimo.
Preserve quebras de linha e o texto fora dos trechos substituídos.
O DevAgent reconstruirá o conteúdo completo para validação e revisão humana.
O formato tradicional com content completo continua aceito; CREATE e DELETE mantêm suas regras.
MANIFESTO SHA256 DAS FONTES UTF-8:
{manifest}
"""

        response = self.ai.generate(prompt)

        for attempt in range(2):
            try:
                data = json.loads(response)
            except (json.JSONDecodeError, TypeError) as error:
                raise ValueError("A IA retornou um plano que não é JSON válido.") from error
            try:
                expanded = expand_local_edits(data, sources)
            except LocalEditAnchorError as error:
                if attempt == 1:
                    raise
                diagnostic = json.dumps({
                    "path": error.path, "edit_number": error.edit_number,
                    "reason": error.reason,
                }, ensure_ascii=False)
                retry_prompt = prompt + (
                    "\nNOVA TENTATIVA ÚNICA DE PLANEJAMENTO:\n"
                    "A resposta anterior foi recusada antes de cadastrar um plano: uma âncora old era ausente ou ambígua. "
                    "Nenhuma alteração foi aplicada. Gere novamente o plano completo a partir das fontes originais já fornecidas. "
                    "Amplie as âncoras com contexto literal da função, conferindo cada old após as edições anteriores. "
                    "Se não conseguir garantir a unicidade, use o formato content completo apenas para esse arquivo. "
                    "Preserve o objetivo, escopo e testes solicitados. Os hashes e todas as validações continuam obrigatórios. "
                    "Não use ferramentas nem execute comandos. Retorne somente JSON.\n"
                    "DIAGNÓSTICO DA VALIDAÇÃO:\n" + diagnostic
                )
                response = self.ai.generate(retry_prompt)
                continue
            return self._build_plan(expanded, instruction)

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
            or normalized.startswith("test_")
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
        return has_requested_changes(instruction)
