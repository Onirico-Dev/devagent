import pytest
from groq_modify_repair_e2e import hello, goodbye

def test_hello():
    assert hello() == "HELLO DEVAGENT"

def test_goodbye():
    assert goodbye() == "GOODBYE DEVAGENT"