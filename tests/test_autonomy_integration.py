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
        ["git", "status", "--porcelain", "--", "autonomous_smoke.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert git_status == ""

class FailingCreateAgent(CreateAgent):
    def build_transaction_from_approved_plan(self, plan):
        transaction = super().build_transaction_from_approved_plan(plan)
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

    observation_store.save([
        Observation(
            "criar arquivo autonomamente",
            {"source": "integration"},
        )
    ])

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
