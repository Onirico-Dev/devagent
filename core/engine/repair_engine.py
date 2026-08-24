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
Você é o módulo de reparo do DevAgent.

Objetivo original:
{instruction}

Erro encontrado:
{error}

Saída dos testes:
{test_output}

Analise o problema e proponha uma correção concreta.

Retorne SOMENTE JSON válido com exatamente estes campos:

{{
  "diagnosis": "causa provável",
  "correction": "descrição da correção",
  "risk": "baixo, medio ou alto",
  "action": "create ou modify",
  "path": "caminho do arquivo",
  "content": "conteúdo completo que deve ficar no arquivo"
}}

Regras:

1. Não execute comandos.
2. Não invente arquivos desnecessários.
3. Não altere arquivos fora do objetivo.
4. Para MODIFY, retorne o conteúdo completo do arquivo.
5. Para CREATE, retorne o conteúdo completo do novo arquivo.
6. Se não for possível propor uma correção segura, use:
   "action": "none"
7. Nunca use markdown.
8. Retorne somente JSON.
"""

        response = self.ai.generate(prompt)

        try:

            result = json.loads(response)

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

        if not required.issubset(result):
            return {
                "diagnosis": "Resposta de reparo incompleta.",
                "correction": "",
                "risk": "alto",
                "action": "none",
                "path": "",
                "content": "",
            }

        return result
