"""A coleta da API não pode recuperar a transação que está testando o projeto."""

import fcntl
import os
from pathlib import Path
import subprocess
import sys

from core.adapters.mock import MockAdapter
from core.approval.approval_coordinator import ApprovalCoordinator
from core.executor.transaction_manager import TransactionManager
from core.schemas.models import Transaction, TransactionStatus


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_api_runtime_is_absolute_temporary_and_uses_real_classes():
    import api
    from agent import DevAgent
    from core.gateway import DevAgentGateway

    assert isinstance(api.agent.ai, MockAdapter)
    assert isinstance(api.agent, DevAgent)
    assert isinstance(api.gateway, DevAgentGateway)
    assert api.DevAgent is DevAgent
    assert api.DevAgentGateway is DevAgentGateway
    runtime = Path(api.agent.root)
    assert runtime.is_absolute()
    assert runtime != PROJECT_ROOT
    assert Path(api.gateway.root) == runtime
    assert api.gateway.transactions.root == runtime
    assert Path(api.gateway.approval_coordinator.root) == runtime
    assert api.agent.session.path.is_relative_to(runtime)


def test_api_collection_finishes_while_parent_keeps_active_approval(tmp_path):
    manager = TransactionManager(tmp_path)
    transaction = Transaction(
        transaction_id="collection-isolation-158",
        status=TransactionStatus.TESTING,
        metadata={"approval_id": "158"},
    )
    manager.persist_manifest(transaction)
    manifest = tmp_path / "transactions" / "collection-isolation-158.json"
    before = manifest.read_bytes()
    session = tmp_path / "logs" / "session.json"
    session.parent.mkdir()
    session.write_text('{"instructions":["PARENT"],"plans":[]}', encoding="utf-8")
    session_before = session.read_bytes()

    coordinator = ApprovalCoordinator(tmp_path)
    locks = coordinator.acquire("158")
    try:
        env = os.environ.copy()
        # O bootstrap deve selecionar Mock antes das fixtures, mesmo neste caso.
        env["DEVAGENT_AI"] = "codex"
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest", "--collect-only", "-q",
                "-o", "addopts=", str(PROJECT_ROOT / "tests" / "test_api.py"),
            ],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "test_health_endpoint" in result.stdout
        # Este teste existente cria um gateway com root='.' durante a execução.
        execution = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
                str(PROJECT_ROOT / "tests" / "test_api.py")
                + "::test_gateway_create_task_rejects_invalid_context",
                str(PROJECT_ROOT / "tests" / "test_api.py")
                + "::test_api_main_invokes_run",
            ],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
        )
        assert execution.returncode == 0, execution.stdout + execution.stderr
        assert "2 passed" in execution.stdout
        assert manifest.read_bytes() == before
        assert session.read_bytes() == session_before
        assert manager.load_manifest(transaction.transaction_id).status == TransactionStatus.TESTING

        # A coleta terminou mantendo o bloqueio do pai efetivo.
        probe = subprocess.run(
            [sys.executable, "-c", "\n".join([
                "import fcntl, sys",
                "with open(sys.argv[1], 'a+') as handle:",
                "    try:",
                "        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)",
                "    except BlockingIOError:",
                "        raise SystemExit(0)",
                "    raise SystemExit(1)",
            ]), str(locks[1].name)],
            capture_output=True, text=True, timeout=10,
        )
        assert probe.returncode == 0, probe.stdout + probe.stderr
    finally:
        coordinator.release(*locks)


def test_api_collection_restores_provider_environment(tmp_path):
    # Executa a coleta e consulta o ambiente no mesmo interpretador filho.
    code = "\n".join([
        "import os, pytest",
        "result = pytest.main(['--collect-only', '-q', '-o', 'addopts=', "
        + repr(str(PROJECT_ROOT / "tests" / "test_api.py")) + "])",
        "assert result == 0",
        "assert os.environ['DEVAGENT_AI'] == 'codex'",
        "import api",
        "from core.adapters.mock import MockAdapter",
        "assert isinstance(api.agent.ai, MockAdapter)",
    ])
    env = os.environ.copy()
    env["DEVAGENT_AI"] = "codex"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
