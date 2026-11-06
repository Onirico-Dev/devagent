from studio_codex_operacional import status


def test_status():
    assert status() == "DEVAGENT OPERACIONAL"
