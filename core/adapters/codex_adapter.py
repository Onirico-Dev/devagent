"""Adaptador Codex para geração de texto pelo DevAgent."""

from core.adapters.base import AIAdapter
from core.adapters.codex import CodexTransport


class CodexAdapter(AIAdapter):
    """Utiliza o Codex App Server sem executar alterações no projeto."""

    def __init__(self, timeout=120, command=None, transport_factory=None):
        if isinstance(timeout, bool) or not isinstance(
            timeout, (int, float)
        ) or timeout <= 0:
            raise ValueError("Timeout deve ser positivo.")

        self.timeout = timeout
        self.command = tuple(command) if command is not None else None
        self.transport_factory = transport_factory or CodexTransport

    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise TypeError("O prompt deve ser uma string.")

        if not prompt.strip():
            raise ValueError("O prompt não pode ser vazio.")

        kwargs = {"timeout": self.timeout}

        if self.command is not None:
            kwargs["command"] = self.command

        transport = self.transport_factory(**kwargs)

        with transport:
            thread_id = transport.create_session()
            turn_id = transport.start_turn(thread_id, prompt)
            response = transport.wait_turn(thread_id, turn_id)

        if not isinstance(response, str) or not response.strip():
            raise RuntimeError(
                "Codex não retornou uma resposta textual válida."
            )

        return response.strip()
