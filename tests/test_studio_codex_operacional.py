from studio_codex_operacional import status, version


def test_status():
    assert status() == "DEVAGENT OPERACIONAL"


def test_version():
    assert version() == "1.0"
