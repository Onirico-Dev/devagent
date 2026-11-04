import time

import pytest

from core.adapters.codex import (
    CodexProtocolError,
    CodexTransport,
)


def test_turn_failed_raises_immediately():
    transport = CodexTransport(timeout=0.2)

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "turn/failed",
        "params": {
            "threadId": "thread-test",
            "turn": {
                "id": "turn-test",
                "status": "failed",
            },
            "error": {
                "message": "Falha simulada",
            },
        },
    })

    start = time.monotonic()

    with pytest.raises(CodexProtocolError):
        transport.wait_turn("thread-test", "turn-test")

    assert time.monotonic() - start < 0.15


def test_unexpected_responses_are_bounded():
    transport = CodexTransport()

    for request_id in range(2000):
        with pytest.raises(
            CodexProtocolError,
            match="identificador desconhecido",
        ):
            transport._dispatch({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {},
            })

    assert transport._responses == {}


def test_duplicate_response_is_rejected():
    transport = CodexTransport()
    transport._pending_requests.add(7)

    response = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"ok": True},
    }

    transport._dispatch(response)

    with pytest.raises(
        CodexProtocolError,
        match="duplicada",
    ):
        transport._dispatch(response)

    assert transport._responses[7] == response


def test_response_without_pending_request_is_rejected():
    transport = CodexTransport()

    with pytest.raises(
        CodexProtocolError,
        match="identificador desconhecido",
    ):
        transport._dispatch({
            "jsonrpc": "2.0",
            "id": 99,
            "result": {},
        })


def test_missing_response_result_is_rejected():
    transport = CodexTransport()

    transport._send = lambda message: None

    transport._read_message = lambda deadline: {
        "jsonrpc": "2.0",
        "id": 1,
    }

    with pytest.raises(CodexProtocolError):
        transport._request("test/method", {})


def test_server_request_is_never_approved():
    transport = CodexTransport()
    replies = []

    transport._send = replies.append

    transport._dispatch({
        "jsonrpc": "2.0",
        "id": 99,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "command": "touch arquivo_indesejado",
        },
    })

    assert len(replies) == 1
    assert "result" not in replies[0]
    assert replies[0]["error"]["code"] == -32601


def test_failed_turn_does_not_return_partial_content():
    transport = CodexTransport(timeout=0.2)

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "item/agentMessage/delta",
        "params": {
            "threadId": "thread-test",
            "turnId": "turn-test",
            "delta": '{"changes":[',
        },
    })

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "turn/failed",
        "params": {
            "threadId": "thread-test",
            "turn": {
                "id": "turn-test",
                "status": "failed",
            },
        },
    })

    with pytest.raises(CodexProtocolError):
        transport.wait_turn("thread-test", "turn-test")
