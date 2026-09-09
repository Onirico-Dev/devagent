import builtins

import cli


class FakeGateway:
    def __init__(self, agent, root):
        self.calls = []

    def create_task(self, instruction):
        self.calls.append(("create_task", instruction))
        return {"approval_id": "a1"}

    def get_task(self, task_id):
        self.calls.append(("get_task", task_id))
        return {
            "approval_id": task_id,
            "status": "pending",
            "instruction": "teste",
            "transaction_id": "tx1",
            "plan": {
                "changes": [
                    {"type": "CREATE", "path": "app.py"},
                ]
            },
            "created_at": "now",
            "updated_at": "now",
            "extra": "valor",
        }

    def list_tasks(self):
        return [
            {
                "approval_id": "a1",
                "status": "pending",
                "instruction": "teste",
            }
        ]

    def latest_task(self):
        return self.get_task("a1")

    def approve(self, approval_id):
        self.calls.append(("approve", approval_id))
        return {
            "status": "committed",
            "transaction_id": "tx1",
            "tests": {"success": True},
            "repair_attempts": 0,
        }

    def reject(self, approval_id):
        self.calls.append(("reject", approval_id))
        return {"status": "rejected"}


def test_print_task_none(capsys):
    cli.print_task(None)
    assert "Nenhuma tarefa encontrada." in capsys.readouterr().out


def test_print_task_full(capsys):
    task = {
        "approval_id": "a1",
        "status": "pending",
        "instruction": "teste",
        "transaction_id": "tx1",
        "plan": {
            "changes": [
                {"type": "CREATE", "path": "app.py"},
                {"type": "MODIFY", "path": "config.py"},
            ]
        },
        "created_at": "now",
        "updated_at": "now",
        "extra": "valor",
    }

    cli.print_task(task)
    output = capsys.readouterr().out

    assert "ID: a1" in output
    assert "Status: pending" in output
    assert "Instrução: teste" in output
    assert "Transação: tx1" in output
    assert "Alterações:" in output
    assert "CREATE: app.py" in output
    assert "MODIFY: config.py" in output
    assert "Detalhes:" in output
    assert "extra: valor" in output


def test_print_task_without_optional_sections(capsys):
    cli.print_task({
        "approval_id": "a1",
        "status": "pending",
        "instruction": "teste",
    })

    output = capsys.readouterr().out

    assert "ID: a1" in output
    assert "Transação:" not in output
    assert "Alterações:" not in output
    assert "Detalhes:" not in output


def test_print_tasks_empty(capsys):
    cli.print_tasks([])
    assert "Nenhuma tarefa encontrada." in capsys.readouterr().out


def test_print_tasks(capsys):
    cli.print_tasks([
        {
            "approval_id": "a1",
            "status": "pending",
            "instruction": "primeira",
        },
        {
            "approval_id": "a2",
            "status": "rejected",
            "instruction": "segunda",
        },
    ])

    output = capsys.readouterr().out

    assert "[a1] pending — primeira" in output
    assert "[a2] rejected — segunda" in output


def test_main_plan_tasks_latest_status_approve_reject(monkeypatch, capsys):
    gateway = FakeGateway(None, ".")
    monkeypatch.setattr(cli, "DevAgent", lambda root: object())
    monkeypatch.setattr(cli, "DevAgentGateway", lambda agent, root: gateway)

    commands = iter([
        "plan criar arquivo",
        "tasks",
        "latest",
        "status a1",
        "approve a1",
        "reject a1",
        "sair",
    ])

    monkeypatch.setattr(builtins, "input", lambda _: next(commands))

    cli.main()

    output = capsys.readouterr().out

    assert "DevAgent CLI" in output
    assert "Tarefa criada." in output
    assert "Resultado da aprovação:" in output
    assert "Execução: committed" in output
    assert "Transação: tx1" in output
    assert "Testes: True" in output
    assert "Reparos: 0" in output
    assert "Tarefa a1: rejected" in output

    assert ("create_task", "criar arquivo") in gateway.calls
    assert ("approve", "a1") in gateway.calls
    assert ("reject", "a1") in gateway.calls


def test_main_missing_arguments_and_unknown_command(monkeypatch, capsys):
    gateway = FakeGateway(None, ".")
    monkeypatch.setattr(cli, "DevAgent", lambda root: object())
    monkeypatch.setattr(cli, "DevAgentGateway", lambda agent, root: gateway)

    commands = iter([
        "plan",
        "status",
        "approve",
        "reject",
        "comando-inexistente",
        "sair",
    ])

    monkeypatch.setattr(builtins, "input", lambda _: next(commands))

    cli.main()

    output = capsys.readouterr().out

    assert "Uso: plan <instrução>" in output
    assert "Uso: status <id>" in output
    assert "Uso: approve <id>" in output
    assert "Uso: reject <id>" in output
    assert "Comando desconhecido." in output


def test_main_empty_input_and_exit_aliases(monkeypatch, capsys):
    gateway = FakeGateway(None, ".")
    monkeypatch.setattr(cli, "DevAgent", lambda root: object())
    monkeypatch.setattr(cli, "DevAgentGateway", lambda agent, root: gateway)

    commands = iter(["", "  ", "exit"])

    monkeypatch.setattr(builtins, "input", lambda _: next(commands))

    cli.main()

    output = capsys.readouterr().out
    assert "DevAgent CLI" in output


def test_main_keyboard_interrupt(monkeypatch, capsys):
    gateway = FakeGateway(None, ".")
    monkeypatch.setattr(cli, "DevAgent", lambda root: object())
    monkeypatch.setattr(cli, "DevAgentGateway", lambda agent, root: gateway)

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)

    cli.main()

    assert "DevAgent CLI" in capsys.readouterr().out


def test_main_gateway_error(monkeypatch, capsys):
    gateway = FakeGateway(None, ".")
    monkeypatch.setattr(cli, "DevAgent", lambda root: object())
    monkeypatch.setattr(cli, "DevAgentGateway", lambda agent, root: gateway)

    def fail():
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(gateway, "list_tasks", fail)

    commands = iter(["tasks", "sair"])
    monkeypatch.setattr(builtins, "input", lambda _: next(commands))

    cli.main()

    output = capsys.readouterr().out
    assert "Erro: RuntimeError: falha de teste" in output


def test_cli_module_entrypoint(monkeypatch):
    monkeypatch.setattr(
        builtins,
        "input",
        lambda _: "sair",
    )

    import runpy

    runpy.run_module("cli", run_name="__main__")
