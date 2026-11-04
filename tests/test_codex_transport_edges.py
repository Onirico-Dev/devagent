"""Failure contracts for framing, policy negotiation and process cleanup."""

import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.adapters.codex import CodexProtocolError, CodexTransport


@pytest.mark.parametrize("exited", [False, True])
def test_send_rejects_missing_or_exited_process(exited):
    transport = CodexTransport()
    process = Mock()
    process.poll.return_value = 0
    transport._process = process if exited else None
    with pytest.raises(CodexProtocolError, match="não está ativo"):
        transport._send({"method": "initialized"})
    process.stdin.write.assert_not_called()


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("error_type", [BrokenPipeError, OSError])
def test_send_wraps_pipe_errors(operation, error_type):
    transport = CodexTransport()
    process = Mock()
    process.poll.return_value = None
    error = error_type("pipe unavailable")
    getattr(process.stdin, operation).side_effect = error
    transport._process = process
    with pytest.raises(CodexProtocolError, match="Falha ao enviar") as exc:
        transport._send({"id": 1, "method": "initialize"})
    assert exc.value.__cause__ is error


def test_blank_lines_do_not_hide_next_message():
    transport = CodexTransport()
    transport._buffer.extend(b'\n \t\n{"id":7,"result":{}}\n')
    assert transport._read_message(time.monotonic() + 1) == {"id": 7, "result": {}}
    assert transport._buffer == b""


@pytest.mark.parametrize("raw", [b"not-json\n", b"\xff\n"])
def test_invalid_wire_encoding_is_a_protocol_error(raw):
    transport = CodexTransport()
    transport._buffer.extend(raw)
    with pytest.raises(CodexProtocolError, match="JSON-RPC inválida") as exc:
        transport._read_message(time.monotonic() + 1)
    assert isinstance(exc.value.__cause__, (ValueError, UnicodeDecodeError))


@pytest.mark.parametrize("value", [[], None, 1, "text"])
def test_wire_message_must_be_an_object(value):
    transport = CodexTransport()
    transport._buffer.extend((json.dumps(value) + "\n").encode())
    with pytest.raises(CodexProtocolError, match="não é um objeto"):
        transport._read_message(time.monotonic() + 1)


def test_process_exit_without_readable_data_is_reported():
    transport = CodexTransport()
    transport._selector = Mock()
    transport._selector.select.return_value = []
    transport._process = Mock()
    transport._process.poll.return_value = 23
    with pytest.raises(CodexProtocolError, match="encerrou inesperadamente"):
        transport._read_message(time.monotonic() + 1)


def test_unterminated_frame_over_limit_is_rejected(monkeypatch):
    import core.adapters.codex as module
    transport = CodexTransport()
    transport._selector = Mock()
    transport._selector.select.return_value = [(object(), 1)]
    transport._process = Mock()
    # Simulate a frame spanning many prior reads, then one final byte.
    transport._buffer.extend(b"x" * (4 * 1024 * 1024))
    monkeypatch.setattr(module.os, "read", lambda fd, size: b"x")
    with pytest.raises(CodexProtocolError, match="limite de 4 MiB"):
        transport._read_message(time.monotonic() + 1)


def completion(thread="thread", turn="turn", items=None):
    return {
        "method": "turn/completed",
        "params": {
            "threadId": thread,
            "turn": {"id": turn, "status": "completed", "items": items or []},
        },
    }


@pytest.mark.parametrize("params", [None, [], "invalid", {"turn": []}])
def test_malformed_terminal_event_is_rejected_without_state_change(params):
    transport = CodexTransport()
    with pytest.raises(CodexProtocolError, match="Evento terminal"):
        transport._dispatch({"method": "turn/completed", "params": params})
    assert transport._terminal_events == {}


@pytest.mark.parametrize("thread,turn", [(None, "t"), ("", "t"), ("h", None), ("h", "")])
def test_terminal_event_requires_valid_identifiers(thread, turn):
    transport = CodexTransport()
    with pytest.raises(CodexProtocolError, match="Identificadores"):
        transport._dispatch(completion(thread, turn))
    assert transport._terminal_events == {}


def test_duplicate_terminal_event_keeps_original():
    transport = CodexTransport()
    original = completion()
    transport._dispatch(original)
    with pytest.raises(CodexProtocolError, match="terminal duplicado"):
        transport._dispatch(completion())
    assert transport._terminal_events == {("thread", "turn"): original}


def test_terminal_event_limit_preserves_existing_events():
    transport = CodexTransport()
    for index in range(1000):
        transport._dispatch(completion(turn=str(index)))
    with pytest.raises(CodexProtocolError, match="Limite de eventos"):
        transport._dispatch(completion(turn="overflow"))
    assert len(transport._terminal_events) == 1000
    assert ("thread", "overflow") not in transport._terminal_events


def test_rpc_error_does_not_become_a_successful_result():
    transport = CodexTransport()
    transport._send = Mock()
    transport._read_message = lambda deadline: {
        "id": 1, "error": {"code": -32000, "message": "unavailable"},
    }
    with pytest.raises(CodexProtocolError, match="Erro JSON-RPC em thread/start"):
        transport._request("thread/start", {})
    assert transport._pending_requests == set()
    assert transport._responses == {}


def test_missing_executable_cleans_temporary_workspace(tmp_path):
    transport = CodexTransport(command=[str(tmp_path / "absent-codex")])
    with pytest.raises(FileNotFoundError):
        transport.start()
    assert transport._workspace is None
    assert transport._selector is None
    assert transport._process is None


def test_failed_handshake_reaps_process_and_closes_streams(monkeypatch):
    transport = CodexTransport(command=[sys.executable, "-c", "import sys; sys.stdin.read()"])
    processes = []
    def fail_handshake(*args, **kwargs):
        processes.append(transport._process)
        raise CodexProtocolError("initialize rejected")
    monkeypatch.setattr(transport, "_request", fail_handshake)
    with pytest.raises(CodexProtocolError, match="initialize rejected"):
        transport.start()
    process, = processes
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed
    assert transport._workspace is None
    assert transport._selector is None
    assert transport._process is None


def test_start_replaces_exited_process_and_discards_stale_state():
    transport = CodexTransport(command=[sys.executable, "-u", "-c", (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        " m = json.loads(line)\n"
        " if m.get('method') == 'initialize':\n"
        "  print(json.dumps({'id': m['id'], 'result': {}}), flush=True)\n"
    )], timeout=5)
    try:
        transport.start()
        old = transport._process
        old.terminate()
        old.wait(timeout=5)
        transport._buffer.extend(b"stale")
        transport.start()
        assert transport._process is not old
        assert transport._process.poll() is None
        assert old.stdin.closed and old.stdout.closed
        assert transport._buffer == b""
    finally:
        transport.close()


@pytest.mark.parametrize("sandbox,approval,message", [
    ("workspaceWrite", "never", "readOnly"),
    ("readOnly", "on-request", "aprovação inesperada"),
])
def test_session_policy_mismatch_is_rejected(monkeypatch, sandbox, approval, message):
    transport = CodexTransport()
    transport._workspace = tempfile.TemporaryDirectory()
    monkeypatch.setattr(transport, "start", lambda: None)
    monkeypatch.setattr(transport, "_request", lambda method, params: {
        "sandbox": {"type": sandbox}, "approvalPolicy": approval,
        "thread": {"id": "thread"},
    })
    try:
        with pytest.raises(CodexProtocolError, match=message):
            transport.create_session()
    finally:
        transport.close()


@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_final_answer_never_returns_text(count):
    transport = CodexTransport()
    items = [{"type": "agentMessage", "phase": "final_answer", "text": "ok"}] * count
    transport._dispatch(completion(items=items))
    with pytest.raises(CodexProtocolError, match="ausente ou ambígua"):
        transport.wait_turn("thread", "turn")
    assert transport._terminal_events == {}


def test_close_kills_unresponsive_process_and_releases_resources():
    transport = CodexTransport()
    process = Mock()
    process.poll.return_value = None
    process.stdin = io.BytesIO()
    process.stdout = io.BytesIO()
    process.wait.side_effect = [subprocess.TimeoutExpired("codex", 5), 0]
    selector = Mock()
    transport._process = process
    transport._selector = selector
    transport._workspace = tempfile.TemporaryDirectory()
    workspace_path = Path(transport._workspace.name)
    transport._pending_requests.add(1)
    transport._responses[1] = {"result": {}}
    transport._dispatch(completion())
    transport.close()
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_args_list[0].kwargs == {"timeout": 5}
    assert process.wait.call_count == 2
    assert process.stdin.closed and process.stdout.closed
    selector.close.assert_called_once_with()
    assert not workspace_path.exists()
    assert transport._process is None
    assert transport._selector is None
    assert transport._workspace is None
    assert transport._pending_requests == set()
    assert transport._responses == {}
    assert transport._terminal_events == {}
