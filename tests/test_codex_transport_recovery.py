import sys
import textwrap

import pytest

from core.adapters.codex import (
    CodexProtocolError,
    CodexTransport,
)


def make_server(tmp_path, source):
    path = tmp_path / "fake_codex_recovery.py"
    path.write_text(
        textwrap.dedent(source),
        encoding="utf-8",
    )
    return [sys.executable, "-u", str(path)]


def test_timeout_closes_transport(tmp_path):
    command = make_server(
        tmp_path,
        """
        import json
        import sys
        import time

        for line in sys.stdin:
            message = json.loads(line)

            if message.get("method") == "initialize":
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {},
                }), flush=True)

            elif message.get("method") == "thread/start":
                time.sleep(10)
        """,
    )

    transport = CodexTransport(
        command=command,
        timeout=0.3,
    )

    try:
        transport.start()

        with pytest.raises(TimeoutError):
            transport.create_session()

        assert transport._process is None
        assert transport._selector is None
        assert transport._workspace is None

    finally:
        transport.close()


def test_disconnect_closes_transport(tmp_path):
    command = make_server(
        tmp_path,
        """
        import json
        import sys

        for line in sys.stdin:
            message = json.loads(line)

            if message.get("method") == "initialize":
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {},
                }), flush=True)

            elif message.get("method") == "thread/start":
                sys.exit(0)
        """,
    )

    transport = CodexTransport(
        command=command,
        timeout=2,
    )

    try:
        transport.start()

        with pytest.raises(CodexProtocolError):
            transport.create_session()

        assert transport._process is None
        assert transport._selector is None

    finally:
        transport.close()


def test_completion_event_is_not_silently_discarded():
    transport = CodexTransport(timeout=0.1)

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "threadId": "thread-test",
            "turn": {
                "id": "turn-test",
                "status": "completed",
                "items": [{
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": "391",
                }],
            },
        },
    })

    for index in range(1500):
        transport._dispatch({
            "jsonrpc": "2.0",
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-test",
                "turnId": "turn-test",
                "delta": str(index),
            },
        })

    assert transport.wait_turn(
        "thread-test",
        "turn-test",
    ) == "391"


def test_rejects_invalid_completion_status():
    transport = CodexTransport(timeout=0.1)

    transport._dispatch({
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "threadId": "thread-test",
            "turn": {
                "id": "turn-test",
                "status": "interrupted",
                "items": [],
            },
        },
    })

    with pytest.raises(CodexProtocolError):
        transport.wait_turn("thread-test", "turn-test")
