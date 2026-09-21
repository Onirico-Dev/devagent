import subprocess

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
