from studio_execution_probe_e2246ae import status

def test_status():
    assert status() == "DEVAGENT_OK"
