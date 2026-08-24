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
Você é o módulo de análise de erros do DevAgent.

Objetivo:
{instruction}

Erro:
{error}

Saída dos testes:
{test_output}

Analise o problema.

Retorne JSON válido com exatamente estes campos:

{{
  "diagnosis": "causa provável",
  "correction": "correção necessária",
  "risk": "baixo, medio ou alto"
}}

Não execute comandos.
Não invente arquivos.
Não altere o projeto.
"""

        response = self.ai.generate(prompt)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {
                "diagnosis": response,
                "correction": "",
                "risk": "alto",
            }
