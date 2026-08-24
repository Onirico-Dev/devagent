import os
import requests

from core.adapters.base import AIAdapter


class GroqAdapter(AIAdapter):

    def __init__(
        self,
        model="llama-3.3-70b-versatile",
    ):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = model

        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY não configurada."
            )

    def generate(self, prompt: str) -> str:

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
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
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        return data["choices"][0]["message"]["content"]
