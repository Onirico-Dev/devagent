from studio_codex_check import status


def test_status():
    assert status() == "STUDIO_CODEX_OK"
