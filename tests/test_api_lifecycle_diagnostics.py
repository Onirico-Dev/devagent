"""Server lifecycle diagnostics preserve existing exit semantics."""
import json
from http.client import HTTPConnection
from threading import Thread

import pytest

import api


@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE"), SystemExit(7)])
def test_loop_failure_is_logged_closed_and_propagated(monkeypatch, capsys, failure):
    closed = []

    class Server:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            raise failure

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(api, "HTTPServer", Server)
    with pytest.raises(type(failure)) as caught:
        api.run()
    assert caught.value is failure
    assert closed == [True]
    err = capsys.readouterr().err
    assert type(failure).__name__ in err
    assert "PRIVATE" not in err
    assert "loop_failure" in err


def test_bind_failure_is_identified_without_logging_message(monkeypatch, capsys):
    failure = OSError(98, "PRIVATE")

    def fail(*args):
        raise failure

    monkeypatch.setattr(api, "HTTPServer", fail)
    with pytest.raises(OSError) as caught:
        api.run()
    assert caught.value is failure
    err = capsys.readouterr().err
    assert "startup_failure" in err
    assert "OSError" in err
    assert "PRIVATE" not in err


@pytest.mark.parametrize("interrupt, reason", [
    (False, "loop_returned"), (True, "keyboard_interrupt"),
])
def test_normal_exit_and_interrupt_are_distinct(monkeypatch, capsys, interrupt, reason):
    closed = []

    class Server:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            if interrupt:
                raise KeyboardInterrupt

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(api, "HTTPServer", Server)
    api.run()
    assert closed == [True]
    assert reason in capsys.readouterr().err


def test_unexpected_route_error_logs_only_class(monkeypatch):
    handler = object.__new__(api.APIHandler)
    logs, responses = [], []
    monkeypatch.setattr(handler, "log_error", lambda *args: logs.append(args))
    monkeypatch.setattr(handler, "send_json", lambda *args: responses.append(args))
    handler.handle_error(RuntimeError("PRIVATE"))
    assert logs == [("Falha interna na rota: %s", "RuntimeError")]
    assert responses[0][0] == 500


def test_http_server_survives_route_exception_and_invalid_json(monkeypatch):
    calls = []

    class Service:
        def health(self):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("simulated route failure")
            return {"status": "ok"}

    monkeypatch.setattr(api, "APIService", lambda *args: Service())
    server = api.HTTPServer(("127.0.0.1", 0), api.APIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for method, body, status in [("GET", None, 500), ("POST", "{", 400), ("GET", None, 200)]:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(method, "/plan" if method == "POST" else "/health", body=body)
                response = connection.getresponse()
                assert response.status == status
                assert isinstance(json.loads(response.read()), dict)
            finally:
                connection.close()
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
