import json

import pytest

from core.adapters.groq import GroqAdapter


def test_groq_init_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="GROQ_API_KEY não configurada.",
    ):
        GroqAdapter()


def test_groq_init_uses_explicit_configuration(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    monkeypatch.setenv("GROQ_MODEL", "env-model")

    adapter = GroqAdapter(
        model="custom-model",
        api_key="custom-key",
        timeout=17,
    )

    assert adapter.api_key == "custom-key"
    assert adapter.model == "custom-model"
    assert adapter.timeout == 17


def test_groq_init_uses_environment_configuration(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    monkeypatch.setenv("GROQ_MODEL", "env-model")

    adapter = GroqAdapter()

    assert adapter.api_key == "env-key"
    assert adapter.model == "env-model"
    assert adapter.timeout == 60


def test_groq_init_uses_default_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    adapter = GroqAdapter()

    assert adapter.model == GroqAdapter.DEFAULT_MODEL


def test_groq_generate_rejects_non_string_prompt():
    adapter = GroqAdapter(api_key="test-key")

    with pytest.raises(
        TypeError,
        match="O prompt deve ser uma string.",
    ):
        adapter.generate(None)


def test_groq_generate_rejects_empty_prompt():
    adapter = GroqAdapter(api_key="test-key")

    with pytest.raises(
        ValueError,
        match="O prompt não pode ser vazio.",
    ):
        adapter.generate("   ")


def test_groq_generate_returns_stripped_content(monkeypatch):
    adapter = GroqAdapter(
        api_key="test-key",
        model="test-model",
        timeout=23,
    )

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            captured["raise_for_status"] = True

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "  resposta da IA  ",
                        }
                    }
                ]
            }

    def fake_post(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        fake_post,
    )

    result = adapter.generate("teste")

    assert result == "resposta da IA"
    assert captured["args"][0] == GroqAdapter.API_URL
    assert captured["kwargs"]["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert captured["kwargs"]["json"] == {
        "model": "test-model",
        "messages": [
            {
                "role": "user",
                "content": "teste",
            }
        ],
        "temperature": 0.2,
    }
    assert captured["kwargs"]["timeout"] == 23
    assert captured["raise_for_status"] is True


def test_groq_generate_propagates_http_error(monkeypatch):
    adapter = GroqAdapter(api_key="test-key")

    class FakeResponse:
        def raise_for_status(self):
            raise RuntimeError("http failure")

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="http failure"):
        adapter.generate("teste")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
    ],
)
def test_groq_generate_rejects_invalid_response_structure(
    monkeypatch,
    payload,
):
    adapter = GroqAdapter(api_key="test-key")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    if (
        payload.get("choices")
        and isinstance(payload["choices"][0], dict)
        and isinstance(payload["choices"][0].get("message"), dict)
        and "content" in payload["choices"][0]["message"]
        and payload["choices"][0]["message"]["content"] is None
    ):
        expected = "A resposta da Groq não contém texto válido."
    else:
        expected = "Resposta inválida da API Groq."

    with pytest.raises(RuntimeError, match=expected):
        adapter.generate("teste")


def test_groq_generate_rejects_non_string_content(monkeypatch):
    adapter = GroqAdapter(api_key="test-key")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": {"text": "não é string"},
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(
        RuntimeError,
        match="A resposta da Groq não contém texto válido.",
    ):
        adapter.generate("teste")


def test_groq_generate_accepts_valid_json_string(monkeypatch):
    adapter = GroqAdapter(api_key="test-key")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "objective": "teste",
                                    "changes": [],
                                }
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "core.adapters.groq.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = adapter.generate("teste")

    assert json.loads(result) == {
        "objective": "teste",
        "changes": [],
    }
