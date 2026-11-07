from studio_execution_probe_e2246ae import status, version

def test_status():
    assert status() == "DEVAGENT_OK"


def test_version():
    assert version() == "1.0"
