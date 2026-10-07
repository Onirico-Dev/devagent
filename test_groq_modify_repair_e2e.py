import pytest
from groq_modify_repair_e2e import hello, goodbye, multiplicar

def test_hello():
    assert hello() == "HELLO DEVAGENT"

def test_goodbye():
    assert goodbye() == "GOODBYE DEVAGENT"

def test_multiplicar():
    assert multiplicar(2, 3) == 6