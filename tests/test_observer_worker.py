import pytest

from core.observation import Observation
from core.observer import Observer
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


def test_observer_persists_observations(tmp_path):
    from core.observation_store import ObservationStore

    store = ObservationStore(tmp_path / "observations.json")
    observer = Observer(store=store)

    observation = Observation(
        instruction="persistir observação",
        metadata={"source": "test"},
    )

    observer.add(observation)

    restored = Observer(store=store)

    assert restored.observe() == [observation]


def test_observer_without_store_remains_ephemeral():
    observation = Observation(
        instruction="temporária",
        metadata={"source": "test"},
    )

    observer = Observer()
    observer.add(observation)

    assert observer.observe() == [observation]


def test_worker_exports_and_restores_state():
    gateway = FakeGateway()
    observer = Observer([
        Observation("criar arquivo", {"source": "test"})
    ])
    worker = Worker(gateway, observer)

    proposals = worker.run_once()
    state = worker.export_state()

    restored = Worker(gateway, observer)
    restored.restore_state(state)

    assert restored.processed_ids == {proposals[0].approval_id}
    assert restored.run_once() == []


def test_worker_rejects_invalid_state():
    worker = Worker(FakeGateway(), Observer())

    with pytest.raises(ValueError):
        worker.restore_state([])

    with pytest.raises(ValueError):
        worker.restore_state({"processed": "invalid"})

    with pytest.raises(ValueError):
        worker.restore_state({"processed": [], "processed_ids": [""]})

def test_worker_loads_persisted_state_and_skips_processed_observation(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")

    first_gateway = FakeGateway()
    observer = Observer([
        Observation(
            "criar arquivo",
            {"source": "test"},
        )
    ])

    worker = Worker(first_gateway, observer, store=store)
    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].approval_id

    second_gateway = FakeGateway()
    restored_worker = Worker(second_gateway, observer, store=store)

    assert restored_worker.run_once() == []
    assert restored_worker.processed_ids == {proposals[0].approval_id}


def test_worker_persists_state_after_processing(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")
    gateway = FakeGateway()
    observer = Observer([
        Observation(
            "criar arquivo",
            {"source": "test"},
        )
    ])

    worker = Worker(gateway, observer, store=store)
    proposal = worker.run_once()[0]

    persisted = store.load()

    assert persisted["processed"] == [
        {
            "instruction": "criar arquivo",
            "metadata": {"source": "test"},
        }
    ]
    assert persisted["processed_ids"] == [proposal.approval_id]


def test_worker_rejects_invalid_store():
    gateway = FakeGateway()
    observer = Observer()

    with pytest.raises(ValueError, match="Store do Worker inválido"):
        Worker(gateway, observer, store=object())


class FailingGateway:
    def __init__(self):
        self.calls = []

    def create_task(self, instruction):
        self.calls.append(instruction)
        if instruction == "falhar":
            raise RuntimeError("falha simulada")
        return {
            "approval_id": str(len(self.calls)),
            "status": "pending",
            "plan": {
                "instruction": instruction,
                "changes": [],
            },
        }


def test_worker_isolates_observation_failure():
    gateway = FailingGateway()
    observer = Observer(
        [
            Observation("falhar", {"source": "test"}),
            Observation("funcionar", {"source": "test"}),
        ]
    )
    worker = Worker(gateway, observer)

    proposals = worker.run_once()

    assert [proposal.instruction for proposal in proposals] == [
        "funcionar"
    ]
    assert gateway.calls == ["falhar", "funcionar"]
    assert worker.errors == [
        {
            "instruction": "falhar",
            "error": "falha simulada",
        }
    ]


def test_worker_retries_failed_observation_on_next_round():
    gateway = FailingGateway()
    observer = Observer(
        [Observation("falhar", {"source": "test"})]
    )
    worker = Worker(gateway, observer)

    first = worker.run_once()
    second = worker.run_once()

    assert first == []
    assert second == []
    assert gateway.calls == ["falhar", "falhar"]
    assert worker.processed_ids == set()
    assert worker.errors == [
        {
            "instruction": "falhar",
            "error": "falha simulada",
        }
    ]


def test_worker_clears_previous_errors_on_successful_round():
    gateway = FailingGateway()
    observer = Observer(
        [
            Observation("falhar", {"source": "test"}),
        ]
    )
    worker = Worker(gateway, observer)

    worker.run_once()

    worker.observer = Observer(
        [
            Observation("nova tarefa", {"source": "test"}),
        ]
    )
    gateway.calls.clear()

    proposals = worker.run_once()

    assert [proposal.instruction for proposal in proposals] == [
        "nova tarefa"
    ]
    assert worker.errors == []
