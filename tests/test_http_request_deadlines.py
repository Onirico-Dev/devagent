"""Incomplete local clients must not occupy the single HTTP worker forever."""
import json
import socket
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

import api


@pytest.fixture
def bounded_server(monkeypatch):
    calls = []

    class Service:
        def health(self):
            return {"status": "ok", "service": "devagent"}

        def create_task(self, instruction):
            calls.append("plan")
            raise TimeoutError("simulated provider timeout")

        def start_task_investigation(self, task_id):
            calls.append("investigation")
            return {"status": "running", "job_id": "test"}

    monkeypatch.setattr(api, "APIService", lambda *args: Service())
    monkeypatch.setattr(api.APIHandler, "REQUEST_READ_TIMEOUT", 0.15, raising=False)
    server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield server, calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()


def health(server):
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=1)
    try:
        client.request("GET", "/health")
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["status"] == "ok"
    finally:
        client.close()


def test_incomplete_headers_release_worker_for_next_client(bounded_server):
    server, calls = bounded_server
    idle = socket.create_connection(("127.0.0.1", server.server_port), timeout=1)
    try:
        idle.sendall(b"GET /health HTTP/1.1\r\nHost:")
        health(server)
        assert calls == []
    finally:
        idle.close()


@pytest.mark.parametrize("route", ["/plan", "/consultations", "/tasks/1/investigation"])
def test_incomplete_body_returns_408_and_releases_worker(bounded_server, route):
    server, calls = bounded_server
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=1)
    try:
        client.putrequest("POST", route)
        client.putheader("Content-Type", "application/json")
        client.putheader("Content-Length", "50")
        client.endheaders()
        client.send(b"{}")
        response = client.getresponse()
        assert response.status == 408
        assert "error" in json.loads(response.read())
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        assert calls == []
        health(server)
    finally:
        client.close()


def test_truncated_investigation_is_rejected_before_starting_job(bounded_server):
    server, calls = bounded_server
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=1)
    try:
        client.putrequest("POST", "/tasks/1/investigation")
        client.putheader("Content-Type", "application/json")
        client.putheader("Content-Length", "50")
        client.endheaders()
        client.send(b"{}")
        client.sock.shutdown(socket.SHUT_WR)
        response = client.getresponse()
        assert response.status == 400
        response.read()
        assert calls == []
        health(server)
    finally:
        client.close()


def test_provider_timeout_is_not_misclassified_as_request_read_timeout(bounded_server):
    server, calls = bounded_server
    client = HTTPConnection("127.0.0.1", server.server_port, timeout=1)
    try:
        client.request("POST", "/plan", body=json.dumps({"instruction": "Crie a.py"}),
                       headers={"Content-Type": "application/json"})
        response = client.getresponse()
        assert response.status == 500
        assert response.status != 408
        response.read()
        assert calls == ["plan"]
        health(server)
    finally:
        client.close()
