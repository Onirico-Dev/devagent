from types import SimpleNamespace

import pytest

from core.adapters.codex_adapter import CodexAdapter
from core.adapters.mock import MockAdapter
from core.adapters.groq import GroqAdapter
from core.api.service import APIService


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (SimpleNamespace(ai=object.__new__(CodexAdapter)), "Codex"),
        (SimpleNamespace(ai=object.__new__(MockAdapter)), "Mock"),
        (SimpleNamespace(ai=object.__new__(GroqAdapter)), "Groq"),
        (SimpleNamespace(ai=object()), "Desconhecido"),
        (SimpleNamespace(), "Desconhecido"),
        (SimpleNamespace(ai=None), "Desconhecido"),
    ],
    ids=["codex", "mock", "groq", "unknown", "missing", "none"],
)
def test_health_reports_active_adapter_without_credentials(agent, expected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Health não deve consultar configuração nem credenciais")

    monkeypatch.setattr("os.getenv", forbidden)
    assert APIService(agent, object()).health() == {
        "status": "ok", "service": "devagent", "ai_provider": expected,
    }
