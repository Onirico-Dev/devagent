import pytest
from groq_modify_repair_e2e import hello

def test_hello():
    assert hello() == "HELLO DEVAGENT"
