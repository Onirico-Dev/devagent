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
Você é o módulo de diagnóstico do DevAgent.

Objetivo original:
{instruction}

Erro encontrado:
{error}

Saída dos testes:
{test_output}

Analise tecnicamente a falha.

Você NÃO executa comandos.
Você NÃO altera arquivos.
Você NÃO deve inventar caminhos.

Retorne SOMENTE JSON válido, sem markdown,
com exatamente estes campos:

{{
  "diagnosis": "causa provável da falha",
  "correction": "descrição objetiva da correção",
  "risk": "baixo, medio ou alto"
}}

Classifique o risco da correção.
"""

        response = self.ai.generate(prompt)

        try:
            result = json.loads(response)
        except json.JSONDecodeError:

            return {
                "diagnosis": response,
                "correction": "",
                "risk": "alto",
            }

        required = {
            "diagnosis",
            "correction",
            "risk",
        }

        if not required.issubset(result.keys()):

            return {
                "diagnosis": (
                    "Resposta da IA não possui "
                    "o formato esperado."
                ),
                "correction": "",
                "risk": "alto",
            }

        risk = str(
            result["risk"]
        ).lower().strip()

        if risk not in {
            "baixo",
            "medio",
            "alto",
        }:

            result["risk"] = "alto"

        return {
            "diagnosis": str(
                result["diagnosis"]
            ),
            "correction": str(
                result["correction"]
            ),
            "risk": result["risk"],
        }
