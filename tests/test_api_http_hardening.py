import json
import socket
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

import api


class FakeAPIService:
    def health(self):
        return {"status": "ok", "service": "devagent"}

    def list_tasks(self):
        return []

    def latest_task(self):
        return None

    def get_task(self, task_id):
        return {"task_id": task_id}

    def create_task(self, instruction):
        return {
            "approval_id": "approval-test",
            "instruction": instruction,
        }

    def approve(self, approval_id):
        return {
            "status": "committed",
            "approval_id": approval_id,
        }

    def reject(self, approval_id):
        return {
            "status": "rejected",
            "approval_id": approval_id,
        }


@pytest.fixture
def http_server(monkeypatch):
    monkeypatch.setattr(
        api,
        "APIService",
        lambda agent, gateway: FakeAPIService(),
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

    yield server

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def send_request(server, method, path, body=None):
    connection = HTTPConnection(
        "127.0.0.1",
        server.server_port,
        timeout=10,
    )

    encoded = None
    headers = {}

    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    connection.request(
        method,
        path,
        body=encoded,
        headers=headers,
    )

    response = connection.getresponse()
    status = response.status
    raw = response.read()
    response_headers = dict(response.getheaders())

    connection.close()

    data = json.loads(raw.decode("utf-8")) if raw else {}

    return status, data, response_headers


def test_get_health_accepts_query_parameters(http_server):
    status, data, _ = send_request(
        http_server,
        "GET",
        "/health?probe=1",
    )

    assert status == 200
    assert data["status"] == "ok"


def test_get_task_accepts_query_parameters(http_server):
    status, data, _ = send_request(
        http_server,
        "GET",
        "/tasks/task-123?details=true",
    )

    assert status == 200
    assert data["task_id"] == "task-123"


def test_post_plan_accepts_query_parameters(http_server):
    status, data, _ = send_request(
        http_server,
        "POST",
        "/plan?source=studio",
        {"instruction": "teste"},
    )

    assert status == 200
    assert data["approval_id"] == "approval-test"


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/approve/approval-123?source=studio", "committed"),
        ("/reject/approval-123?source=studio", "rejected"),
    ],
)
def test_post_approval_routes_accept_query_parameters(
    http_server,
    path,
    expected_status,
):
    status, data, _ = send_request(
        http_server,
        "POST",
        path,
    )

    assert status == 200
    assert data["status"] == expected_status
    assert data["approval_id"] == "approval-123"


def test_post_plan_rejects_body_over_one_mib(http_server):
    connection = HTTPConnection(
        "127.0.0.1",
        http_server.server_port,
        timeout=10,
    )

    try:
        connection.putrequest("POST", "/plan")
        connection.putheader(
            "Content-Type",
            "application/json",
        )
        connection.putheader(
            "Content-Length",
            str(1024 * 1024 + 100),
        )
        connection.endheaders()

        response = connection.getresponse()
        status = response.status
        data = json.loads(response.read().decode("utf-8"))

        assert status == 413
        assert "error" in data

    finally:
        connection.close()


def test_json_responses_include_security_headers(http_server):
    status, data, headers = send_request(
        http_server,
        "GET",
        "/health",
    )

    assert status == 200
    assert data["status"] == "ok"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-cache"


def test_get_unexpected_exception_returns_json_500(
    http_server,
    monkeypatch,
):
    class BrokenAPIService:
        def health(self):
            raise RuntimeError("falha interna simulada")

    monkeypatch.setattr(
        api,
        "APIService",
        lambda agent, gateway: BrokenAPIService(),
    )

    status, data, _ = send_request(
        http_server,
        "GET",
        "/health",
    )

    assert status == 500
    assert data["error"] == "falha interna simulada"

def test_post_plan_rejects_truncated_request_body(http_server):
    connection = socket.create_connection(
        ("127.0.0.1", http_server.server_port),
        timeout=10,
    )

    try:
        request = (
            b"POST /plan HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 10\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"{}"
        )

        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)

        response = bytearray()

        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)

        headers, body = bytes(response).split(
            b"\r\n\r\n",
            1,
        )

        status_line = headers.split(b"\r\n", 1)[0]
        status = int(status_line.split()[1])

        data = json.loads(body.decode("utf-8"))

        assert status == 400
        assert data["error"] == "JSON inválido"

    finally:
        connection.close()
