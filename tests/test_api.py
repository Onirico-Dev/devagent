from agent import DevAgent
import json
from http.client import HTTPConnection
from threading import Thread
from http.server import HTTPServer
import pytest

import api
from core.adapters.mock import MockAdapter


def start_server(root=None):
    if root is not None:
        from agent import DevAgent
        from core.gateway import DevAgentGateway

        api.agent = DevAgent(str(root), ai_adapter=MockAdapter())
        api.gateway = DevAgentGateway(
            api.agent,
            str(root),
        )

    server = HTTPServer(
        ("127.0.0.1", 0),
        api.APIHandler,
    )

    thread = Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    return server, thread


def request(
    server,
    method,
    path,
    body=None,
    raw_body=None,
):
    connection = HTTPConnection(
        "127.0.0.1",
        server.server_port,
    )

    headers = {}
    encoded_body = None

    if raw_body is not None:
        encoded_body = raw_body.encode("utf-8")
        headers["Content-Type"] = "application/json"

    elif body is not None:
        encoded_body = json.dumps(
            body
        ).encode("utf-8")

        headers["Content-Type"] = (
            "application/json"
        )

    connection.request(
        method,
        path,
        body=encoded_body,
        headers=headers,
    )

    response = connection.getresponse()
    raw = response.read()

    connection.close()

    return (
        response.status,
        json.loads(raw.decode("utf-8")),
    )


def test_health():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/health",
        )

        assert status == 200
        assert data["status"] == "ok"
        assert data["service"] == "devagent"

    finally:
        server.shutdown()
        server.server_close()


def test_unknown_endpoint():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/nao-existe",
        )

        assert status == 404
        assert data["error"] == (
            "Endpoint não encontrado"
        )

    finally:
        server.shutdown()
        server.server_close()


def test_full_task_flow(isolated_project):
    server, _ = start_server(isolated_project)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    'Crie api_teste.py contendo '
                    'print("API OK")'
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"
        assert "approval_id" in created

        approval_id = created["approval_id"]

        status, latest = request(
            server,
            "GET",
            "/tasks/latest",
        )

        assert status == 200
        assert latest["approval_id"] == approval_id
        assert latest["status"] == "pending"

        status, approved = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert approved["status"] == "committed"
        assert approved["tests"]["success"] is True
        assert approved["repair_attempts"] == 0
        assert "transaction_id" in approved

        status, final_task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert final_task["status"] == "committed"

    finally:
        server.shutdown()
        server.server_close()



def test_reject_task(isolated_project):
    server, _ = start_server(isolated_project)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    'Crie rejeitado.py contendo '
                    'print("NÃO DEVE EXECUTAR")'
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, rejected = request(
            server,
            "POST",
            f"/reject/{approval_id}",
        )

        assert status == 200
        assert rejected["status"] == "rejected"

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] == "rejected"

        import os

        assert not os.path.exists(
            "rejeitado.py"
        )

    finally:
        server.shutdown()
        server.server_close()



def test_rollback_task(isolated_project):
    server, _ = start_server(isolated_project)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie api_falha.py contendo "
                    "isto não é Python válido"
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"
        assert result["tests"]["success"] is False
        assert result["repair_attempts"] >= 1

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] == "rolled_back"

        import os

        assert not os.path.exists(
            "api_falha.py"
        )

    finally:
        server.shutdown()
        server.server_close()


def test_plan_without_instruction():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "POST",
            "/plan",
            {}
        )

        assert status == 400
        assert data["error"] == (
            "Campo 'instruction' é obrigatório"
        )

    finally:
        server.shutdown()
        server.server_close()


def test_plan_with_invalid_json():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "POST",
            "/plan",
            raw_body="{isso não é JSON}"
        )

        assert status == 400
        assert data["error"] == "JSON inválido"

    finally:
        server.shutdown()
        server.server_close()


def test_get_unknown_task():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/tasks/999999"
        )

        assert status == 404
        assert data["error"] == "Tarefa não encontrada"

    finally:
        server.shutdown()
        server.server_close()


def test_approve_unknown_task():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "POST",
            "/approve/999999"
        )

        assert status == 404
        assert data["error"] == (
            "Tarefa não encontrada."
        )

    finally:
        server.shutdown()
        server.server_close()


def test_reject_unknown_task():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "POST",
            "/reject/999999"
        )

        assert status == 404
        assert data["error"] == (
            "Solicitação não encontrada."
        )

    finally:
        server.shutdown()
        server.server_close()


def test_approve_already_rejected_task():
    server, _ = start_server()

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie teste_conflito.py "
                    'contendo print("OK")'
                )
            }
        )

        assert status == 200

        approval_id = created["approval_id"]

        status, rejected = request(
            server,
            "POST",
            f"/reject/{approval_id}"
        )

        assert status == 200
        assert rejected["status"] == "rejected"

        status, data = request(
            server,
            "POST",
            f"/approve/{approval_id}"
        )

        assert status == 409
        assert data["error"] == (
            "Solicitação não está pendente."
        )

    finally:
        server.shutdown()
        server.server_close()


def test_reject_already_rejected_task():
    server, _ = start_server()

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie teste_conflito.py "
                    'contendo print("OK")'
                )
            }
        )

        assert status == 200

        approval_id = created["approval_id"]

        status, rejected = request(
            server,
            "POST",
            f"/reject/{approval_id}"
        )

        assert status == 200
        assert rejected["status"] == "rejected"

        status, data = request(
            server,
            "POST",
            f"/reject/{approval_id}"
        )

        assert status == 409
        assert data["error"] == (
            "Solicitação não está pendente."
        )

    finally:
        server.shutdown()
        server.server_close()


def test_method_not_allowed():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "DELETE",
            "/health"
        )

        assert status == 405
        assert data["error"] == "Método não permitido"

    finally:
        server.shutdown()
        server.server_close()

def test_malformed_task_routes():
    server, _ = start_server()

    try:
        for path in (
            "/tasks/",
            "/tasks/a/b",
        ):
            status, data = request(server, "GET", path)
            assert status == 404
            assert data["error"] == "Endpoint não encontrado"
    finally:
        server.shutdown()
        server.server_close()


def test_malformed_approval_routes():
    server, _ = start_server()

    try:
        for path in (
            "/approve/",
            "/approve/a/b",
            "/reject/",
            "/reject/a/b",
        ):
            status, data = request(server, "POST", path)
            assert status == 404
            assert data["error"] == "Endpoint não encontrado"
    finally:
        server.shutdown()
        server.server_close()


def test_health_endpoint():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/health",
        )

        assert status == 200
        assert data == {
            "status": "ok",
            "service": "devagent",
        }

    finally:
        server.shutdown()
        server.server_close()


def test_tasks_endpoint():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/tasks",
        )

        assert status == 200
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    finally:
        server.shutdown()
        server.server_close()


def test_latest_without_tasks(tmp_path):
    server, _ = start_server(tmp_path)

    try:
        status, data = request(
            server,
            "GET",
            "/tasks/latest",
        )

        assert status == 404
        assert data["error"] == "Nenhuma tarefa encontrada"

    finally:
        server.shutdown()
        server.server_close()


def test_plan_get_task_and_latest():
    server, _ = start_server()

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie contrato_api.py "
                    'contendo print("API")'
                )
            },
        )

        assert status == 200
        assert "approval_id" in created

        approval_id = created["approval_id"]

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["approval_id"] == approval_id

        status, latest = request(
            server,
            "GET",
            "/tasks/latest",
        )

        assert status == 200
        assert latest["approval_id"] == approval_id

    finally:
        server.shutdown()
        server.server_close()


def test_unknown_endpoint():
    server, _ = start_server()

    try:
        status, data = request(
            server,
            "GET",
            "/nao-existe",
        )

        assert status == 404
        assert data["error"] == "Endpoint não encontrado"

    finally:
        server.shutdown()
        server.server_close()


def test_create_failure_rolls_back_before_repair(tmp_path):
    server, _ = start_server(tmp_path)

    target = tmp_path / "rollback_gateway.py"

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie rollback_gateway.py contendo "
                    "isto não é Python válido"
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"
        assert result["tests"]["success"] is False
        assert not target.exists()

    finally:
        server.shutdown()
        server.server_close()


def test_modify_failure_restores_original_file(tmp_path):
    target = tmp_path / "arquivo.py"
    target.write_text(
        'print("ORIGINAL")\n',
        encoding="utf-8",
    )

    server, _ = start_server(tmp_path)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    'Modifique arquivo.py '
                    'isto não é Python válido'
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"
        assert result["tests"]["success"] is False

        assert target.exists()
        assert target.read_text(
            encoding="utf-8"
        ) == 'print("ORIGINAL")\n'

    finally:
        server.shutdown()
        server.server_close()


def test_delete_failure_restores_original_file(tmp_path):
    target = tmp_path / "arquivo_delete.py"
    original = 'print("NAO DEVE SER PERDIDO")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    server, _ = start_server(tmp_path)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Delete arquivo_delete.py"
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200

        # O DELETE deve ser executado e, caso a etapa
        # posterior falhe, o backup deve restaurar o arquivo.
        assert result["status"] in {
            "committed",
            "rolled_back",
        }

        if result["status"] == "rolled_back":
            assert target.exists()
            assert target.read_text(
                encoding="utf-8"
            ) == original

    finally:
        server.shutdown()
        server.server_close()


def test_gateway_rolls_back_failed_execution(isolated_project):
    server, _ = start_server(isolated_project)

    try:
        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie gateway_falha.py contendo "
                    "isto não é Python válido"
                )
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"
        assert result["tests"]["success"] is False

        target = isolated_project / "gateway_falha.py"

        assert not target.exists()

    finally:
        server.shutdown()
        server.server_close()


def test_gateway_reports_rollback_failure(tmp_path, monkeypatch):
    server, _ = start_server(tmp_path)

    try:
        def failing_rollback(transaction):
            raise RuntimeError(
                "ROLLBACK_FAILURE_TEST"
            )

        monkeypatch.setattr(
            api.gateway.transactions,
            "rollback",
            failing_rollback,
        )

        def failing_execute(transaction):
            raise RuntimeError(
                "EXECUTION_FAILURE_TEST"
            )

        monkeypatch.setattr(
            api.gateway.executor,
            "execute",
            failing_execute,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": "Crie arquivo.py",
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 500
        assert "error" in result

        task = api.gateway.get_task(
            approval_id
        )

        assert task["status"] == "failed"

        error = task.get(
            "error",
            "",
        )

        assert "EXECUTION_FAILURE_TEST" in error

    finally:
        server.shutdown()
        server.server_close()




def test_gateway_reports_rollback_failure_separately(
    tmp_path,
    monkeypatch,
):
    server, _ = start_server(tmp_path)

    try:
        def failing_rollback(transaction):
            raise RuntimeError(
                "ROLLBACK_FAILURE_TEST"
            )

        monkeypatch.setattr(
            api.gateway.transactions,
            "rollback",
            failing_rollback,
        )

        def failing_execute(transaction):
            raise RuntimeError(
                "EXECUTION_FAILURE_TEST"
            )

        monkeypatch.setattr(
            api.gateway.executor,
            "execute",
            failing_execute,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": "Crie arquivo.py",
            },
        )

        assert status == 200

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 500
        assert "error" in result

        task = api.gateway.get_task(
            approval_id
        )

        assert task["status"] == "failed"

        assert (
            task["error"]
            == "EXECUTION_FAILURE_TEST"
        )

        assert (
            task["rollback_error"]
            == "ROLLBACK_FAILURE_TEST"
        )

    finally:
        server.shutdown()
        server.server_close()

def test_gateway_repairs_failed_task_and_commits(isolated_project, monkeypatch):
    from agent import DevAgent
    from core.gateway import DevAgentGateway

    agent = DevAgent(str(isolated_project))
    gateway = DevAgentGateway(
        agent,
        str(isolated_project),
    )

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: {
            "diagnosis": "Arquivo contém sintaxe inválida.",
            "correction": "Substituir pelo conteúdo Python válido.",
            "risk": "baixo",
            "action": "modify",
            "path": "reparado.py",
            "content": 'print("REPARADO")\n',
        },
    )

    original_generate = agent.ai.generate

    def fake_generate(prompt):
        if "reparado.py" in prompt.lower():
            return (
                '{"action":"modify",'
                '"path":"reparado.py",'
                '"content":"print(\\"REPARADO\\")\\n",'
                '"diagnosis":"Arquivo corrigido.",'
                '"correction":"Conteúdo válido.",'
                '"risk":"baixo"}'
            )
        return original_generate(prompt)

    monkeypatch.setattr(
        agent.ai,
        "generate",
        fake_generate,
    )

    server = None

    try:
        from http.server import HTTPServer

        api.agent = agent
        api.gateway = gateway

        server = HTTPServer(
            ("127.0.0.1", 0),
            api.APIHandler,
        )

        from threading import Thread

        thread = Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie reparado.py contendo "
                    "isto não é Python válido"
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "committed"
        assert result["repair_attempts"] == 1
        assert result["tests"]["success"] is True

        target = isolated_project / "reparado.py"

        assert target.exists()
        assert target.read_text(
            encoding="utf-8",
        ) == 'print("REPARADO")\n'

    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

def test_gateway_repairs_failed_task_and_commits(
    isolated_project,
    monkeypatch,
):
    server, _ = start_server(isolated_project)

    try:
        def fake_analyze_failure(
            instruction,
            error,
            test_output,
        ):
            return {
                "diagnosis": "Sintaxe inválida.",
                "correction": "Substituir pelo conteúdo Python válido.",
                "risk": "baixo",
                "action": "modify",
                "path": "reparado.py",
                "content": 'print("REPARADO")\n',
            }

        monkeypatch.setattr(
            api.gateway.repair_engine,
            "analyze_failure",
            fake_analyze_failure,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie reparado.py contendo "
                    "isto não é Python válido"
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "committed"
        assert result["repair_attempts"] == 1
        assert result["tests"]["success"] is True

        target = isolated_project / "reparado.py"

        assert target.exists()
        assert target.read_text(
            encoding="utf-8",
        ) == 'print("REPARADO")\n'

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] == "committed"
        assert task["repair_attempts"] == 1
        assert task["repair"]["action"] == "modify"

    finally:
        server.shutdown()
        server.server_close()

def test_gateway_repair_second_attempt_succeeds(
    isolated_project,
    monkeypatch,
):
    server, _ = start_server(isolated_project)

    try:
        calls = []

        def fake_analyze_failure(
            instruction,
            error,
            test_output,
        ):
            calls.append(len(calls) + 1)

            if len(calls) == 1:
                return {
                    "diagnosis": "Primeira correção insuficiente.",
                    "correction": "Aplicar uma correção ainda incompleta.",
                    "risk": "baixo",
                    "action": "modify",
                    "path": "reparo_duplo.py",
                    "content": "print(\n",
                }

            return {
                "diagnosis": "Segunda análise identificou a causa correta.",
                "correction": "Corrigir a sintaxe.",
                "risk": "baixo",
                "action": "modify",
                "path": "reparo_duplo.py",
                "content": 'print("CORRIGIDO")\n',
            }

        monkeypatch.setattr(
            api.gateway.repair_engine,
            "analyze_failure",
            fake_analyze_failure,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie reparo_duplo.py contendo "
                    "código inicialmente inválido"
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "committed"
        assert result["repair_attempts"] == 2
        assert result["tests"]["success"] is True

        assert calls == [1, 2]

        target = isolated_project / "reparo_duplo.py"

        assert target.exists()
        assert target.read_text(
            encoding="utf-8",
        ) == 'print("CORRIGIDO")\n'

    finally:
        server.shutdown()
        server.server_close()

def test_gateway_repair_limit_triggers_rollback(
    isolated_project,
    monkeypatch,
):
    server, _ = start_server(isolated_project)

    try:
        calls = []

        def fake_analyze_failure(
            instruction,
            error,
            test_output,
        ):
            calls.append(len(calls) + 1)

            return {
                "diagnosis": "Correção deliberadamente inválida.",
                "correction": "A correção continuará falhando.",
                "risk": "baixo",
                "action": "modify",
                "path": "limite_reparo.py",
                "content": "print(\n",
            }

        monkeypatch.setattr(
            api.gateway.repair_engine,
            "analyze_failure",
            fake_analyze_failure,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie limite_reparo.py contendo "
                    "código inválido"
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"
        assert result["repair_attempts"] == 2

        assert result["repair"]["status"] == "limit_reached"

        # O limite deve impedir uma terceira análise.
        assert calls == [1, 2]

        target = isolated_project / "limite_reparo.py"

        assert not target.exists()

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] == "rolled_back"
        assert task["repair_attempts"] == 2
        assert task["repair"]["status"] == "limit_reached"

    finally:
        server.shutdown()
        server.server_close()

def test_gateway_high_risk_repair_triggers_immediate_rollback(
    isolated_project,
    monkeypatch,
):
    server, _ = start_server(isolated_project)

    try:
        calls = []

        def fake_analyze_failure(
            instruction,
            error,
            test_output,
        ):
            calls.append(1)

            return {
                "diagnosis": "A correção exige alteração potencialmente perigosa.",
                "correction": "Alteração estrutural de alto risco.",
                "risk": "alto",
                "action": "modify",
                "path": "alto_risco.py",
                "content": 'print("NAO DEVE SER APLICADO")\n',
            }

        monkeypatch.setattr(
            api.gateway.repair_engine,
            "analyze_failure",
            fake_analyze_failure,
        )

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    "Crie alto_risco.py contendo "
                    "código inválido"
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] == "rolled_back"

        # Alto risco não deve consumir uma tentativa de reparo.
        assert result["repair_attempts"] == 0

        assert result["repair"]["risk"] == "alto"

        # A análise aconteceu uma única vez.
        assert calls == [1]

        target = isolated_project / "alto_risco.py"

        # A correção perigosa nunca deve ser aplicada.
        assert not target.exists()

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] == "rolled_back"
        assert task["repair_attempts"] == 0
        assert task["repair"]["risk"] == "alto"

    finally:
        server.shutdown()
        server.server_close()


def test_gateway_does_not_commit_when_git_returns_no_changes(tmp_path, monkeypatch):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [
                    {
                        "path": "app.py",
                        "action": "create",
                        "content": "print('hello')",
                    }
                ],
            }

        def build_transaction_from_approved_plan(self, plan):
            from core.schemas.models import Change, ChangeType, Transaction

            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="app.py",
                        content="print('hello')",
                    )
                ],
            )

    agent = FakeAgent()
    gateway = DevAgentGateway(agent, root=str(tmp_path))

    monkeypatch.setattr(
        gateway.supervisor,
        "approve",
        lambda approval_id: {
            "plan": {
                "instruction": "Crie app.py contendo print('hello')"
            }
        },
    )

    monkeypatch.setattr(
        gateway.tests,
        "run",
        lambda paths: {
            "success": True,
            "stdout": "",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        lambda *args, **kwargs: {
            "status": "no_changes",
            "transaction_id": args[0],
        },
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Crie app.py contendo print('hello')",
            "changes": [],
        }
    )

    with pytest.raises(RuntimeError, match="Commit Git não foi concluído"):
        gateway.approve(approval_id)

    assert (tmp_path / "app.py").exists() is False


def test_gateway_does_not_commit_when_git_returns_error(tmp_path, monkeypatch):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [
                    {
                        "path": "app.py",
                        "action": "create",
                        "content": "print('hello')",
                    }
                ],
            }

        def build_transaction_from_approved_plan(self, plan):
            from core.schemas.models import Change, ChangeType, Transaction

            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="app.py",
                        content="print('hello')",
                    )
                ],
            )

    agent = FakeAgent()
    gateway = DevAgentGateway(agent, root=str(tmp_path))

    monkeypatch.setattr(
        gateway.supervisor,
        "approve",
        lambda approval_id: {
            "plan": {
                "instruction": "Crie app.py contendo print('hello')"
            }
        },
    )

    monkeypatch.setattr(
        gateway.tests,
        "run",
        lambda paths: {
            "success": True,
            "stdout": "",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        lambda *args, **kwargs: {
            "status": "error",
            "transaction_id": args[0],
            "message": "simulated git failure",
        },
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Crie app.py contendo print('hello')",
            "changes": [],
        }
    )

    with pytest.raises(RuntimeError, match="Commit Git não foi concluído"):
        gateway.approve(approval_id)

    assert (tmp_path / "app.py").exists() is False

def test_gateway_rolls_back_when_git_commit_fails(tmp_path, monkeypatch):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None

        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [
                    {
                        "path": "commit_failure.py",
                        "action": "create",
                        "content": "print('should be removed')",
                    }
                ],
            }

        def build_transaction_from_approved_plan(self, plan):
            from core.schemas.models import Change, ChangeType, Transaction

            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="commit_failure.py",
                        content="print('should be removed')",
                    )
                ],
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    monkeypatch.setattr(
        gateway.supervisor,
        "approve",
        lambda approval_id: {
            "plan": {
                "instruction": "Crie commit_failure.py"
            }
        },
    )

    monkeypatch.setattr(
        gateway.tests,
        "run",
        lambda paths: {
            "success": True,
            "stdout": "",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        lambda *args, **kwargs: {
            "status": "error",
            "transaction_id": args[0],
            "message": "simulated git failure",
        },
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Crie commit_failure.py",
            "changes": [],
        }
    )

    with pytest.raises(
        RuntimeError,
        match="Commit Git não foi concluído",
    ):
        gateway.approve(approval_id)

    # O arquivo foi criado durante a execução,
    # mas deve desaparecer após a falha do commit.
    assert not (
        tmp_path / "commit_failure.py"
    ).exists()


def test_gateway_evaluate_execution_commits_when_verified(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAI:
        pass

    class FakeAgent:
        ai = FakeAI()

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    result = gateway._evaluate_execution({
        "success": True,
        "tests": {"success": True},
        "verification": {"success": True},
    })

    assert result == "commit"


def test_gateway_evaluate_execution_repairs_failed_tests(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAI:
        pass

    class FakeAgent:
        ai = FakeAI()

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    result = gateway._evaluate_execution({
        "success": False,
        "tests": {"success": False},
        "verification": None,
    })

    assert result == "repair"


def test_gateway_evaluate_execution_repairs_failed_verification(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAI:
        pass

    class FakeAgent:
        ai = FakeAI()

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    result = gateway._evaluate_execution({
        "success": True,
        "tests": {"success": True},
        "verification": {"success": False},
    })

    assert result == "repair"


def test_supervisor_preserves_approved_plan_snapshot(tmp_path):
    from core.supervisor import Supervisor

    supervisor = Supervisor(
        storage_path=str(
            tmp_path / "approvals.json"
        )
    )

    plan = {
        "instruction": "Crie app.py",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('hello')",
            }
        ],
    }

    approval_id = supervisor.request_approval(
        plan
    )

    plan["instruction"] = "ALTERADO"
    plan["changes"][0]["content"] = "MALICIOSO"

    request = supervisor.get(
        approval_id
    )

    assert request["plan"]["instruction"] == (
        "Crie app.py"
    )

    assert request["plan"]["changes"][0][
        "content"
    ] == "print('hello')"


def test_supervisor_returns_isolated_approval_data(tmp_path):
    from core.supervisor import Supervisor

    supervisor = Supervisor(
        storage_path=str(
            tmp_path / "approvals.json"
        )
    )

    plan = {
        "instruction": "Crie app.py",
        "changes": [],
    }

    approval_id = supervisor.request_approval(
        plan
    )

    request = supervisor.get(
        approval_id
    )

    request["plan"]["instruction"] = (
        "MUTADO"
    )

    fresh = supervisor.get(
        approval_id
    )

    assert fresh["plan"]["instruction"] == (
        "Crie app.py"
    )


def test_gateway_keeps_approval_pending_when_transaction_build_fails(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            raise RuntimeError(
                "simulated transaction build failure"
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    def fake_commit_transaction(**kwargs):
        transaction = kwargs["transaction"]
        return {
            "approval_id": kwargs["approval_id"],
            "status": "committed",
            "transaction_id": transaction.transaction_id,
            "tests": kwargs["test_result"],
            "repair": kwargs.get("repair"),
            "repair_attempts": 0,
            "error": None,
        }

    monkeypatch.setattr(
        gateway,
        "_commit_transaction",
        fake_commit_transaction,
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Criar app.py",
            "changes": [
                {
                    "path": "app.py",
                    "action": "create",
                    "content": "print('hello')",
                }
            ],
        }
    )

    with pytest.raises(
        RuntimeError,
        match="simulated transaction build failure",
    ):
        gateway.approve(approval_id)

    request = gateway.supervisor.get(approval_id)

    assert request["status"] == "pending"


def test_gateway_keeps_approval_pending_when_transaction_begin_fails(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
    )

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="app.py",
                        content="print('hello')",
                    )
                ],
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Criar app.py",
            "changes": [
                {
                    "path": "app.py",
                    "action": "create",
                    "content": "print('hello')",
                }
            ],
        }
    )

    monkeypatch.setattr(
        gateway.transactions,
        "begin",
        lambda transaction: (_ for _ in ()).throw(
            RuntimeError("simulated transaction begin failure")
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="simulated transaction begin failure",
    ):
        gateway.approve(approval_id)

    request = gateway.supervisor.get(approval_id)

    assert request["status"] == "pending"

def test_gateway_commit_failure_rolls_back_transaction(
    isolated_project,
    monkeypatch,
):
    from agent import DevAgent
    from core.gateway import DevAgentGateway

    agent = DevAgent(str(isolated_project))
    gateway = DevAgentGateway(
        agent,
        str(isolated_project),
    )

    def fake_commit_transaction(*args, **kwargs):
        return {
            "status": "failed",
            "message": "Falha simulada no commit Git.",
        }

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        fake_commit_transaction,
    )

    server = None
    try:
        from http.server import HTTPServer
        from threading import Thread

        api.agent = agent
        api.gateway = gateway

        server = HTTPServer(
            ("127.0.0.1", 0),
            api.APIHandler,
        )

        thread = Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()

        status, created = request(
            server,
            "POST",
            "/plan",
            {
                "instruction": (
                    'Crie commit_falha.py contendo '
                    'print("COMMIT TEST")'
                ),
            },
        )

        assert status == 200
        assert created["status"] == "pending"

        approval_id = created["approval_id"]

        status, result = request(
            server,
            "POST",
            f"/approve/{approval_id}",
        )

        assert status == 200
        assert result["status"] in {
            "failed",
            "rolled_back",
        }

        target = isolated_project / "commit_falha.py"

        assert not target.exists()

        status, task = request(
            server,
            "GET",
            f"/tasks/{approval_id}",
        )

        assert status == 200
        assert task["status"] in {
            "failed",
            "rolled_back",
        }

    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


def test_plan_endpoint_propagates_ai_provider_runtime_error():
    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("falha no provedor de IA")

    server, _ = start_server()
    original_agent = api.agent
    original_gateway = api.gateway

    try:
        api.agent = DevAgent(ai_adapter=FailingAdapter())

        response = request(
            server,
            "POST",
            "/plan",
            {"instruction": "Crie app.py"},
        )

        assert response[0] == 500
        assert "falha no provedor de IA" in response[1]["error"]
    finally:
        api.agent = original_agent
        api.gateway = original_gateway
        server.shutdown()
        server.server_close()


def test_plan_endpoint_propagates_ai_provider_http_error():
    class FailingAdapter:
        def generate(self, prompt):
            raise RuntimeError("HTTP 429")

    server, _ = start_server()
    original_agent = api.agent
    original_gateway = api.gateway

    try:
        api.agent = DevAgent(ai_adapter=FailingAdapter())

        response = request(
            server,
            "POST",
            "/plan",
            {"instruction": "Crie app.py"},
        )

        assert response[0] == 500
        assert "HTTP 429" in response[1]["error"]
    finally:
        api.agent = original_agent
        api.gateway = original_gateway
        server.shutdown()
        server.server_close()


def test_approved_task_history_preserves_transaction_metadata(tmp_path):
    from core.memory.task_history import TaskHistory

    history_path = tmp_path / "tasks.json"

    history = TaskHistory(
        storage_path=history_path
    )

    approval_id = "approval-metadata-integration"

    history.create(
        approval_id=approval_id,
        instruction="Crie app.py",
        plan={
            "instruction": "Crie app.py",
            "objective": "Criar aplicação principal",
            "changes": [
                {
                    "change_type": "create",
                    "path": "app.py",
                    "content": "print('OK')",
                    "reason": "Arquivo principal",
                }
            ],
            "tests": ["pytest -q"],
            "risks": ["baixo"],
        },
    )

    metadata = {
        "instruction": "Crie app.py",
        "objective": "Criar aplicação principal",
        "tests": ["pytest -q"],
        "risks": ["baixo"],
    }

    history.update(
        approval_id,
        extra={
            "metadata": metadata,
        },
    )

    reloaded = TaskHistory(
        storage_path=history_path
    )

    task = reloaded.get(approval_id)

    assert task is not None
    assert task["metadata"] == metadata
    assert task["plan"]["instruction"] == "Crie app.py"
    assert task["plan"]["objective"] == "Criar aplicação principal"
    assert task["plan"]["tests"] == ["pytest -q"]
    assert task["plan"]["risks"] == ["baixo"]

def test_gateway_preparation_failure_register_created_rolls_back(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.schemas.models import Change, ChangeType, Transaction

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="prep_failure.py",
                        content="print('x')",
                    ),
                ],
            )

    gateway = DevAgentGateway(FakeAgent(), root=str(tmp_path))

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Criar prep_failure.py",
            "changes": [
                {
                    "path": "prep_failure.py",
                    "action": "create",
                    "content": "print('x')",
                },
            ],
        }
    )

    def failing_register_created(transaction, path):
        raise RuntimeError("REGISTER_CREATED_FAILURE_TEST")

    executor_called = False

    def forbidden_execute(transaction):
        nonlocal executor_called
        executor_called = True

    monkeypatch.setattr(
        gateway.transactions,
        "register_created",
        failing_register_created,
    )
    monkeypatch.setattr(
        gateway.executor,
        "execute",
        forbidden_execute,
    )

    print("\n===== BEFORE APPROVE =====")
    print("APPROVAL:", approval_id)
    print("HISTORY PATH:", gateway.history.storage_path)
    print("HISTORY TASKS:", gateway.history.tasks)
    print("TASK FILE EXISTS:", gateway.history.storage_path.exists())

    result = gateway.approve(approval_id)

    print("\n===== AFTER APPROVE =====")
    print("RESULT:", result)
    print("HISTORY PATH:", gateway.history.storage_path)
    print("HISTORY TASKS:", gateway.history.tasks)
    print("TASK FILE EXISTS:", gateway.history.storage_path.exists())

    if gateway.history.storage_path.exists():
        print("TASK FILE:")
        print(gateway.history.storage_path.read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert "REGISTER_CREATED_FAILURE_TEST" in result["error"]
    assert executor_called is False
    assert not (tmp_path / "prep_failure.py").exists()


def test_gateway_preparation_failure_backup_file_rolls_back(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.schemas.models import Change, ChangeType, Transaction

    target = tmp_path / "prep_backup_failure.py"
    target.write_text("original", encoding="utf-8")

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.MODIFY,
                        path="prep_backup_failure.py",
                        content="alterado",
                    ),
                ],
            )

    gateway = DevAgentGateway(FakeAgent(), root=str(tmp_path))

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Modificar prep_backup_failure.py",
            "changes": [
                {
                    "path": "prep_backup_failure.py",
                    "action": "modify",
                    "content": "alterado",
                },
            ],
        }
    )

    def failing_backup_file(transaction, path):
        raise RuntimeError("BACKUP_FILE_FAILURE_TEST")

    executor_called = False

    def forbidden_execute(transaction):
        nonlocal executor_called
        executor_called = True

    monkeypatch.setattr(
        gateway.transactions,
        "backup_file",
        failing_backup_file,
    )
    monkeypatch.setattr(
        gateway.executor,
        "execute",
        forbidden_execute,
    )

    result = gateway.approve(approval_id); print("\n===== APPROVE RESULT ====="); print(result)

    assert result["status"] == "failed"
    assert "BACKUP_FILE_FAILURE_TEST" in result["error"]
    assert executor_called is False
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "original"


def test_gateway_commit_state_is_consistent_across_transaction_repair_and_history(
    isolated_project,
):
    from core.gateway import DevAgentGateway
    from agent import DevAgent

    gateway = DevAgentGateway(
        DevAgent(str(isolated_project)),
        root=str(isolated_project),
    )

    def fake_process(instruction):
        return {
            "instruction": instruction,
            "objective": "teste",
            "changes": [
                {
                    "change_type": "create",
                    "path": "state_consistency.py",
                    "content": "VALUE = 1\n",
                }
            ],
            "tests": [],
            "risks": [],
        }

    gateway.agent.process = fake_process

    created = gateway.create_task(
        "criar arquivo de consistência"
    )

    approval_id = created["approval_id"]

    result = gateway.approve(approval_id)

    print("\\n===== APPROVE RESULT =====")
    print(result)

    assert result["status"] == "committed"
    assert result["transaction_id"]
    assert result["repair_attempts"] == 0

    task = gateway.history.get(approval_id)

    assert task is not None
    assert task["status"] == "committed"
    assert task["transaction_id"] == result["transaction_id"]
    assert task["repair_attempts"] == result["repair_attempts"]

    assert task["metadata"]["repair_cycle"]["status"] == "committed"
    assert task["repair_state"]["status"] == "committed"
    assert task["repair_state"]["transaction_id"] == result["transaction_id"]

def test_gateway_rollback_state_is_consistent_across_history_and_result(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState
    from agent import DevAgent

    gateway = DevAgentGateway(DevAgent(str(tmp_path)), root=str(tmp_path))

    approval_id = "state-consistency-rollback"

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "criar arquivo que falha",
            "objective": "teste",
            "changes": [
                {
                    "change_type": "create",
                    "path": "state_consistency_rollback.py",
                    "content": "VALUE = 1\n",
                }
            ],
            "tests": [],
            "risks": [],
        },
    )

    class FailingTests:
        def run(self, paths):
            return {
                "success": False,
                "output": "TEST_FAILURE",
            }

    monkeypatch.setattr(gateway, "tests", FailingTests())

    result = gateway.approve(approval_id); print("\n===== APPROVE RESULT ====="); print(result)

    assert result["status"] == "rolled_back"
    assert result["transaction_id"]
    assert result["repair_attempts"] >= 1

    task = gateway.history.get(approval_id)

    assert task is not None
    assert task["status"] == "rolled_back"
    assert task["transaction_id"] == result["transaction_id"]
    assert task["repair_attempts"] == result["repair_attempts"]

    repair_state = task["repair_state"]

    assert repair_state["transaction_id"] == result["transaction_id"]
    assert repair_state["status"] == "rolled_back"
    assert repair_state["attempts"] == result["repair_attempts"]

    assert task["metadata"]["repair_cycle"]["status"] == "rolled_back"

    assert not (tmp_path / "state_consistency_rollback.py").exists()


def test_gateway_commit_failure_with_successful_rollback_is_consistent(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.gateway import CommitTransactionError
    from agent import DevAgent

    gateway = DevAgentGateway(DevAgent(str(tmp_path)), root=str(tmp_path))

    approval_id = "state-consistency-commit-failure"

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "criar arquivo e falhar commit",
            "objective": "teste",
            "changes": [
                {
                    "change_type": "create",
                    "path": "commit_failure_state.py",
                    "content": "VALUE = 1\n",
                }
            ],
            "tests": [],
            "risks": [],
        },
    )

    def failing_commit(*args, **kwargs):
        raise CommitTransactionError(
            "COMMIT_FAILURE_TEST",
            result={
                "status": "failed",
                "message": "COMMIT_FAILURE_TEST",
            },
        )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        failing_commit,
    )

    try:
        gateway.approve(approval_id)
        assert False, "Gateway deveria propagar CommitTransactionError."
    except CommitTransactionError as error:
        assert "COMMIT_FAILURE_TEST" in str(error)

        rollback = error.result["rollback"]

        assert rollback["status"] == "rolled_back"
        assert rollback["transaction_id"]
        assert "rollback_error" not in rollback

        task = gateway.history.get(approval_id)

        assert task is not None
        assert task["status"] == "rolled_back"
        assert task["transaction_id"] == rollback["transaction_id"]
        assert task["repair_attempts"] == rollback["repair_attempts"]
        assert task["repair_state"]["status"] == "rolled_back"
        assert (
            task["repair_state"]["transaction_id"]
            == rollback["transaction_id"]
        )
        assert task["metadata"]["repair_cycle"]["status"] == "rolled_back"

    assert not (tmp_path / "commit_failure_state.py").exists()


def test_commit_transaction_does_not_mark_committed_before_git_success(
    tmp_path,
    monkeypatch,
):
    from agent import DevAgent
    from core.gateway import (
        CommitTransactionError,
        DevAgentGateway,
    )
    from core.engine.repair_cycle_state import RepairCycleState
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
        TransactionStatus,
    )

    gateway = DevAgentGateway(
        DevAgent(str(tmp_path)),
        root=str(tmp_path),
    )

    transaction = Transaction(
        transaction_id="tx-commit-order",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="app.py",
                content="VALUE = 1\n",
            )
        ],
    )

    repair_state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    def failing_commit(*args, **kwargs):
        return {
            "status": "failed",
            "message": "COMMIT_FAILURE_ORDER_TEST",
        }

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        failing_commit,
    )

    with pytest.raises(
        CommitTransactionError,
        match="COMMIT_FAILURE_ORDER_TEST",
    ):
        gateway._commit_transaction(
            approval_id="approval-commit-order",
            instruction="criar app.py",
            transaction=transaction,
            test_result={"success": True},
            repair_state=repair_state,
        )

    assert transaction.status != TransactionStatus.COMMITTED
    assert repair_state.status != "committed"
    assert transaction.repair_state == {}



def test_gateway_commit_failure_and_rollback_failure_propagates_rollback_error(
    tmp_path,
    monkeypatch,
):
    from agent import DevAgent
    from core.gateway import (
        CommitTransactionError,
        DevAgentGateway,
    )

    class FakeAgent:
        ai = None

        def process(self, instruction):
            return {
                "instruction": instruction,
                "objective": "teste",
                "changes": [
                    {
                        "path": "commit_rollback_failure.py",
                        "action": "create",
                        "content": "VALUE = 1\n",
                    }
                ],
            }

        def build_transaction_from_approved_plan(self, plan):
            from core.schemas.models import (
                Change,
                ChangeType,
                Transaction,
            )

            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="commit_rollback_failure.py",
                        content="VALUE = 1\n",
                    )
                ],
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "criar commit_rollback_failure.py",
            "objective": "teste",
            "changes": [
                {
                    "change_type": "create",
                    "path": "commit_rollback_failure.py",
                    "content": "VALUE = 1\n",
                }
            ],
            "tests": [],
            "risks": [],
        }
    )

    monkeypatch.setattr(
        gateway.tests,
        "run",
        lambda paths: {
            "success": True,
            "stdout": "",
            "stderr": "",
        },
    )

    def failing_commit(*args, **kwargs):
        raise CommitTransactionError(
            "COMMIT_FAILURE_TEST",
            result={
                "status": "failed",
                "message": "COMMIT_FAILURE_TEST",
            },
        )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        failing_commit,
    )

    def failing_rollback(transaction):
        raise RuntimeError("ROLLBACK_FAILURE_TEST")

    monkeypatch.setattr(
        gateway.transactions,
        "rollback",
        failing_rollback,
    )

    with pytest.raises(
        RuntimeError,
        match="ROLLBACK_FAILURE_TEST",
    ) as exc_info:
        gateway.approve(approval_id)

    # A falha de rollback deve substituir a falha de commit
    # como exceção operacional propagada.
    assert isinstance(
        exc_info.value.__cause__,
        CommitTransactionError,
    )

    task = gateway.history.get(approval_id)

    assert task is not None
    assert task["status"] == "failed"
    assert task["rollback_error"] == "ROLLBACK_FAILURE_TEST"
    assert "COMMIT_FAILURE_TEST" in task["error"]

    assert (
        task["repair_state"]["status"]
        == "failed"
    )


def test_gateway_keeps_approval_pending_when_post_begin_setup_fails(
    tmp_path,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
    )

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="app.py",
                        content="print('hello')",
                    )
                ],
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Criar app.py",
            "changes": [
                {
                    "path": "app.py",
                    "action": "create",
                    "content": "print('hello')",
                }
            ],
        }
    )

    def fail_restore(transaction):
        raise RuntimeError(
            "simulated post-begin setup failure"
        )

    monkeypatch.setattr(
        gateway,
        "_restore_repair_state",
        fail_restore,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated post-begin setup failure",
    ):
        gateway.approve(approval_id)

    request = gateway.supervisor.get(approval_id)

    assert request["status"] == "pending"


def test_gateway_serializes_concurrent_approve_for_same_request(
    tmp_path,
    monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )

    from core.gateway import DevAgentGateway
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
    )

    class FakeAgent:
        ai = None

        def build_transaction_from_approved_plan(self, plan):
            return Transaction(
                transaction_id="",
                changes=[
                    Change(
                        change_type=ChangeType.CREATE,
                        path="app.py",
                        content="print('hello')",
                    )
                ],
            )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=str(tmp_path),
    )

    approval_id = gateway.supervisor.request_approval(
        {
            "instruction": "Criar app.py",
            "changes": [
                {
                    "path": "app.py",
                    "action": "create",
                    "content": "print('hello')",
                }
            ],
        }
    )

    barrier = Barrier(2)
    entered = {"count": 0}

    original_prepare = gateway.supervisor.prepare_approval

    def synchronized_prepare(approval_id):
        entered["count"] += 1
        if entered["count"] <= 2:
            barrier.wait(timeout=5)
        return original_prepare(approval_id)

    monkeypatch.setattr(
        gateway.supervisor,
        "prepare_approval",
        synchronized_prepare,
    )

    def approve():
        try:
            return ("success", gateway.approve(approval_id))
        except Exception as exc:
            return ("error", type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: approve(), range(2)))

    print("\n===== CONCURRENT APPROVE RESULTS =====")
    for result in results:
        print(repr(result))
    print("===== FILE EXISTS =====")
    print((tmp_path / "app.py").exists())

    successes = [
        result
        for result in results
        if result[0] == "success"
    ]
    errors = [
        result
        for result in results
        if result[0] == "error"
    ]

    assert len(successes) == 1
    assert len(errors) == 1

    assert errors[0][1] == "ValueError"
    assert errors[0][2] == "Solicitação não está pendente."

    request = gateway.supervisor.get(approval_id)
    assert request["status"] == "approved"

    assert len(list(tmp_path.glob("app.py"))) == 1


def test_gateway_history_update_ignores_missing_task_keyerror(isolated_project):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    def fake_update(*args, **kwargs):
        raise KeyError("Tarefa não encontrada.")

    gateway.history.update = fake_update

    result = gateway._history_update("missing-id", status="failed")

    assert result is None


def test_gateway_history_update_reraises_unexpected_keyerror(isolated_project):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    def fake_update(*args, **kwargs):
        raise KeyError("Outra chave")

    gateway.history.update = fake_update

    with pytest.raises(KeyError, match="Outra chave"):
        gateway._history_update("task-id", status="failed")


def test_gateway_create_task_rejects_invalid_instruction(isolated_project):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    with pytest.raises(ValueError, match="Instrução inválida"):
        gateway.create_task("   ")


def test_gateway_create_task_rejects_non_dict_agent_result(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        def process(self, instruction):
            return None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=str(isolated_project),
    )

    with pytest.raises(
        ValueError,
        match="Plano inválido retornado pelo agente",
    ):
        gateway.create_task("teste")


def test_gateway_create_task_rejects_non_list_changes(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": {},
            }

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=str(isolated_project),
    )

    with pytest.raises(
        ValueError,
        match="Plano não possui lista de alterações",
    ):
        gateway.create_task("teste")


def test_gateway_create_task_rejects_non_dict_change(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": ["invalid"],
            }

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=str(isolated_project),
    )

    with pytest.raises(
        ValueError,
        match="Alteração inválida no plano",
    ):
        gateway.create_task("teste")


def test_gateway_create_task_rejects_change_without_path(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [
                    {
                        "change_type": "create",
                        "content": "print('x')",
                    }
                ],
            }

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=str(isolated_project),
    )

    with pytest.raises(
        ValueError,
        match="Alteração sem caminho",
    ):
        gateway.create_task("teste")


def test_gateway_create_task_rejects_non_string_content(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        def process(self, instruction):
            return {
                "instruction": instruction,
                "changes": [
                    {
                        "change_type": "create",
                        "path": "app.py",
                        "content": None,
                    }
                ],
            }

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=str(isolated_project),
    )

    with pytest.raises(
        ValueError,
        match="Conteúdo inválido para alteração",
    ):
        gateway.create_task("teste")


def test_gateway_execute_approved_rejects_missing_task(isolated_project):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    gateway.supervisor.get = lambda approval_id: None

    with pytest.raises(
        KeyError,
        match="Tarefa não encontrada",
    ):
        gateway.execute_approved("missing")


def test_gateway_execute_approved_rejects_unapproved_task(isolated_project):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    gateway.supervisor.get = lambda approval_id: {
        "status": "pending",
    }

    with pytest.raises(
        ValueError,
        match="Tarefa não está aprovada",
    ):
        gateway.execute_approved("pending")


def test_gateway_execute_approved_delegates_approved_task(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway

    gateway = DevAgentGateway(
        agent=None,
        root=str(isolated_project),
    )

    gateway.supervisor.get = lambda approval_id: {
        "status": "approved",
    }

    called = []

    def fake_approve(approval_id):
        called.append(approval_id)
        return {
            "success": True,
            "status": "committed",
        }

    monkeypatch.setattr(
        gateway,
        "approve",
        fake_approve,
    )

    result = gateway.execute_approved("approval-123")

    assert called == ["approval-123"]
    assert result["status"] == "committed"


def test_gateway_attempt_repair_rechecks_limit_after_analysis(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    calls = []

    def fake_can_continue():
        calls.append(1)

        if len(calls) == 1:
            return True

        state.attempts = state.max_attempts
        return False

    monkeypatch.setattr(
        state,
        "can_continue",
        fake_can_continue,
    )

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: {
            "diagnosis": "erro",
            "correction": "corrigir",
            "risk": "baixo",
            "action": "modify",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
        },
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "limit_reached"
    assert result["success"] is False
    assert state.attempts == state.max_attempts

# ===== GATEWAY DEFENSIVE COVERAGE =====

def test_gateway_evaluate_execution_rolls_back_non_dict(isolated_project):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    assert gateway._evaluate_execution(None) == "rollback"


def test_gateway_evaluate_execution_repairs_failed_tests_after_success(
    isolated_project,
):
    from core.gateway import DevAgentGateway

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    result = gateway._evaluate_execution(
        {
            "success": True,
            "verification": {"success": True},
            "tests": {"success": False},
        }
    )

    assert result == "repair"


def test_gateway_attempt_repair_stops_when_limit_already_reached(
    isolated_project,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        attempts=2,
        max_attempts=2,
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "limit_reached"
    assert result["success"] is False
    assert result["repair"]["action"] == "none"


def test_gateway_attempt_repair_normalizes_invalid_diagnosis(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: None,
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "no_repair"
    assert result["success"] is False
    assert result["repair"]["action"] == "none"
    assert result["repair"]["diagnosis"] == (
        "Diagnóstico de reparo inválido."
    )
    assert state.attempts == 0


def test_gateway_attempt_repair_returns_no_repair_for_none_action(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    diagnosis = {
        "diagnosis": "Sem correção segura.",
        "correction": "",
        "risk": "baixo",
        "action": "none",
        "path": "",
        "content": "",
    }

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: diagnosis,
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "no_repair"
    assert result["success"] is False
    assert result["repair"] == diagnosis
    assert state.attempts == 0


def test_gateway_attempt_repair_normalizes_invalid_repair_result(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    diagnosis = {
        "diagnosis": "Erro corrigível.",
        "correction": "Aplicar correção.",
        "risk": "baixo",
        "action": "modify",
        "path": "arquivo.py",
        "content": "VALUE = 1\n",
    }

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: diagnosis,
    )

    monkeypatch.setattr(
        gateway.repair_executor,
        "execute_repair",
        lambda *args, **kwargs: None,
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "failed"
    assert result["success"] is False
    assert result["error"] == "Resultado de reparo inválido."
    assert result["repair_attempts"] == 1
    assert state.status == "failed"


def test_gateway_attempt_repair_handles_invalid_test_result(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    diagnosis = {
        "diagnosis": "Erro corrigível.",
        "correction": "Aplicar correção.",
        "risk": "baixo",
        "action": "modify",
        "path": "arquivo.py",
        "content": "VALUE = 1\n",
    }

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: diagnosis,
    )

    monkeypatch.setattr(
        gateway.repair_executor,
        "execute_repair",
        lambda *args, **kwargs: {
            "success": False,
            "status": "repair_failed",
            "tests": None,
        },
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "repair_failed"
    assert result["success"] is False
    assert result["tests"]["status"] == "invalid_test_result"
    assert result["tests"]["success"] is False
    assert state.status == "failed"
    assert state.attempts == 1


def test_gateway_attempt_repair_rechecks_limit_after_analysis(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    calls = []

    def fake_can_continue():
        calls.append(1)

        if len(calls) == 1:
            return True

        state.attempts = state.max_attempts
        return False

    monkeypatch.setattr(
        state,
        "can_continue",
        fake_can_continue,
    )

    monkeypatch.setattr(
        gateway.repair_engine,
        "analyze_failure",
        lambda **kwargs: {
            "diagnosis": "erro",
            "correction": "corrigir",
            "risk": "baixo",
            "action": "modify",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
        },
    )

    result = gateway._attempt_repair(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "limit_reached"
    assert result["success"] is False
    assert state.attempts == state.max_attempts
    assert len(calls) == 2


def test_gateway_run_repair_cycle_rolls_back_when_limit_reached(
    isolated_project,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        attempts=2,
        max_attempts=2,
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "rolled_back"
    assert result["repair_attempts"] == 2
    assert result["repair"]["status"] == "limit_reached"


def test_gateway_run_repair_cycle_handles_repair_failed_without_tests(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": False,
            "status": "repair_failed",
            "tests": None,
            "repair": {
                "action": "modify",
                "risk": "baixo",
            },
        },
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "rolled_back"
    assert result["tests"]["success"] is False
    assert result["repair_attempts"] == 0


def test_gateway_run_repair_cycle_handles_unknown_repair_status(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": False,
            "status": "future_unknown_status",
            "tests": {
                "success": False,
            },
            "repair": {
                "action": "modify",
                "risk": "baixo",
            },
        },
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "rolled_back"
    assert result["repair_attempts"] == 0


def test_gateway_run_repair_cycle_returns_verified_when_initial_tests_pass(
    isolated_project,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": True,
            "stdout": "OK",
            "stderr": "",
        },
        repair_state=state,
    )

    assert result["success"] is True
    assert result["status"] == "verified"
    assert result["repair"] is None
    assert result["repair_attempts"] == 0


def test_gateway_run_repair_cycle_handles_success_without_successful_tests(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": True,
            "status": "unexpected_success",
            "tests": {
                "success": False,
            },
            "repair": {
                "action": "modify",
                "risk": "baixo",
            },
        },
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "rolled_back"
    assert result["success"] is False
    assert result["repair_attempts"] == 0


def test_gateway_run_repair_cycle_handles_success_without_test_dict(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = type(
        "Transaction",
        (),
        {
            "transaction_id": "test-transaction",
            "repair_state": None,
            "metadata": {},
        },
    )()

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": True,
            "status": "unexpected_success",
            "tests": None,
            "repair": {
                "action": "modify",
                "risk": "baixo",
            },
        },
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["status"] == "rolled_back"
    assert result["success"] is False
    assert result["repair_attempts"] == 0


def test_gateway_run_repair_cycle_marks_limit_after_repair_failed_with_tests(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState
    from core.schemas.models import Transaction

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = gateway.transactions.begin(
        Transaction(
            transaction_id="test-repair-limit-after-failure",
            changes=[],
        )
    )

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        attempts=1,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": False,
            "status": "repair_failed",
            "tests": {
                "success": False,
                "stderr": "falha persistente",
                "stdout": "",
            },
            "repair": {
                "action": "modify",
                "risk": "baixo",
                "path": "arquivo.py",
            },
        },
    )

    monkeypatch.setattr(
        state,
        "can_continue",
        lambda: False,
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha inicial",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == "rolled_back"
    assert result["repair_attempts"] == 1
    assert result["tests"]["success"] is False
    assert result["repair"]["status"] == "limit_reached"



def test_gateway_run_repair_cycle_marks_limit_with_non_dict_repair(
    isolated_project,
    monkeypatch,
):
    from core.gateway import DevAgentGateway
    from core.engine.repair_cycle_state import RepairCycleState
    from core.schemas.models import Transaction

    class FakeAgent:
        ai = None

    gateway = DevAgentGateway(
        agent=FakeAgent(),
        root=isolated_project,
    )

    transaction = gateway.transactions.begin(
        Transaction(
            transaction_id="test-limit-non-dict-repair",
            changes=[],
        )
    )

    state = RepairCycleState(
        transaction_id=transaction.transaction_id,
        attempts=1,
        max_attempts=2,
    )

    monkeypatch.setattr(
        gateway,
        "_attempt_repair",
        lambda **kwargs: {
            "success": False,
            "status": "repair_failed",
            "tests": {
                "success": False,
                "stderr": "falha persistente",
                "stdout": "",
            },
            "repair": "invalid-repair-result",
        },
    )

    can_continue_results = iter([True, False])
    monkeypatch.setattr(
        state,
        "can_continue",
        lambda: next(can_continue_results),
    )

    result = gateway._run_repair_cycle(
        instruction="reparar",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "falha inicial",
            "stdout": "",
        },
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == "rolled_back"
    assert result["repair_attempts"] == 1
    assert result["tests"]["success"] is False
    assert result["repair"] is None
