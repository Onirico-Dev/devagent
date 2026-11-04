from studio_codex_check import status, version


def test_status():
    assert status() == "STUDIO_CODEX_OK"


def test_version():
    assert version() == "1.0"
