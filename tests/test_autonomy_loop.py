import pytest

from core.autonomy_loop import AutonomyLoop
from core.observer import Observation, Observer
from core.worker import Worker


class FakeGateway:
    def __init__(self):
        self.calls = []

    def create_task(self, instruction):
        self.calls.append(instruction)
        return {
            "approval_id": str(len(self.calls)),
            "status": "pending",
            "plan": {
                "instruction": instruction,
                "changes": [],
            },
        }


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
    from core.worker_state_store import WorkerStateStore

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
    from core.worker_state_store import WorkerStateStore

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
    from core.worker_state_store import WorkerStateStore

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
    from agent import DevAgent
    from core.gateway import DevAgentGateway
    from core.observation import Observation
    from core.observer import Observer

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)
    observer = Observer([
        Observation(
            instruction="crie smoke_test.py contendo assert 2 + 2 == 4",
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
        "crie smoke_test.py contendo assert 2 + 2 == 4"
    )

    task = gateway.get_task(proposal.approval_id)

    assert task["status"] == "pending"
    assert task["approval_id"] == proposal.approval_id
