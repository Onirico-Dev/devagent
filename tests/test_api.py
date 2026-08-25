import json
from http.client import HTTPConnection
from threading import Thread
from http.server import HTTPServer

import api


def start_server(root=None):
    if root is not None:
        from agent import DevAgent
        from core.gateway import DevAgentGateway

        api.agent = DevAgent(str(root))
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
