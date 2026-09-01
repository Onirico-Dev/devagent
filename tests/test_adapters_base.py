import pytest

from core.adapters.base import AIAdapter


def test_ai_adapter_is_abstract():
    with pytest.raises(TypeError):
        AIAdapter()


def test_ai_adapter_generate_abstract_body_is_callable():
    class ConcreteAdapter(AIAdapter):
        def generate(self, prompt: str) -> str:
            return super().generate(prompt)

    adapter = ConcreteAdapter()

    assert adapter.generate("teste") is None
