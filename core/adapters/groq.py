import os

import requests

from core.adapters.base import AIAdapter


class GroqAdapter(AIAdapter):

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model=None, api_key=None, timeout=60):
        self.api_key = (
            api_key
            or os.getenv("GROQ_API_KEY")
        )

        self.model = (
            model
            or os.getenv(
                "GROQ_MODEL",
                self.DEFAULT_MODEL
            )
        )

        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY não configurada."
            )

    def generate(self, prompt: str) -> str:

        if not isinstance(prompt, str):
            raise TypeError(
                "O prompt deve ser uma string."
            )

        if not prompt.strip():
            raise ValueError(
                "O prompt não pode ser vazio."
            )

        response = requests.post(
            self.API_URL,
            headers={
                "Authorization": (
                    f"Bearer {self.api_key}"
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": 0.2,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        try:
            content = (
                data["choices"][0]
                ["message"]
                ["content"]
            )
        except (
            KeyError,
            IndexError,
            TypeError,
        ) as error:

            raise RuntimeError(
                "Resposta inválida da API Groq."
            ) from error

        if not isinstance(content, str):
            raise RuntimeError(
                "A resposta da Groq não contém "
                "texto válido."
            )

        return content.strip()
