import pytest
from smoke_ai_repair import dividir

def test_dividir():
    assert dividir(6, 2) == 3
    assert dividir(6, 0) == 0
