import os
import subprocess
import sys
from pathlib import Path

from core.autonomy_policy import AutonomyPolicy
from core.gateway import DevAgentGateway
from core.observation import Observation
from core.observation_store import ObservationStore
from core.observer import Observer
from core.supervised_loop import SupervisedLoop
from core.worker import Worker
from core.worker_state_store import WorkerStateStore


class CreateAgent:
    def process(self, instruction, feedback_context=None):
        return {
            "instruction": instruction,
            "objective": instruction,
            "changes": [
                {
                    "path": "autonomous_smoke.py",
                    "change_type": "create",
                    "content": "VALUE = 42\n",
                    "reason": "Criar arquivo solicitado.",
                }
            ],
            "tests": [],
            "risks": [],
        }

    def build_transaction_from_approved_plan(self, plan):
        from core.schemas.models import Change, ChangeType, Transaction

        changes = [
            Change(
                change_type=ChangeType(change["change_type"]),
                path=change["path"],
                content=change.get("content"),
                reason=change.get("reason", ""),
            )
            for change in plan["changes"]
        ]

        return Transaction(
            transaction_id="",
            changes=changes,
            metadata={
                "instruction": plan["instruction"],
                "objective": plan.get("objective"),
                "tests": plan.get("tests", []),
                "risks": plan.get("risks", []),
            },
        )


def init_git(root):
    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    (root / ".gitignore").write_text(
        "transactions/\n"
        "observations.json\n"
        "worker.json\n"
        "supervised_loop.json\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_real_autonomy_cycle_observe_autoapprove_execute_commit(tmp_path):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    observer = Observer(store=observation_store)

    worker = Worker(
        gateway,
        observer,
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    result = loop.run_once()

    target = tmp_path / "autonomous_smoke.py"

    assert len(result.proposals) == 1
    assert (
        result.proposals[0].autonomy_decision
        == "auto_approve"
    )
    assert result.metadata["auto_approved_count"] == 1
    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    task = gateway.get_task(
        result.proposals[0].approval_id
    )

    assert task["status"] == "committed"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


def test_real_autonomy_restart_does_not_reprocess_observation(tmp_path):
    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    observation_store = ObservationStore(observation_path)
    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "restart"},
            )
        ]
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )
    observer = Observer(store=observation_store)
    worker = Worker(
        gateway,
        observer,
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )
    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(loop_path),
    )

    first = loop.run_once()

    assert len(first.proposals) == 1
    assert first.metadata["auto_approved_count"] == 1
    assert len(gateway.list_tasks()) == 1

    restarted_gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )
    restarted_observer = Observer(
        store=ObservationStore(observation_path)
    )
    restarted_worker = Worker(
        restarted_gateway,
        restarted_observer,
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )
    restarted_loop = SupervisedLoop(
        restarted_worker,
        restarted_gateway,
        state_store=WorkerStateStore(loop_path),
    )

    second = restarted_loop.run_once()

    assert second.proposals == []
    assert second.metadata["auto_approved_count"] == 0
    assert len(restarted_gateway.list_tasks()) == 1

    task = restarted_gateway.get_task(
        first.proposals[0].approval_id
    )

    assert task["status"] == "committed"
    assert (
        (tmp_path / "autonomous_smoke.py").read_text(
            encoding="utf-8"
        )
        == "VALUE = 42\n"
    )


class FailingCreateAgent(CreateAgent):
    def build_transaction_from_approved_plan(self, plan):
        transaction = super().build_transaction_from_approved_plan(
            plan
        )
        transaction.changes[0].content = "def broken(:\n"
        return transaction


def test_real_autonomy_cycle_failure_rolls_back(tmp_path):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        FailingCreateAgent(),
        root=tmp_path,
    )

    observer = Observer(store=observation_store)

    worker = Worker(
        gateway,
        observer,
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    result = loop.run_once()

    target = tmp_path / "autonomous_smoke.py"

    assert len(result.proposals) == 1
    assert (
        result.proposals[0].autonomy_decision
        == "auto_approve"
    )
    assert result.metadata["auto_approved_count"] == 1
    assert not target.exists()

    task = gateway.get_task(
        result.proposals[0].approval_id
    )

    assert task["status"] == "rolled_back"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


def test_real_autonomy_cycle_recovers_after_crash(
    tmp_path,
    monkeypatch,
):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    observer = Observer(store=observation_store)

    worker = Worker(
        gateway,
        observer,
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    def crash_during_execution(transaction, on_change_applied=None):
        raise SystemExit(
            "CRASH_DURING_AUTONOMOUS_EXECUTION"
        )

    monkeypatch.setattr(
        gateway.executor,
        "execute",
        crash_during_execution,
    )

    try:
        loop.run_once()
    except SystemExit as error:
        assert str(error) == (
            "CRASH_DURING_AUTONOMOUS_EXECUTION"
        )
    else:
        raise AssertionError(
            "O ciclo autônomo deveria ter sido interrompido."
        )

    tasks = gateway.list_tasks()

    assert len(tasks) == 1

    approval_id = tasks[0]["approval_id"]

    task = gateway.get_task(approval_id)

    assert task["status"] == "executing"
    assert task["transaction_id"] is not None

    approval = gateway.supervisor.get(approval_id)

    assert approval["status"] == "approved"

    recoverable = (
        gateway.transactions.list_recoverable_transactions()
    )

    assert len(recoverable) == 1

    restarted = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    assert (
        restarted.transactions.list_recoverable_transactions()
        == []
    )

    recovered_task = restarted.get_task(approval_id)

    assert recovered_task["status"] == "rolled_back"

    target = tmp_path / "autonomous_smoke.py"

    assert not target.exists()

def test_real_autonomy_continuous_detects_observation_arriving_between_rounds(tmp_path):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    observer = Observer(store=observation_store)

    worker = Worker(
        gateway,
        observer,
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    results = []

    def sleep_and_inject(_interval):
        observation_store.save(
            [
                Observation(
                    "criar arquivo autonomamente",
                    {"source": "continuous"},
                )
            ]
        )

    results = loop.run_continuous(
        interval_seconds=1,
        max_iterations=2,
        sleep_fn=sleep_and_inject,
    )

    target = tmp_path / "autonomous_smoke.py"

    assert len(results) == 2

    assert results[0].metadata["proposal_count"] == 0

    assert results[1].metadata["proposal_count"] == 1
    assert results[1].metadata["auto_approved_count"] == 1

    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    proposal = results[1].proposals[0]

    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "committed"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""

def test_real_autonomy_restart_continues_loop_state_and_processes_new_observation(
    tmp_path,
):
    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    observation_store = ObservationStore(observation_path)
    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "before-restart"},
            )
        ]
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(loop_path),
    )

    first = loop.run_once()

    assert first.metadata["iterations"] == 1
    assert first.metadata["proposal_count"] == 1
    assert first.metadata["auto_approved_count"] == 1

    class RestartCreateAgent(CreateAgent):
        def process(self, instruction):
            result = super().process(instruction)
            result["changes"][0]["path"] = "autonomous_restart_smoke.py"
            result["changes"][0]["content"] = "VALUE = 43\n"
            return result

    restarted_observation_store = ObservationStore(observation_path)
    restarted_observation_store.save(
        [
            Observation(
                "criar segundo arquivo depois do restart",
                {"source": "after-restart"},
            )
        ]
    )

    restarted_gateway = DevAgentGateway(
        RestartCreateAgent(),
        root=tmp_path,
    )

    restarted_worker = Worker(
        restarted_gateway,
        Observer(store=restarted_observation_store),
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )

    restarted_loop = SupervisedLoop(
        restarted_worker,
        restarted_gateway,
        state_store=WorkerStateStore(loop_path),
    )

    assert restarted_loop.iterations == 1
    assert restarted_loop.stopped is False

    second = restarted_loop.run_once()

    assert second.metadata["iterations"] == 2
    assert second.metadata["proposal_count"] == 1
    assert second.metadata["auto_approved_count"] == 1

    tasks = restarted_gateway.list_tasks()

    assert len(tasks) == 2
    assert all(task["status"] == "committed" for task in tasks)

    assert (tmp_path / "autonomous_smoke.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 42\n"

    assert (tmp_path / "autonomous_restart_smoke.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 43\n"

    assert WorkerStateStore(loop_path).load() == {
        "stopped": False,
        "iterations": 2,
    }

def test_real_autonomy_cross_process_restart_continues_from_persisted_state(
    tmp_path,
):
    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    ObservationStore(observation_path).save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "process-a"},
            )
        ]
    )

    script = tmp_path / "run_agent.py"
    script.write_text(
        """
from pathlib import Path
import sys

from core.autonomy_policy import AutonomyPolicy
from core.gateway import DevAgentGateway
from core.observation_store import ObservationStore
from core.observer import Observation, Observer
from core.supervised_loop import SupervisedLoop
from core.worker import Worker
from core.worker_state_store import WorkerStateStore


class CreateAgent:
    def process(self, instruction):
        return {
                        "instruction": instruction,
"objective": instruction,
            "changes": [
                {
                    "change_type": "create",
                    "path": (
                        "cross_process_smoke_2.py"
                        if instruction == "criar segundo arquivo autonomamente"
                        else "cross_process_smoke.py"
                    ),
                    "content": "VALUE = 42\\n",
                }
            ],
            "tests": [],
            "risks": [],
        }

    def build_transaction_from_approved_plan(self, plan):
        from uuid import uuid4
        from core.schemas.models import Change, ChangeType
        from core.schemas.models import Transaction

        changes = [
            Change(
                change_type=ChangeType(item["change_type"]),
                path=item["path"],
                content=item.get("content"),
                reason=item.get("reason", ""),
            )
            for item in plan["changes"]
        ]
        return Transaction(
            transaction_id=str(uuid4()),
            changes=changes,
            metadata={"tests": plan.get("tests", [])},
        )


root = Path(sys.argv[1])
observation_path = root / "observations.json"
worker_path = root / "worker.json"
loop_path = root / "supervised_loop.json"

gateway = DevAgentGateway(CreateAgent(), root=root)
worker = Worker(
    gateway,
    Observer(store=ObservationStore(observation_path)),
    store=WorkerStateStore(worker_path),
    autonomy_policy=AutonomyPolicy(),
)
loop = SupervisedLoop(
    worker,
    gateway,
    state_store=WorkerStateStore(loop_path),
)

result = loop.run_once()

print(
    result.metadata["iterations"],
    result.metadata["proposal_count"],
    result.metadata["auto_approved_count"],
)
""",
        encoding="utf-8",
    )

    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())

    first = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert first.returncode == 0
    assert first.stdout.strip() == "1 1 1"
    assert (tmp_path / "cross_process_smoke.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 42\n"

    ObservationStore(observation_path).save(
        [
            Observation(
                "criar segundo arquivo autonomamente",
                {"source": "process-b"},
            )
        ]
    )

    second = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    assert second.stdout.strip() == "2 1 1"

    tasks = DevAgentGateway(CreateAgent(), root=tmp_path).list_tasks()

    assert len(tasks) == 2
    assert all(task["status"] == "committed" for task in tasks)

    assert WorkerStateStore(loop_path).load() == {
        "stopped": False,
        "iterations": 2,
    }


class RepairAgent(CreateAgent):
    def process(self, instruction):
        result = super().process(instruction)
        result["changes"][0]["content"] = "def broken(:\n"
        return result


class RepairAdapter:
    prompts = []

    def generate(self, prompt):
        import json

        self.prompts.append(prompt)

        return json.dumps(
            {
                "diagnosis": "Erro de sintaxe no arquivo.",
                "correction": "Corrigir a definição da função.",
                "risk": "baixo",
                "action": "modify",
                "path": "autonomous_smoke.py",
                "content": "VALUE = 42\n",
            }
        )


def test_real_autonomy_cycle_repairs_failed_test_and_commits(tmp_path):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "repair-integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        RepairAgent(),
        root=tmp_path,
    )

    repair_adapter = RepairAdapter()
    gateway.repair_engine.ai = repair_adapter

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0].autonomy_decision == "auto_approve"
    assert result.metadata["auto_approved_count"] == 1

    assert len(repair_adapter.prompts) == 1
    assert "Tipo de falha classificado:" in repair_adapter.prompts[0]
    assert "syntax_error" in repair_adapter.prompts[0]

    target = tmp_path / "autonomous_smoke.py"
    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    proposal = result.proposals[0]
    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "committed"

    transaction = gateway.transactions.load_manifest(
        task["transaction_id"]
    )

    assert transaction.status.value == "committed"
    assert transaction.metadata["repair_cycle"]["attempts"] == 1

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


class PersistentlyBrokenRepairAdapter:
    def generate(self, prompt):
        import json

        return json.dumps(
            {
                "diagnosis": "Erro de sintaxe persistente.",
                "correction": "Tentativa de correção ainda inválida.",
                "risk": "baixo",
                "action": "modify",
                "path": "autonomous_smoke.py",
                "content": "def still_broken(:\n",
            }
        )


def test_real_autonomy_cycle_exhausts_repair_attempts_and_rolls_back(
    tmp_path,
):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "repair-limit-integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        RepairAgent(),
        root=tmp_path,
    )

    gateway.repair_engine.ai = PersistentlyBrokenRepairAdapter()

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0].autonomy_decision == "auto_approve"
    assert result.metadata["auto_approved_count"] == 1

    target = tmp_path / "autonomous_smoke.py"

    assert not target.exists()

    proposal = result.proposals[0]
    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "rolled_back"

    transaction = gateway.transactions.load_manifest(
        task["transaction_id"]
    )

    assert transaction.status.value == "rolled_back"
    assert transaction.metadata["repair_cycle"]["attempts"] == 2

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


def test_real_autonomy_cycle_recovers_after_crash_during_repair(
    tmp_path,
    monkeypatch,
):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "repair-crash-integration"},
            )
        ]
    )

    gateway = DevAgentGateway(
        RepairAgent(),
        root=tmp_path,
    )

    gateway.repair_engine.ai = RepairAdapter()

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    def crash_during_repair(diagnosis, instruction, transaction):
        raise SystemExit("CRASH_DURING_AUTONOMOUS_REPAIR")

    monkeypatch.setattr(
        gateway.repair_executor,
        "execute_repair",
        crash_during_repair,
    )

    try:
        loop.run_once()
    except SystemExit as error:
        assert str(error) == "CRASH_DURING_AUTONOMOUS_REPAIR"
    else:
        raise AssertionError(
            "O ciclo autônomo deveria ter sido interrompido durante o reparo."
        )

    tasks = gateway.list_tasks()

    assert len(tasks) == 1

    approval_id = tasks[0]["approval_id"]
    task = gateway.get_task(approval_id)

    assert task["status"] == "testing"
    assert task["transaction_id"] is not None

    recoverable = (
        gateway.transactions.list_recoverable_transactions()
    )

    assert len(recoverable) == 1

    restarted = DevAgentGateway(
        RepairAgent(),
        root=tmp_path,
    )

    assert (
        restarted.transactions.list_recoverable_transactions()
        == []
    )

    recovered_task = restarted.get_task(approval_id)

    assert recovered_task["status"] == "rolled_back"

    target = tmp_path / "autonomous_smoke.py"

    assert not target.exists()

    transaction = restarted.transactions.load_manifest(
        recovered_task["transaction_id"]
    )

    assert transaction.status.value == "rolled_back"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
                       "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


def test_real_autonomy_restart_after_recovery_does_not_reprocess_observation(
    tmp_path,
    monkeypatch,
):
    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    observation_store = ObservationStore(observation_path)
    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "recovery-idempotency"},
            )
        ]
    )

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(loop_path),
    )

    def crash_during_execution(transaction, on_change_applied=None):
        raise SystemExit("CRASH_BEFORE_COMPLETION")

    monkeypatch.setattr(
        gateway.executor,
        "execute",
        crash_during_execution,
    )

    try:
        loop.run_once()
    except SystemExit as error:
        assert str(error) == "CRASH_BEFORE_COMPLETION"
    else:
        raise AssertionError(
            "O ciclo deveria ter sido interrompido pelo crash."
        )

    tasks_before_restart = gateway.list_tasks()

    assert len(tasks_before_restart) == 1
    approval_id = tasks_before_restart[0]["approval_id"]

    restarted_gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    recovered_task = restarted_gateway.get_task(approval_id)

    assert recovered_task["status"] == "rolled_back"

    restarted_worker = Worker(
        restarted_gateway,
        Observer(
            store=ObservationStore(observation_path)
        ),
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
    )

    restarted_loop = SupervisedLoop(
        restarted_worker,
        restarted_gateway,
        state_store=WorkerStateStore(loop_path),
    )

    result = restarted_loop.run_once()

    assert result.proposals == []
    assert result.metadata["proposal_count"] == 0
    assert result.metadata["auto_approved_count"] == 0
    assert result.metadata["pending_count"] == 0

    tasks_after_restart = restarted_gateway.list_tasks()

    assert len(tasks_after_restart) == 1
    assert tasks_after_restart[0]["approval_id"] == approval_id
    assert tasks_after_restart[0]["status"] == "rolled_back"

    assert not (tmp_path / "autonomous_smoke.py").exists()


def test_real_autonomy_concurrent_processes_do_not_duplicate_observation(
    tmp_path,
):
    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    ObservationStore(observation_path).save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "concurrent-autonomy"},
            )
        ]
    )

    script = tmp_path / "run_concurrent_agent.py"
    script.write_text(
        """
from pathlib import Path
import sys

from core.autonomy_policy import AutonomyPolicy
from core.gateway import DevAgentGateway
from core.observation_store import ObservationStore
from core.observer import Observer
from core.supervised_loop import SupervisedLoop
from core.worker import Worker
from core.worker_state_store import WorkerStateStore


class CreateAgent:
    def process(self, instruction):
        return {
            "instruction": instruction,
            "objective": instruction,
            "changes": [
                {
                    "change_type": "create",
                    "path": "concurrent_autonomy_smoke.py",
                    "content": "VALUE = 42\\n",
                }
            ],
            "tests": [],
            "risks": [],
        }

    def build_transaction_from_approved_plan(self, plan):
        from uuid import uuid4
        from core.schemas.models import Change, ChangeType, Transaction

        changes = [
            Change(
                change_type=ChangeType(item["change_type"]),
                path=item["path"],
                content=item.get("content"),
                reason=item.get("reason", ""),
            )
            for item in plan["changes"]
        ]

        return Transaction(
            transaction_id=str(uuid4()),
            changes=changes,
            metadata={"tests": plan.get("tests", [])},
        )


root = Path(sys.argv[1])

gateway = DevAgentGateway(
    CreateAgent(),
    root=root,
)

worker = Worker(
    gateway,
    Observer(
        store=ObservationStore(root / "observations.json")
    ),
    store=WorkerStateStore(root / "worker.json"),
    autonomy_policy=AutonomyPolicy(),
)

loop = SupervisedLoop(
    worker,
    gateway,
    state_store=WorkerStateStore(
        root / "supervised_loop.json"
    ),
)

result = loop.run_once()

print(
    result.metadata["proposal_count"],
    result.metadata["auto_approved_count"],
)
""",
        encoding="utf-8",
    )

    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())

    first = subprocess.Popen(
        [sys.executable, str(script), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    second = subprocess.Popen(
        [sys.executable, str(script), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    first_stdout, first_stderr = first.communicate()
    second_stdout, second_stderr = second.communicate()

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr

    outputs = {
        first_stdout.strip(),
        second_stdout.strip(),
    }

    assert outputs <= {"0 0", "1 1"}
    assert sum(
        output == "1 1"
        for output in [first_stdout.strip(), second_stdout.strip()]
    ) == 1

    tasks = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    ).list_tasks()

    assert len(tasks) == 1
    assert tasks[0]["status"] == "committed"

    target = tmp_path / "concurrent_autonomy_smoke.py"

    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "concurrent_autonomy_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""


def test_real_transaction_feedback_creates_persistent_correction_proposal(
    tmp_path,
):
    from core.execution_feedback import ExecutionFeedback
    from core.feedback_handler import FeedbackHandler

    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"

    observation_store = ObservationStore(observation_path)

    failed_result = {
        "approval_id": "approval-original",
        "status": "failed",
        "transaction_id": "tx-feedback-e2e",
        "tests": {
            "success": False,
            "error": "TEST_FAILURE",
        },
        "repair_attempts": 2,
        "error": "TEST_FAILURE",
    }

    observation = ExecutionFeedback().build(failed_result)
    assert observation is not None

    observation_store.append(observation)

    class FeedbackGateway:
        def __init__(self):
            self.created = []

        def create_task(self, instruction):
            self.created.append(instruction)
            return {
                "approval_id": "approval-correction-e2e",
                "status": "pending",
                "plan": {
                    "instruction": instruction,
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": [],
                },
            }

    gateway = FeedbackGateway()

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=WorkerStateStore(worker_path),
        feedback_handler=FeedbackHandler(),
    )

    first = worker.run_once()

    assert len(first) == 1
    assert first[0].approval_id == "approval-correction-e2e"
    assert first[0].status == "pending"
    assert len(gateway.created) == 1
    assert "tx-feedback-e2e" in gateway.created[0]

    restarted_gateway = FeedbackGateway()

    restarted_worker = Worker(
        restarted_gateway,
        Observer(store=ObservationStore(observation_path)),
        store=WorkerStateStore(worker_path),
        feedback_handler=FeedbackHandler(),
    )

    second = restarted_worker.run_once()

    assert second == []
    assert restarted_gateway.created == []
    assert len(restarted_worker.processed_ids) == 1


def test_real_transaction_feedback_proposal_requires_human_approval(tmp_path):
    from core.execution_feedback import ExecutionFeedback
    from core.feedback_handler import FeedbackHandler

    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"
    loop_path = tmp_path / "supervised_loop.json"

    observation_store = ObservationStore(observation_path)

    observation = ExecutionFeedback().build(
        {
            "approval_id": "approval-original",
            "status": "failed",
            "transaction_id": "tx-human-feedback",
            "tests": {"success": False, "error": "TEST_FAILURE"},
            "repair_attempts": 2,
            "error": "TEST_FAILURE",
        }
    )

    assert observation is not None
    observation_store.append(observation)

    class FeedbackGateway:
        def __init__(self):
            self.created = []
            self.approved = []

        def create_task(self, instruction):
            self.created.append(instruction)
            return {
                "approval_id": "approval-correction-human",
                "status": "pending",
                "plan": {
                    "instruction": instruction,
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": ["Correção requer supervisão"],
                },
            }

        def approve(self, approval_id):
            self.approved.append(approval_id)
            raise AssertionError(
                "Proposta corretiva não deve ser aprovada automaticamente."
            )

        def list_tasks(self):
            return []

    gateway = FeedbackGateway()

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=WorkerStateStore(worker_path),
        autonomy_policy=AutonomyPolicy(),
        feedback_handler=FeedbackHandler(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(loop_path),
    )

    result = loop.run_once()

    assert len(result.proposals) == 1
    proposal = result.proposals[0]

    assert proposal.approval_id == "approval-correction-human"
    assert proposal.autonomy_decision == "require_human"
    assert result.metadata["auto_approved_count"] == 0
    assert gateway.approved == []
    assert len(gateway.created) == 1


def test_real_transaction_feedback_correction_approval_execution_commit(tmp_path):
    from core.execution_feedback import ExecutionFeedback

    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )

    observation = ExecutionFeedback().build(
        {
            "approval_id": "approval-original",
            "status": "failed",
            "transaction_id": "tx-human-feedback",
            "tests": {
                "success": False,
                "error": "TEST_FAILURE",
            },
            "repair_attempts": 2,
            "error": "TEST_FAILURE",
            "metadata": {
                "changes": [
                    {
                        "change_type": "create",
                        "path": "autonomous_smoke.py",
                        "content": "VALUE = 42\n",
                        "reason": "Criar arquivo.",
                    }
                ],
            },
        }
    )
    observation_store.append(observation)

    gateway = DevAgentGateway(
        CreateAgent(),
        root=tmp_path,
    )

    observer = Observer(store=observation_store)
    worker = Worker(
        gateway,
        observer,
        store=worker_store,
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(tmp_path / "supervised_loop.json"),
        observer=observer,
    )

    result = worker.run_once()

    assert len(result) == 1, worker.errors

    proposal = result[0]
    approval_id = proposal.approval_id

    task = gateway.get_task(approval_id)
    assert task["status"] == "pending"
    assert task["plan"]["changes"]

    change = task["plan"]["changes"][0]
    assert change["path"] == "autonomous_smoke.py"
    assert change["change_type"] == "create"

    approval_result = loop.approve(approval_id)

    assert approval_result["status"] == "committed"

    final_task = gateway.get_task(approval_id)
    assert final_task["status"] == "committed"

    target = tmp_path / "autonomous_smoke.py"
    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    observations = observation_store.load()
    feedback_observations = [
        item
        for item in observations
        if item.metadata.get("source") == "transaction_result"
    ]

    assert len(feedback_observations) == 2

    original_feedback = feedback_observations[0]
    assert original_feedback.metadata["transaction_id"] == "tx-human-feedback"
    assert original_feedback.metadata["approval_id"] == "approval-original"
    assert original_feedback.metadata["status"] == "failed"

    approval_feedback = feedback_observations[1]
    assert approval_feedback.metadata["transaction_id"] == approval_result["transaction_id"]
    assert approval_feedback.metadata["approval_id"] == approval_id
    assert approval_feedback.metadata["status"] == "committed"

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""

def test_real_transaction_feedback_second_failure_creates_second_correction(tmp_path):
    from uuid import uuid4

    from core.execution_feedback import ExecutionFeedback
    from core.observation_store import ObservationStore
    from core.observer import Observer
    from core.schemas.models import Change, ChangeType, Transaction
    from core.worker import Worker

    class AlwaysFailingAgent:
        def __init__(self):
            self.build_count = 0

        def process(self, instruction, feedback_context=None):
            if feedback_context:
                return {
                    "instruction": instruction,
                    "objective": instruction,
                    "changes": [
                        {
                            "change_type": "create",
                            "path": "second_cycle_smoke.py",
                            "content": "def broken():\n    pass\n",
                            "reason": "Correção da falha de sintaxe.",
                        }
                    ],
                    "tests": [],
                    "risks": [],
                }

            return {
                "instruction": instruction,
                "objective": instruction,
                "changes": [
                    {
                        "change_type": "create",
                        "path": "second_cycle_smoke.py",
                        "content": "VALUE = 42\n",
                        "reason": "Criar arquivo.",
                    }
                ],
                "tests": [],
                "risks": [],
            }

        def build_transaction_from_approved_plan(self, plan):
            changes = [
                Change(
                    change_type=ChangeType(item["change_type"]),
                    path=item["path"],
                    content=item.get("content"),
                    reason=item.get("reason", ""),
                )
                for item in plan["changes"]
            ]

            transaction = Transaction(
                transaction_id=str(uuid4()),
                changes=changes,
                metadata={
                    "instruction": plan["instruction"],
                    "objective": plan.get("objective"),
                    "tests": plan.get("tests", []),
                    "risks": plan.get("risks", []),
                    "changes": [
                        {
                            "change_type": change.change_type.value,
                            "path": change.path,
                            "content": change.content,
                            "reason": change.reason,
                        }
                        for change in changes
                    ],
                },
            )

            if self.build_count == 0:
                transaction.changes[0].content = "def broken(:\n"

            self.build_count += 1
            return transaction

    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )

    first_feedback = ExecutionFeedback().build(
        {
            "approval_id": "approval-first-failure",
            "status": "failed",
            "transaction_id": "tx-first-failure",
            "tests": {
                "success": False,
                "error": "TEST_FAILURE",
            },
            "repair_attempts": 0,
            "error": "TEST_FAILURE",
            "metadata": {
                "changes": [
                    {
                        "change_type": "create",
                        "path": "second_cycle_smoke.py",
                        "content": "def broken(:\n",
                        "reason": "Criar arquivo.",
                    }
                ]
            },
        }
    )
    observation_store.append(first_feedback)

    gateway = DevAgentGateway(
        AlwaysFailingAgent(),
        root=tmp_path,
    )
    observer = Observer(store=observation_store)
    worker = Worker(
        gateway,
        observer,
        store=worker_store,
    )
    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=WorkerStateStore(
            tmp_path / "supervised_loop.json"
        ),
        observer=observer,
    )

    first_result = worker.run_once()

    assert len(first_result) == 1, worker.errors

    first_proposal = first_result[0]
    first_approval_id = first_proposal.approval_id

    first_task = gateway.get_task(first_approval_id)
    assert first_task["status"] == "pending"
    assert first_task["plan"]["changes"][0]["path"] == "second_cycle_smoke.py"

    first_execution = loop.approve(first_approval_id)

    assert first_execution["status"] == "rolled_back"

    observations = observation_store.load()
    transaction_feedback = [
        item
        for item in observations
        if item.metadata.get("source") == "transaction_result"
    ]

    assert len(transaction_feedback) == 2

    execution_feedback = transaction_feedback[-1]

    assert execution_feedback.metadata["transaction_id"] == (
        first_execution["transaction_id"]
    )
    assert execution_feedback.metadata["approval_id"] == first_approval_id
    assert execution_feedback.metadata["status"] == "rolled_back"

    second_result = worker.run_once()

    assert len(second_result) == 1, worker.errors

    second_proposal = second_result[0]

    assert second_proposal.approval_id != first_approval_id

    second_task = gateway.get_task(second_proposal.approval_id)

    assert second_task["status"] == "pending"
    assert second_task["plan"]["changes"][0]["path"] == "second_cycle_smoke.py"
    assert second_task["plan"]["changes"][0]["change_type"] == "create"
    assert second_task["plan"]["changes"][0]["content"] == "def broken():\n    pass\n"

    second_execution = loop.approve(second_proposal.approval_id)

    assert second_execution["status"] == "committed"

    corrected_file = tmp_path / "second_cycle_smoke.py"
    assert corrected_file.read_text() == "def broken():\n    pass\n"

    final_observations = observation_store.load()
    final_transaction_results = [
        item
        for item in final_observations
        if item.metadata.get("source") == "transaction_result"
    ]

    assert len(final_transaction_results) == 3
    assert final_transaction_results[-1].metadata["status"] == "committed"

    second_result_after_commit = worker.run_once()
    assert second_result_after_commit == []
    assert worker.errors == []

    assert len(worker.errors) == 0
def test_real_autonomy_retry_instruction_persists_across_worker_restart(
    tmp_path,
):
    from core.execution_feedback import ExecutionFeedback
    from core.feedback_handler import FeedbackHandler

    init_git(tmp_path)

    observation_path = tmp_path / "observations.json"
    worker_path = tmp_path / "worker.json"

    observation_store = ObservationStore(observation_path)
    worker_state_store = WorkerStateStore(worker_path)

    original_instruction = "criar arquivo após falha"

    class RetryGateway:
        def __init__(self):
            self.created = []

        def create_task(self, instruction):
            self.created.append(instruction)
            return {
                "approval_id": f"approval-{len(self.created)}",
                "status": "pending",
                "plan": {
                    "instruction": instruction,
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": [],
                },
            }

    observation_store.append(
        Observation(
            instruction=original_instruction,
            metadata={"source": "retry-persistence-e2e"},
        )
    )

    first_gateway = RetryGateway()
    first_worker = Worker(
        first_gateway,
        Observer(store=observation_store),
        store=worker_state_store,
        feedback_handler=FeedbackHandler(),
    )

    first = first_worker.run_once()

    assert len(first) == 1
    assert first[0].status == "pending"
    assert first_gateway.created == [original_instruction]

    failed_result = {
        "approval_id": first[0].approval_id,
        "status": "failed",
        "transaction_id": "tx-retry-persistence-e2e",
        "tests": {
            "success": False,
            "error": "TEST_FAILURE",
        },
        "repair_attempts": 2,
        "error": "TEST_FAILURE",
        "metadata": {
            "instruction": original_instruction,
        },
    }

    feedback = ExecutionFeedback().build(failed_result)

    assert feedback is not None
    observation_store.append(feedback)

    restarted_gateway = RetryGateway()
    restarted_worker = Worker(
        restarted_gateway,
        Observer(store=ObservationStore(observation_path)),
        store=WorkerStateStore(worker_path),
        feedback_handler=FeedbackHandler(),
    )

    first_restart_cycle = restarted_worker.run_once()

    assert len(first_restart_cycle) == 1
    assert first_restart_cycle[0].autonomy_decision == "require_human"
    assert original_instruction in restarted_worker._retry_instructions
    assert len(restarted_gateway.created) == 1
    assert "Analise a transação tx-retry-persistence-e2e" in restarted_gateway.created[0]

    second_restart_cycle = restarted_worker.run_once()

    assert len(second_restart_cycle) == 1
    assert second_restart_cycle[0].status == "pending"
    assert restarted_gateway.created[-1] == original_instruction
    assert original_instruction not in restarted_worker._retry_instructions

    final_gateway = RetryGateway()
    final_worker = Worker(
        final_gateway,
        Observer(store=ObservationStore(observation_path)),
        store=WorkerStateStore(worker_path),
        feedback_handler=FeedbackHandler(),
    )

    final_cycle = final_worker.run_once()

    assert final_cycle == []
    assert final_gateway.created == []
    assert original_instruction not in final_worker._retry_instructions

def test_real_autonomy_cycle_repair_physical_mismatch_rolls_back(
    tmp_path,
    monkeypatch,
):
    init_git(tmp_path)

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_store = WorkerStateStore(
        tmp_path / "worker.json"
    )
    loop_store = WorkerStateStore(
        tmp_path / "supervised_loop.json"
    )

    observation_store.save(
        [
            Observation(
                "criar arquivo autonomamente",
                {"source": "repair-physical-mismatch"},
            )
        ]
    )

    gateway = DevAgentGateway(
        RepairAgent(),
        root=tmp_path,
    )

    repair_adapter = RepairAdapter()
    repair_adapter.prompts = []
    gateway.repair_engine.ai = repair_adapter

    original_execute_change = gateway.executor.execute_change

    def execute_change_with_physical_mismatch(change):
        if change.content == "VALUE = 42\n":
            target = tmp_path / change.path
            target.write_text(
                "VALUE = 999\n",
                encoding="utf-8",
            )
            return None

        return original_execute_change(change)

    monkeypatch.setattr(
        gateway.executor,
        "execute_change",
        execute_change_with_physical_mismatch,
    )

    worker = Worker(
        gateway,
        Observer(store=observation_store),
        store=worker_store,
        autonomy_policy=AutonomyPolicy(),
    )

    loop = SupervisedLoop(
        worker,
        gateway,
        state_store=loop_store,
    )

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0].autonomy_decision == "auto_approve"
    assert result.metadata["auto_approved_count"] == 1

    assert len(repair_adapter.prompts) == 1

    target = tmp_path / "autonomous_smoke.py"
    assert not target.exists()

    proposal = result.proposals[0]
    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "rolled_back"

    transaction = gateway.transactions.load_manifest(
        task["transaction_id"]
    )

    assert transaction.status.value == "rolled_back"
    assert transaction.metadata["repair_cycle"]["attempts"] == 1

    git_status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "autonomous_smoke.py",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""

def test_real_transaction_feedback_is_recovered_after_restart(tmp_path):
    from core.execution_feedback import ExecutionFeedback

    init_git(tmp_path)

    observation_store = ObservationStore(tmp_path / "observations.json")
    worker_store = WorkerStateStore(tmp_path / "worker.json")

    observation = ExecutionFeedback().build(
        {
            "approval_id": "approval-original",
            "transaction_id": "tx-human-feedback",
            "status": "failed",
            "tests": {"passed": False},
            "repair_attempts": 2,
            "metadata": {
                "instruction": "corrigir arquivo quebrado",
                "objective": "autonomous correction",
                "repair_cycle": {
                    "attempts": 2,
                    "max_attempts": 2,
                },
                "change": {
                    "type": "create",
                    "path": "autonomous_smoke.py",
                    "content": "VALUE = 42\n",
                },
            },
        }
    )

    observation_store.append(observation)

    gateway = DevAgentGateway(CreateAgent(), root=tmp_path)

    class FailingFeedbackObserver(Observer):
        def add(self, observation):
            if observation.metadata.get("source") == "transaction_result":
                raise RuntimeError("FEEDBACK_PERSIST_FAILURE")
            return super().add(observation)

    observer = FailingFeedbackObserver(store=observation_store)
    worker = Worker(gateway, observer, store=worker_store)
    loop = SupervisedLoop(
        worker=worker,
        gateway=gateway,
        observer=observer,
        state_store=WorkerStateStore(tmp_path / "supervised_loop.json"),
    )

    result = worker.run_once()
    assert len(result) == 1

    approval_id = result[0].approval_id

    try:
        loop.approve(approval_id)
    except RuntimeError as error:
        assert str(error) == "FEEDBACK_PERSIST_FAILURE"
    else:
        raise AssertionError("A falha de persistência do feedback deveria propagar.")

    target = tmp_path / "autonomous_smoke.py"
    assert target.read_text(encoding="utf-8") == "VALUE = 42\n"

    committed_task = gateway.get_task(approval_id)
    assert committed_task["status"] == "committed"

    observations_before_restart = observation_store.load()
    feedback_before_restart = [
        item
        for item in observations_before_restart
        if item.metadata.get("source") == "transaction_result"
    ]
    assert len(feedback_before_restart) == 1
    assert feedback_before_restart[0].metadata["status"] == "failed"

    restarted_gateway = DevAgentGateway(CreateAgent(), root=tmp_path)
    restarted_observation_store = ObservationStore(tmp_path / "observations.json")
    restarted_observer = Observer(store=restarted_observation_store)
    restarted_worker = Worker(
        restarted_gateway,
        restarted_observer,
        store=worker_store,
    )

    restarted_worker.run_once()

    observations_after_restart = restarted_observation_store.load()
    feedback_after_restart = [
        item
        for item in observations_after_restart
        if item.metadata.get("source") == "transaction_result"
    ]

    assert len(feedback_after_restart) == 2
    assert sorted(
        item.metadata["status"] for item in feedback_after_restart
    ) == ["committed", "failed"]

    committed_feedback = [
        item
        for item in feedback_after_restart
        if item.metadata["status"] == "committed"
    ]
    assert len(committed_feedback) == 1
    assert committed_feedback[0].metadata["transaction_id"] == committed_task["transaction_id"]

    restarted_worker.run_once()

    observations_after_second_restart_cycle = restarted_observation_store.load()
    feedback_after_second_restart_cycle = [
        item
        for item in observations_after_second_restart_cycle
        if item.metadata.get("source") == "transaction_result"
    ]

    assert len(feedback_after_second_restart_cycle) == 2
