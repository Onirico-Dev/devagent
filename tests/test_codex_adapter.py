import pytest

from core.adapters.codex import (
    CodexProtocolError,
    CodexTransport,
)


def test_rejects_invalid_timeout():
    with pytest.raises(ValueError):
        CodexTransport(timeout=0)


def test_rejects_invalid_thread():
    transport = CodexTransport()

    with pytest.raises(ValueError):
        transport.start_turn("", "teste")


def test_rejects_empty_prompt():
    transport = CodexTransport()

    with pytest.raises(ValueError):
        transport.start_turn("thread-1", " ")


def test_rejects_unexpected_server_request():
    transport = CodexTransport()
    sent = []

    transport._send = sent.append

    transport._dispatch({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "item/commandExecution/requestApproval",
        "params": {},
    })

    assert sent[0]["id"] == 42
    assert sent[0]["error"]["code"] == -32601


def test_collects_notifications():
    transport = CodexTransport()

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "thread/started",
        "params": {"threadId": "abc"},
    })

    events = transport.get_events()

    assert len(events) == 1
    assert events[0]["method"] == "thread/started"
    assert transport.get_events() == []


def test_correlates_responses():
    transport = CodexTransport()

    transport._pending_requests.add(7)

    transport._dispatch({
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"ok": True},
    })

    assert transport._responses[7] == {"id": 7, "jsonrpc": "2.0", "result": {"ok": True}}


def test_rejects_invalid_message():
    transport = CodexTransport()

    with pytest.raises(CodexProtocolError):
        transport._dispatch({"jsonrpc": "2.0"})


def test_close_is_idempotent():
    transport = CodexTransport()
    transport.close()
    transport.close()
