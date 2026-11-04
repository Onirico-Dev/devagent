import sys
import textwrap

from core.adapters.codex import CodexTransport


FAKE_SERVER = r'''
import json
import sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "userAgent": "fake-codex",
            },
        })

    elif method == "initialized":
        continue

    elif method == "thread/start":
        send({
            "jsonrpc": "2.0",
            "method": "thread/started",
            "params": {
                "threadId": "thread-test",
            },
        })

        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "thread": {
                    "id": "thread-test",
                },
                "sandbox": {
                    "type": "readOnly",
                    "networkAccess": False,
                },
                "approvalPolicy": "never",
            },
        })

    elif method == "turn/start":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "turn": {
                    "id": "turn-test",
                },
            },
        })

        send({
            "jsonrpc": "2.0",
            "method": "turn/completed",
            "params": {
                "threadId": "thread-test",
                "turn": {
                    "id": "turn-test",
                    "status": "completed",
                    "items": [
                        {
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": "391",
                        },
                    ],
                },
            },
        })
'''


def test_complete_codex_transport_flow(tmp_path):
    server = tmp_path / "fake_codex.py"
    server.write_text(
        textwrap.dedent(FAKE_SERVER),
        encoding="utf-8",
    )

    transport = CodexTransport(
        command=[sys.executable, "-u", str(server)],
        timeout=5,
    )

    try:
        transport.start()

        thread_id = transport.create_session()
        assert thread_id == "thread-test"

        turn_id = transport.start_turn(
            thread_id,
            "Quanto é 17 * 23?",
        )
        assert turn_id == "turn-test"

        response = transport.wait_turn(thread_id, turn_id)
        assert response == "391"

        events = transport.get_events()
        assert any(
            event.get("method") == "thread/started"
            for event in events
        )

    finally:
        transport.close()


def test_transport_context_manager(tmp_path):
    server = tmp_path / "fake_codex.py"
    server.write_text(
        textwrap.dedent(FAKE_SERVER),
        encoding="utf-8",
    )

    with CodexTransport(
        command=[sys.executable, "-u", str(server)],
        timeout=5,
    ) as transport:
        assert transport.create_session() == "thread-test"

    assert transport._process is None
