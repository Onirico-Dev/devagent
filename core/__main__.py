"""
Entrypoint oficial do DevAgent.

Mantém a execução centralizada no CLI existente, sem duplicar
a lógica do Gateway ou do pipeline.
"""

from cli import main


if __name__ == "__main__":
    main()
