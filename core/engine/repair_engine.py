import json


class RepairEngine:

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    def analyze_failure(
        self,
        instruction,
        diagnostic,
        test_output,
    ):
        """
        Analisa uma falha já estruturada pelo DiagnosticEngine.

        O RepairEngine não executa comandos e não altera arquivos.
        Ele apenas produz uma proposta de correção.
        """

        error_type = diagnostic.get(
            "error_type",
            "UnknownError",
        )

        file_path = diagnostic.get(
            "file"
        )

        line = diagnostic.get(
            "line"
        )

        message = diagnostic.get(
            "message",
            "",
        )

        prompt = f"""
Você é o módulo de reparo do DevAgent.

Sua função é analisar uma falha de execução/teste
e propor uma correção segura.

OBJETIVO:
{instruction}

TIPO DO ERRO:
{error_type}

ARQUIVO:
{file_path}

LINHA:
{line}

MENSAGEM:
{message}

SAÍDA COMPLETA DOS TESTES:
{test_output}

Retorne SOMENTE JSON válido.

O JSON deve possuir exatamente estes campos:

{{
  "diagnosis": "causa provável do erro",
  "correction": "descrição objetiva da correção necessária",
  "risk": "baixo, medio ou alto",
  "action": "modify, create ou none",
  "path": "caminho do arquivo que deve ser corrigido",
  "content": "conteúdo completo do arquivo corrigido ou vazio"
}}

REGRAS:

1. Não execute comandos.
2. Não altere arquivos.
3. Não invente arquivos sem necessidade.
4. Se a correção não puder ser determinada com segurança,
   use action "none".
5. Para action "modify", informe o conteúdo COMPLETO
   do arquivo corrigido.
6. Nunca coloque markdown no JSON.
7. Nunca use ```json.
8. risk deve ser somente:
   "baixo", "medio" ou "alto".
9. Se o erro for claramente de sintaxe e o arquivo estiver
   disponível no contexto, proponha uma correção objetiva.
10. Não proponha alterações fora do objetivo solicitado.
"""

        response = self.ai.generate(prompt)

        return self._parse_response(response)

    def _parse_response(self, response):

        if not response:
            return self._empty_repair(
                "IA não retornou resposta."
            )

        if isinstance(response, dict):
            data = response
        else:

            try:
                data = json.loads(response)

            except (
                json.JSONDecodeError,
                TypeError,
            ):

                return self._empty_repair(
                    "Resposta da IA não contém JSON válido."
                )

        required = {
            "diagnosis",
            "correction",
            "risk",
            "action",
            "path",
            "content",
        }

        if not required.issubset(data.keys()):

            return self._empty_repair(
                "Resposta da IA possui campos incompletos."
            )

        risk = str(
            data.get("risk", "")
        ).lower()

        if risk not in {
            "baixo",
            "medio",
            "alto",
        }:

            return self._empty_repair(
                "Nível de risco inválido."
            )

        action = str(
            data.get("action", "")
        ).lower()

        if action not in {
            "modify",
            "create",
            "none",
        }:

            return self._empty_repair(
                "Ação de reparo inválida."
            )

        return {
            "diagnosis": str(
                data.get("diagnosis", "")
            ),
            "correction": str(
                data.get("correction", "")
            ),
            "risk": risk,
            "action": action,
            "path": str(
                data.get("path", "")
            ),
            "content": str(
                data.get("content", "")
            ),
            "approved": False,
        }

    def _empty_repair(self, reason):

        return {
            "diagnosis": reason,
            "correction": "",
            "risk": "alto",
            "action": "none",
            "path": "",
            "content": "",
            "approved": False,
        }
