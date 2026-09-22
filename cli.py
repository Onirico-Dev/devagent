from pathlib import Path

from agent import DevAgent
from core.supervised_loop import SupervisedLoop
from core.gateway import DevAgentGateway
from core.observation_store import ObservationStore
from core.observer import Observation, Observer
from core.autonomy_policy import AutonomyPolicy
from core.worker import Worker
from core.worker_state_store import WorkerStateStore


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
            change_type = change.get("change_type")
            if change_type is None:
                change_type = change.get("type")

            print(
                f"  - {change_type}: "
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


def _read_command():
    command = input("\nDevAgent > ").rstrip()
    if not command:
        return ""

    lines = [command]

    while lines[-1].endswith(":"):
        try:
            continuation = input("... ").rstrip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not continuation:
            break

        lines.append(continuation)

    return "\n".join(lines).strip()


def print_proposals(proposals):
    if not proposals:
        print("\nNenhuma nova proposta.")
        return

    print("\nNovas propostas:")
    for proposal in proposals:
        print(
            f"  - [{proposal.approval_id}] "
            f"{proposal.status} — "
            f"{proposal.instruction}"
        )


def main(state_root: str | Path = "transactions", command_args=None):
    agent = DevAgent(".")
    gateway = DevAgentGateway(agent, ".")

    state_root = Path(state_root)

    observation_store = ObservationStore(
        state_root / "observations.json"
    )
    worker_state_store = WorkerStateStore(
        state_root / "worker.json"
    )
    supervised_loop_state_store = WorkerStateStore(
        state_root / "supervised_loop.json"
    )

    observer = Observer(store=observation_store)
    autonomy_policy = AutonomyPolicy()

    worker = Worker(
        gateway,
        observer,
        store=worker_state_store,
        autonomy_policy=autonomy_policy,
    )
    supervised_loop = SupervisedLoop(
        worker,
        gateway,
        state_store=supervised_loop_state_store,
        observer=observer,
    )

    print("=" * 60)
    print("DevAgent CLI")
    print("=" * 60)

    print("\nComandos:")
    print("  plan <instrução>")
    print("  observe <instrução>")
    print("  autonomy [iterações]")
    print("  tasks")
    print("  latest")
    print("  status <id>")
    print("  approve <id>")
    print("  reject <id>")
    print("  sair")

    non_interactive = command_args is not None
    pending_command = " ".join(command_args) if non_interactive else None

    while True:
        try:
            command = (
                pending_command
                if non_interactive
                else _read_command()
            )
            pending_command = None
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not command:
            if non_interactive:
                return
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

                result = gateway.create_task(parts[1])

                print("\nTarefa criada.")
                print_task(
                    gateway.get_task(result["approval_id"])
                )

            elif action == "observe":
                if len(parts) < 2:
                    print("Uso: observe <instrução>")
                    continue

                observer.add(
                    Observation(
                        instruction=parts[1],
                        metadata={"source": "cli"},
                    )
                )

                print("\nObservação adicionada.")

            elif action == "autonomy":

                if len(parts) == 1:

                    results = [supervised_loop.run_once()]

                else:

                    autonomy_args = parts[1].split()



                    if autonomy_args[0].lower() == "continuous":

                        interval_seconds = 1.0

                        max_iterations = None



                        if len(autonomy_args) >= 2:

                            try:

                                interval_seconds = float(autonomy_args[1])

                            except ValueError:

                                print(

                                    "Uso: autonomy continuous [intervalo] [iterações]"

                                )

                                continue



                        if len(autonomy_args) >= 3:

                            try:

                                max_iterations = int(autonomy_args[2])

                            except ValueError:

                                print(

                                    "Uso: autonomy continuous [intervalo] [iterações]"

                                )

                                continue



                        try:

                            results = supervised_loop.run_continuous(

                                interval_seconds=interval_seconds,

                                max_iterations=max_iterations,

                            )

                        except KeyboardInterrupt:

                            supervised_loop.stop()

                            print("\nLoop contínuo interrompido.")

                            results = []

                    else:

                        try:

                            max_iterations = int(parts[1])

                        except ValueError:

                            print("Uso: autonomy [iterações]")

                            continue



                        results = supervised_loop.run(

                            max_iterations=max_iterations

                        )


                for result in results:

                    print_proposals(result.proposals)

                    print(

                        f"Rodada: {result.metadata['iterations']} | "

                        f"Propostas: "

                        f"{result.metadata.get('proposal_count', 0)}"

                    )


            elif action == "tasks":
                print_tasks(gateway.list_tasks())

            elif action == "latest":
                print_task(gateway.latest_task())

            elif action == "status":
                if len(parts) < 2:
                    print("Uso: status <id>")
                    continue

                print_task(gateway.get_task(parts[1]))

            elif action == "approve":
                if len(parts) < 2:
                    print("Uso: approve <id>")
                    continue

                result = gateway.approve(parts[1])

                print("\nResultado da aprovação:")
                print_task(gateway.get_task(parts[1]))

                print(f"\nExecução: {result.get('status')}")

                if result.get("transaction_id"):
                    print(
                        f"Transação: "
                        f"{result['transaction_id']}"
                    )

                tests = result.get("tests")
                if tests:
                    print(f"Testes: {tests.get('success')}")

                print(
                    f"Reparos: "
                    f"{result.get('repair_attempts', 0)}"
                )

            elif action == "reject":
                if len(parts) < 2:
                    print("Uso: reject <id>")
                    continue

                result = gateway.reject(parts[1])

                print(
                    f"Tarefa {parts[1]}: "
                    f"{result.get('status')}"
                )

            else:
                print(
                    "Comando desconhecido. "
                    "Use: plan, observe, autonomy, tasks, "
                    "latest, status, approve, reject ou sair."
                )

        except Exception as error:
            print(
                f"\nErro: "
                f"{type(error).__name__}: {error}"
            )

        if non_interactive:
            return


if __name__ == "__main__":
    import sys

    main(command_args=sys.argv[1:])
