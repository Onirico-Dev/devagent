"""
Entrypoint oficial do DevAgent.

Mantém a execução centralizada no CLI existente, sem duplicar a lógica
do Gateway ou do pipeline.
"""

import sys
from importlib.metadata import PackageNotFoundError, version

from cli import main


HELP_TEXT = """DevAgent

Uso:
  devagent
  devagent --help
  devagent --version

A CLI interativa oferece:
  plan <instrução>   Criar uma tarefa
  tasks              Listar tarefas
  latest             Mostrar a tarefa mais recente
  status <id>        Mostrar uma tarefa
  approve <id>       Aprovar uma tarefa
  reject <id>        Rejeitar uma tarefa
  sair               Encerrar a CLI
"""


def _version():
    try:
        return version("devagent")
    except PackageNotFoundError:
        return "0.4.6"


def main():
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(HELP_TEXT)
        return

    if "--version" in sys.argv[1:] or "-V" in sys.argv[1:]:
        print(_version())
        return

    cli_args = sys.argv[1:]
    if cli_args:
        print(f"Argumento não reconhecido: {cli_args[0]}")
        print("Use 'devagent --help' para ver os comandos disponíveis.")
        return

    from cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
