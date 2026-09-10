import pytest

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


def test_observation_is_immutable():
    observation = Observation("verificar projeto", {"source": "test"})

    assert observation.instruction == "verificar projeto"
    assert observation.metadata["source"] == "test"


def test_observer_returns_snapshot():
    observation = Observation("verificar projeto", {})
    observer = Observer([observation])

    result = observer.observe()
    result.clear()

    assert len(observer.observe()) == 1


def test_observer_rejects_invalid_observation():
    observer = Observer()

    with pytest.raises(ValueError, match="Observação inválida"):
        observer.add(None)


def test_worker_creates_pending_proposal():
    gateway = FakeGateway()
    observer = Observer([
        Observation("verificar testes", {"source": "observer"})
    ])

    worker = Worker(gateway, observer)

    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].approval_id == "1"
    assert proposals[0].status == "pending"
    assert gateway.calls == ["verificar testes"]


def test_worker_never_approves_or_executes():
    gateway = FakeGateway()
    observer = Observer([
        Observation("verificar testes", {})
    ])

    worker = Worker(gateway, observer)

    worker.run_once()

    assert not hasattr(gateway, "approve")
    assert not hasattr(gateway, "execute_approved")


def test_worker_tracks_processed_ids():
    gateway = FakeGateway()
    observer = Observer([
        Observation("primeira tarefa", {})
    ])

    worker = Worker(gateway, observer)
    worker.run_once()

    assert worker.processed_ids == {"1"}


def test_worker_rejects_invalid_gateway():
    observer = Observer()

    with pytest.raises(ValueError, match="Gateway inválido"):
        Worker(None, observer)


def test_worker_rejects_invalid_observer():
    with pytest.raises(ValueError, match="Observer inválido"):
        Worker(FakeGateway(), None)


def test_worker_rejects_invalid_observation():
    worker = Worker(FakeGateway(), Observer())

    with pytest.raises(ValueError, match="Observação inválida"):
        worker.process_observation(None)


def test_worker_does_not_reprocess_same_observation():
    gateway = FakeGateway()
    observer = Observer([
        Observation("verificar testes", {"source": "observer"})
    ])

    worker = Worker(gateway, observer)

    first = worker.run_once()
    second = worker.run_once()

    assert len(first) == 1
    assert second == []
    assert gateway.calls == ["verificar testes"]


def test_worker_allows_distinct_observations():
    gateway = FakeGateway()
    observer = Observer([
        Observation("primeira tarefa", {"source": "a"}),
        Observation("segunda tarefa", {"source": "b"}),
    ])

    worker = Worker(gateway, observer)

    proposals = worker.run_once()

    assert [p.instruction for p in proposals] == [
        "primeira tarefa",
        "segunda tarefa",
    ]
    assert gateway.calls == ["primeira tarefa", "segunda tarefa"]
