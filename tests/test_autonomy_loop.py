from core.gateway import DevAgentGateway
from agent import DevAgent
from core.worker_state_store import WorkerStateStore
from core.observation_store import ObservationStore
import subprocess
import pytest

from core.autonomy_loop import AutonomyLoop
from core.observer import Observation, Observer
from core.worker import Worker


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.tasks = []

    def create_task(self, instruction):
        self.calls.append(instruction)
        approval_id = str(len(self.calls))
        task = {
            "task_id": approval_id,
            "approval_id": approval_id,
            "instruction": instruction,
            "status": "pending",
            "plan": {
                "instruction": instruction,
                "changes": [],
            },
        }
        self.tasks.append(task)
        return {
            "approval_id": approval_id,
            "status": "pending",
            "plan": task["plan"],
        }

    def list_pending(self):
        return [
            task
            for task in self.tasks
            if task["status"] == "pending"
        ]


def test_loop_requires_worker():
    with pytest.raises(ValueError, match="Worker inválido"):
        AutonomyLoop(None)


def test_loop_runs_one_observation_round():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    result = loop.run_once()

    assert result.stopped is False
    assert len(result.proposals) == 1
    assert result.proposals[0].status == "pending"
    assert result.metadata["iterations"] == 1
    assert result.metadata["proposal_count"] == 1


def test_loop_is_idempotent_for_same_observation():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    first = loop.run_once()
    second = loop.run_once()

    assert len(first.proposals) == 1
    assert second.proposals == []
    assert loop.iterations == 2
    assert gateway.calls == ["verificar projeto"]


def test_loop_can_be_stopped():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    loop.stop()
    result = loop.run_once()

    assert loop.stopped is True
    assert result.stopped is True
    assert result.proposals == []
    assert result.metadata["iterations"] == 0
    assert gateway.calls == []


def test_loop_does_not_execute_approval():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    result = loop.run_once()

    assert result.proposals[0].status == "pending"
    assert not hasattr(gateway, "approve")
    assert not hasattr(gateway, "execute_approved")

def test_loop_restores_worker_state_after_restart(tmp_path):

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [
            Observation("primeira tarefa", {"source": "test"}),
            Observation("segunda tarefa", {"source": "test"}),
        ]
    )

    gateway = FakeGateway()
    worker = Worker(gateway, observer, store=store)
    first_loop = AutonomyLoop(worker)

    first = first_loop.run_once()

    assert len(first.proposals) == 2
    assert first.stopped is False
    assert first.metadata["iterations"] == 1

    restored_worker = Worker(
        gateway,
        observer,
        store=store,
    )
    second_loop = AutonomyLoop(restored_worker)

    second = second_loop.run_once()

    assert second.proposals == []
    assert second.stopped is False
    assert second.metadata["iterations"] == 1
    assert gateway.calls == [
        "primeira tarefa",
        "segunda tarefa",
    ]


def test_loop_stop_does_not_modify_persisted_worker_state(tmp_path):

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [Observation("tarefa", {"source": "test"})]
    )
    gateway = FakeGateway()
    worker = Worker(gateway, observer, store=store)

    loop = AutonomyLoop(worker)
    loop.stop()

    result = loop.run_once()

    assert result.stopped is True
    assert result.proposals == []
    assert worker.processed_ids == set()
    assert store.load() == {}


def test_loop_iterations_are_runtime_state_only(tmp_path):

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [Observation("tarefa", {"source": "test"})]
    )
    gateway = FakeGateway()

    worker = Worker(gateway, observer, store=store)
    first_loop = AutonomyLoop(worker)
    first_loop.run_once()

    assert first_loop.iterations == 1

    restored_worker = Worker(
        gateway,
        observer,
        store=store,
    )
    second_loop = AutonomyLoop(restored_worker)

    assert second_loop.iterations == 0
    second_loop.run_once()
    assert second_loop.iterations == 1

def test_autonomy_loop_real_gateway_creates_pending_proposal(tmp_path):
    from core.observation import Observation
    from core.observer import Observer


    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)
    observer = Observer([
        Observation(
            instruction="crie smoke_test.py contendo def test_smoke(): assert 2 + 2 == 4",
            metadata={"source": "integration"},
        )
    ])
    worker = Worker(gateway, observer)
    loop = AutonomyLoop(worker)

    result = loop.run_once()

    assert result.stopped is False
    assert result.metadata["iterations"] == 1
    assert result.metadata["proposal_count"] == 1

    proposal = result.proposals[0]

    assert proposal.status == "pending"
    assert proposal.approval_id
    assert proposal.instruction == (
        "crie smoke_test.py contendo def test_smoke(): assert 2 + 2 == 4"
    )

    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "pending"
    assert task["approval_id"] == proposal.approval_id

def test_autonomy_loop_proposal_can_be_approved_through_real_gateway(tmp_path):
    from core.observation import Observation
    from core.observer import Observer

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)
    observer = Observer([
        Observation(
            instruction="crie smoke_test.py contendo def test_smoke(): assert 2 + 2 == 4",
            metadata={"source": "integration"},
        )
    ])
    worker = Worker(gateway, observer)
    loop = AutonomyLoop(worker)

    result = loop.run_once()
    proposal = result.proposals[0]

    assert proposal.status == "pending"

    approval_result = gateway.approve(proposal.approval_id)

    assert approval_result["status"] == "committed"
    assert (tmp_path / "smoke_test.py").exists()
    assert (tmp_path / "smoke_test.py").read_text() == (
        "def test_smoke(): assert 2 + 2 == 4"
    )

    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "committed"
    assert task["approval_id"] == proposal.approval_id

def test_autonomy_loop_persists_worker_state_across_restart(tmp_path):
    from core.autonomy_loop import AutonomyLoop
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_state_store = WorkerStateStore(
        tmp_path / "worker.json"
    )

    Observer(store=observation_store).add(
        Observation(
            instruction=(
                "crie loop_restart.py contendo "
                "def test_loop_restart(): assert 2 + 2 == 4"
            ),
            metadata={"source": "loop-restart"},
        )
    )

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)

    first_observer = Observer(store=observation_store)
    first_worker = Worker(
        gateway,
        first_observer,
        store=worker_state_store,
    )
    first_loop = AutonomyLoop(first_worker)

    first_result = first_loop.run_once()

    assert len(first_result.proposals) == 1
    assert first_result.proposals[0].status == "pending"

    restarted_observer = Observer(store=observation_store)
    restarted_worker = Worker(
        gateway,
        restarted_observer,
        store=worker_state_store,
    )
    restarted_loop = AutonomyLoop(restarted_worker)

    second_result = restarted_loop.run_once()

    assert second_result.proposals == []
    assert second_result.metadata["iterations"] == 1
    assert restarted_loop.iterations == 1
    assert restarted_worker.processed_ids == {
        first_result.proposals[0].approval_id
    }
def test_autonomy_loop_pending_proposal_survives_gateway_restart(tmp_path):
    from core.autonomy_loop import AutonomyLoop
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    observation_store = ObservationStore(
        tmp_path / "observations.json"
    )
    worker_state_store = WorkerStateStore(
        tmp_path / "worker.json"
    )

    Observer(store=observation_store).add(
        Observation(
            instruction=(
                "crie gateway_restart.py contendo "
                "def test_gateway_restart(): assert 2 + 2 == 4"
            ),
            metadata={"source": "gateway-restart"},
        )
    )

    agent = DevAgent(tmp_path)
    first_gateway = DevAgentGateway(agent, tmp_path)
    first_worker = Worker(
        first_gateway,
        Observer(store=observation_store),
        store=worker_state_store,
    )
    first_loop = AutonomyLoop(first_worker)

    first_result = first_loop.run_once()
    proposal = first_result.proposals[0]

    assert proposal.status == "pending"

    restarted_gateway = DevAgentGateway(
        DevAgent(tmp_path),
        tmp_path,
    )

    pending_task = restarted_gateway.get_task(
        proposal.approval_id
    )

    assert pending_task["status"] == "pending"
    assert pending_task["approval_id"] == proposal.approval_id

    approval_result = restarted_gateway.approve(
        proposal.approval_id
    )

    assert approval_result["status"] == "committed"
    assert (
        tmp_path / "gateway_restart.py"
    ).read_text(encoding="utf-8") == (
        "def test_gateway_restart(): assert 2 + 2 == 4"
    )

    final_task = restarted_gateway.get_task(
        proposal.approval_id
    )

    assert final_task["status"] == "committed"


def test_autonomy_loop_processes_new_observation_on_next_iteration(tmp_path):
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    observation_store = ObservationStore(tmp_path / "observations.json")
    worker_state_store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(store=observation_store)

    observer.add(
        Observation(
            instruction=(
                "crie iteration_one.py contendo "
                "def test_iteration_one(): assert 1 == 1"
            ),
            metadata={"source": "iteration-one"},
        )
    )

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)
    worker = Worker(
        gateway,
        observer,
        store=worker_state_store,
    )
    loop = AutonomyLoop(worker)

    first_result = loop.run_once()

    assert first_result.stopped is False
    assert len(first_result.proposals) == 1
    first_proposal = first_result.proposals[0]
    assert first_proposal.status == "pending"
    assert first_result.metadata["iterations"] == 1
    assert first_result.metadata["proposal_count"] == 1

    observer.add(
        Observation(
            instruction=(
                "crie iteration_two.py contendo "
                "def test_iteration_two(): assert 2 == 2"
            ),
            metadata={"source": "iteration-two"},
        )
    )

    second_result = loop.run_once()

    assert second_result.stopped is False
    assert len(second_result.proposals) == 1
    second_proposal = second_result.proposals[0]

    assert second_proposal.status == "pending"
    assert second_proposal.approval_id != first_proposal.approval_id
    assert second_result.metadata["iterations"] == 2
    assert second_result.metadata["proposal_count"] == 1
    assert loop.iterations == 2

    assert worker.processed_ids == {
        first_proposal.approval_id,
        second_proposal.approval_id,
    }

    first_task = gateway.get_task(first_proposal.approval_id)
    second_task = gateway.get_task(second_proposal.approval_id)

    assert first_task["status"] == "pending"
    assert second_task["status"] == "pending"

def test_run_executes_multiple_iterations():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    results = loop.run(max_iterations=3)

    assert len(results) == 3
    assert loop.iterations == 3
    assert all(not result.stopped for result in results)
    assert len(results[0].proposals) == 1
    assert results[1].proposals == []
    assert results[2].proposals == []


def test_run_respects_stop():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)
    loop.stop()

    results = loop.run(max_iterations=3)

    assert results == []
    assert loop.stopped is True
    assert loop.iterations == 0
    assert gateway.calls == []


def test_run_rejects_invalid_max_iterations():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(max_iterations=0)

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(max_iterations=-1)

    with pytest.raises(ValueError, match="max_iterations"):
        loop.run(max_iterations="3")


def test_worker_reuses_equivalent_pending_proposal():
    gateway = FakeGateway()
    first_observer = Observer(
        [Observation("verificar   projeto", {})],
    )
    worker = Worker(gateway, first_observer)

    first = worker.run_once()

    assert len(first) == 1
    assert len(gateway.calls) == 1
    first_id = first[0].approval_id

    second_observer = Observer(
        [Observation("  verificar projeto  ", {"source": "second"})],
    )
    worker.observer = second_observer

    second = worker.run_once()

    assert len(second) == 1
    assert second[0].approval_id == first_id
    assert second[0].status == "pending"
    assert len(gateway.calls) == 1


def test_worker_creates_new_proposal_after_previous_is_no_longer_pending():
    gateway = FakeGateway()
    observer = Observer(
        [Observation("verificar projeto", {})],
    )
    worker = Worker(gateway, observer)

    first = worker.run_once()

    assert len(first) == 1
    assert len(gateway.calls) == 1

    gateway.tasks[0]["status"] = "committed"

    worker.observer = Observer(
        [Observation("verificar projeto", {"retry": "yes"})],
    )

    second = worker.run_once()

    assert len(second) == 1
    assert second[0].approval_id != first[0].approval_id
    assert len(gateway.calls) == 2

def test_run_stops_when_requested_between_iterations():
    gateway = FakeGateway()
    observer = Observer(
        [
            Observation("primeira", {}),
            Observation("segunda", {}),
        ],
    )
    worker = Worker(gateway, observer)
    loop = AutonomyLoop(worker)

    original_run_once = loop.run_once
    calls = 0

    def run_once_and_stop():
        nonlocal calls
        calls += 1
        result = original_run_once()
        loop.stop()
        return result

    loop.run_once = run_once_and_stop

    results = loop.run(10)

    assert len(results) == 1
    assert calls == 1
    assert loop.stopped is True
    assert results[0].stopped is False


def test_run_returns_empty_after_being_stopped_before_start():
    gateway = FakeGateway()
    worker = Worker(
        gateway,
        Observer([Observation("verificar projeto", {})]),
    )
    loop = AutonomyLoop(worker)

    loop.stop()

    results = loop.run(10)

    assert results == []
    assert loop.stopped is True
    assert loop.iterations == 0
