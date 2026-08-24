from agent import DevAgent
from core.gateway import DevAgentGateway


def print_task(task):
    if task is None:
        print("Nenhuma tarefa encontrada.")
        return

    print(f"\nID: {task.get('approval_id')}")
    print(f"Status: {task.get('status')}")
    print(f"Instrução: {task.get('instruction')}")

    transaction_id = task.get("transaction_id")

    if transaction_id:
        print(f"Transação: {transaction_id}")

    plan = task.get("plan") or {}
    changes = plan.get("changes", [])

    if changes:
        print("Alterações:")

        for change in changes:
            print(
                f"  - {change.get('type')}: "
                f"{change.get('path')}"
            )

    extra = {
        key: value
        for key, value in task.items()
        if key not in {
            "task_id",
            "approval_id",
            "instruction",
            "plan",
            "status",
            "transaction_id",
            "created_at",
            "updated_at",
        }
    }

    if extra:
        print("Detalhes:")

        for key, value in extra.items():
            print(f"  {key}: {value}")


def print_tasks(tasks):
    if not tasks:
        print("Nenhuma tarefa encontrada.")
        return

    for task in tasks:
        print(
            f"[{task.get('approval_id')}] "
            f"{task.get('status')} — "
            f"{task.get('instruction')}"
        )


def main():
    agent = DevAgent(".")
    gateway = DevAgentGateway(agent, ".")

    print("=" * 60)
    print("DevAgent CLI")
    print("=" * 60)

    print("\nComandos:")
    print("  plan <instrução>")
    print("  tasks")
    print("  latest")
    print("  status <id>")
    print("  approve <id>")
    print("  reject <id>")
    print("  sair")

    while True:
        try:
            command = input("\nDevAgent > ").strip()

        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not command:
            continue

        parts = command.split(maxsplit=1)
        action = parts[0].lower()

        if action in {"sair", "exit", "quit"}:
            break

        try:

            if action == "plan":

                if len(parts) < 2:
                    print("Uso: plan <instrução>")
                    continue

                result = gateway.create_task(
                    parts[1]
                )

                print("\nTarefa criada.")
                print_task(
                    gateway.get_task(
                        result["approval_id"]
                    )
                )

            elif action == "tasks":

                print_tasks(
                    gateway.list_tasks()
                )

            elif action == "latest":

                print_task(
                    gateway.latest_task()
                )

            elif action == "status":

                if len(parts) < 2:
                    print("Uso: status <id>")
                    continue

                print_task(
                    gateway.get_task(
                        parts[1]
                    )
                )

            elif action == "approve":

                if len(parts) < 2:
                    print("Uso: approve <id>")
                    continue

                result = gateway.approve(
                    parts[1]
                )

                print("\nResultado da aprovação:")
                print_task(
                    gateway.get_task(
                        parts[1]
                    )
                )

                print(
                    f"\nExecução: "
                    f"{result.get('status')}"
                )

                if result.get("transaction_id"):
                    print(
                        f"Transação: "
                        f"{result['transaction_id']}"
                    )

                tests = result.get("tests")

                if tests:
                    print(
                        f"Testes: "
                        f"{tests.get('success')}"
                    )

                print(
                    f"Reparos: "
                    f"{result.get('repair_attempts', 0)}"
                )

            elif action == "reject":

                if len(parts) < 2:
                    print("Uso: reject <id>")
                    continue

                result = gateway.reject(
                    parts[1]
                )

                print(
                    f"Tarefa {parts[1]}: "
                    f"{result.get('status')}"
                )

            else:

                print(
                    "Comando desconhecido. "
                    "Use: plan, tasks, latest, "
                    "status, approve, reject ou sair."
                )

        except Exception as error:
            print(
                f"\nErro: "
                f"{type(error).__name__}: {error}"
            )


if __name__ == "__main__":
    main()
