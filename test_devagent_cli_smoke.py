from devagent_cli_smoke import saudacao

def test_saudacao():
    assert saudacao() == 'Olá, mundo!'
