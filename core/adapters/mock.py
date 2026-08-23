from core.adapters.base import AIAdapter


class MockAdapter(AIAdapter):

    def generate(self, prompt: str) -> str:
        return (
            "Resposta simulada do modelo.\n"
            f"Prompt recebido: {prompt}"
        )
