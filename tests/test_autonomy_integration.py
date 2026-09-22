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
    def process(self, instruction):
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

    assert task["status"] == "failed"

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

    def crash_during_execution(transaction):
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
    def generate(self, prompt):
        import json

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

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0].autonomy_decision == "auto_approve"
    assert result.metadata["auto_approved_count"] == 1

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

    def crash_during_execution(transaction):
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
