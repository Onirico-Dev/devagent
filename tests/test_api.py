import json
from http.client import HTTPConnection
from threading import Thread
from http.server import HTTPServer

import api


def start_server():
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
):
    connection = HTTPConnection(
        "127.0.0.1",
        server.server_port,
    )

    headers = {}

    encoded_body = None

    if body is not None:
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


def test_full_task_flow():
    server, _ = start_server()

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

        import os

        if os.path.exists("api_teste.py"):
            os.remove("api_teste.py")


def test_reject_task():
    server, _ = start_server()

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

        import os

        if os.path.exists("rejeitado.py"):
            os.remove("rejeitado.py")


def test_rollback_task():
    server, _ = start_server()

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

        import os

        if os.path.exists("api_falha.py"):
            os.remove("api_falha.py")
