import json


class RepairEngine:

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    def analyze_failure(
        self,
        instruction,
        error,
        test_output,
    ):

        prompt = f"""
Você é o módulo de reparo automático do DevAgent.

Objetivo original:
{instruction}

Erro:
{error}

Saída dos testes:
{test_output}

Analise a falha e proponha uma correção.

Retorne SOMENTE JSON válido com exatamente estes campos:

{{
  "diagnosis": "causa provável",
  "correction": "explicação da correção",
  "risk": "baixo, medio ou alto",
  "action": "create ou modify",
  "path": "caminho do arquivo",
  "content": "conteúdo completo do arquivo corrigido"
}}

Regras:

- Não execute comandos.
- Não invente arquivos sem necessidade.
- O campo path deve apontar para o arquivo que precisa ser corrigido.
- Para modify, content deve conter o conteúdo COMPLETO do arquivo corrigido.
- Para create, content deve conter o conteúdo completo do novo arquivo.
- Se não for possível propor uma correção segura, use:
  "action": "none"
- Nunca use action diferente de create, modify ou none.
- risk deve ser exatamente baixo, medio ou alto.
"""

        response = self.ai.generate(prompt)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            return {
                "diagnosis": response,
                "correction": "",
                "risk": "alto",
                "action": "none",
                "path": "",
                "content": "",
            }

        required = {
            "diagnosis",
            "correction",
            "risk",
            "action",
            "path",
            "content",
        }

        if not isinstance(data, dict):
            return {
                "diagnosis": "Resposta do modelo não é um objeto JSON.",
                "correction": "",
                "risk": "alto",
                "action": "none",
                "path": "",
                "content": "",
            }

        if not required.issubset(data):
            return {
                "diagnosis": "Resposta incompleta do modelo.",
                "correction": "",
                "risk": "alto",
                "action": "none",
                "path": "",
                "content": "",
            }

        if not isinstance(data["risk"], str):
            data["risk"] = "alto"

        if data["risk"] not in {
            "baixo",
            "medio",
            "alto",
        }:
            data["risk"] = "alto"

        if not isinstance(data["action"], str):
            data["action"] = "none"

        if data["action"] not in {
            "create",
            "modify",
            "none",
        }:
            data["action"] = "none"

        if not isinstance(data["path"], str):
            data["path"] = ""

        if not isinstance(data["content"], str):
            data["content"] = ""

        MAX_REPAIR_CONTENT = 1_000_000

        if len(data["content"]) > MAX_REPAIR_CONTENT:
            return {
                "diagnosis": "Conteúdo de reparo excede o limite permitido.",
                "correction": "",
                "risk": "alto",
                "action": "none",
                "path": "",
                "content": "",
            }

        return data
