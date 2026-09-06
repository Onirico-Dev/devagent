import json


class RepairEngine:
    MAX_REPAIR_CONTENT = 1_000_000

    def __init__(self, ai_adapter):
        self.ai = ai_adapter

    def _build_prompt(self, instruction, error, test_output):
        return f"""Você é o módulo de reparo automático do DevAgent.

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

    @staticmethod
    def _invalid_response(diagnosis):
        return {
            "diagnosis": diagnosis,
            "correction": "",
            "risk": "alto",
            "action": "none",
            "path": "",
            "content": "",
        }

    def _parse_response(self, response):
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            return self._invalid_response(response)

        if not isinstance(data, dict):
            return self._invalid_response(
                "Resposta do modelo não é um objeto JSON."
            )

        required = {
            "diagnosis",
            "correction",
            "risk",
            "action",
            "path",
            "content",
        }

        if not required.issubset(data):
            return self._invalid_response(
                "Resposta incompleta do modelo."
            )

        return data

    def _normalize_response(self, data):
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

        return data

    def _validate_repair_content(self, data):
        if (
            data["action"] in {"create", "modify"}
            and not data["content"].strip()
        ):
            return self._invalid_response(
                "Resposta do modelo não contém conteúdo de reparo."
            )

        if len(data["content"]) > self.MAX_REPAIR_CONTENT:
            return self._invalid_response(
                "Conteúdo de reparo excede o limite permitido."
            )

        return data

    def analyze_failure(
        self,
        instruction,
        error,
        test_output,
    ):
        prompt = self._build_prompt(
            instruction,
            error,
            test_output,
        )

        response = self.ai.generate(prompt)
        data = self._parse_response(response)

        if data.get("action") == "none" and not data.get("path"):
            return data

        data = self._normalize_response(data)
        return self._validate_repair_content(data)
