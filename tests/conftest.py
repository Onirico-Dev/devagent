import subprocess
import sys
from pathlib import Path

import pytest


_api_test_runtime = None


def pytest_sessionstart(session):
    """Inicializa a API dos testes fora do estado da operação em andamento.

    A coleta importa api.py antes das fixtures. Os construtores recebem uma
    raiz absoluta temporária e Mock explícito, sem recuperar transações do
    projeto que está executando este pytest.
    """
    global _api_test_runtime

    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    import agent as agent_module
    import core.gateway as gateway_module
    from core.adapters.mock import MockAdapter

    _api_test_runtime = TemporaryDirectory(prefix="devagent-pytest-api-")
    runtime_root = _api_test_runtime.name
    agent_type = agent_module.DevAgent
    gateway_type = gateway_module.DevAgentGateway

    def isolated_agent(*args, **kwargs):
        return agent_type(runtime_root, ai_adapter=MockAdapter())

    def isolated_gateway(agent, *args, **kwargs):
        return gateway_type(agent, runtime_root)

    with patch.object(agent_module, "DevAgent", isolated_agent), patch.object(
        gateway_module, "DevAgentGateway", isolated_gateway
    ):
        import api

    # O módulo deve continuar exportando as classes reais após o bootstrap.
    api.DevAgent = agent_type
    api.DevAgentGateway = gateway_type

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@devagent.local"],
        cwd=root,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=root,
        check=True,
    )

    return root

@pytest.fixture(autouse=True)
def default_ai_provider(monkeypatch):
    """Mantém os testes isolados de provedores externos por padrão."""
    monkeypatch.setenv("DEVAGENT_AI", "mock")


@pytest.fixture(autouse=True)
def isolated_api_working_directory(request, tmp_path, monkeypatch):
    """Impede que gateways com root='.' usem o estado da operação pai."""
    if request.node.path.name in {"test_api.py", "test_api_http_hardening.py"}:
        # O teste do entrypoint usa runpy.run_path("api.py"). O link mantém
        # esse caminho disponível sem copiar código ou estado do projeto.
        (tmp_path / "api.py").symlink_to(ROOT / "api.py")
        monkeypatch.chdir(tmp_path)
