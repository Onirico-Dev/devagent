import pytest

from agent import DevAgent
from core.adapters.codex_adapter import CodexAdapter
from core.adapters.mock import MockAdapter


def test_codex_provider_is_selected(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVAGENT_AI", "codex")

    agent = DevAgent(root=tmp_path)

    assert isinstance(agent.ai, CodexAdapter)
    assert agent.pipeline.ai_planner.ai is agent.ai


def test_codex_provider_is_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVAGENT_AI", "  CoDeX  ")

    agent = DevAgent(root=tmp_path)

    assert isinstance(agent.ai, CodexAdapter)


def test_mock_remains_default(monkeypatch, tmp_path):
    monkeypatch.delenv("DEVAGENT_AI", raising=False)

    agent = DevAgent(root=tmp_path)

    assert isinstance(agent.ai, MockAdapter)


def test_explicit_mock_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVAGENT_AI", "mock")

    agent = DevAgent(root=tmp_path)

    assert isinstance(agent.ai, MockAdapter)


def test_codex_selection_does_not_start_process(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("DEVAGENT_AI", "codex")

    def forbidden_start(*args, **kwargs):
        raise AssertionError(
            "A seleção não deve iniciar o Codex."
        )

    monkeypatch.setattr(
        "core.adapters.codex.CodexTransport.start",
        forbidden_start,
    )

    agent = DevAgent(root=tmp_path)

    assert isinstance(agent.ai, CodexAdapter)
