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

def test_worker_restores_processed_state_after_restart(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [
            Observation("primeira tarefa", {"source": "test"}),
            Observation("segunda tarefa", {"source": "test"}),
        ]
    )

    first_gateway = FailingGateway()
    first_worker = Worker(first_gateway, observer, store=store)

    first_proposals = first_worker.run_once()

    assert [proposal.instruction for proposal in first_proposals] == [
        "primeira tarefa",
        "segunda tarefa",
    ]

    second_gateway = FailingGateway()
    restored_worker = Worker(second_gateway, observer, store=store)

    assert restored_worker.run_once() == []
    assert second_gateway.calls == []
    assert restored_worker.processed_ids == first_worker.processed_ids


def test_worker_restores_failed_observation_as_retryable(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [
            Observation("falhar", {"source": "test"}),
            Observation("funcionar", {"source": "test"}),
        ]
    )

    first_gateway = FailingGateway()
    first_worker = Worker(first_gateway, observer, store=store)

    first = first_worker.run_once()

    assert [proposal.instruction for proposal in first] == [
        "funcionar"
    ]

    second_gateway = FailingGateway()
    restored_worker = Worker(second_gateway, observer, store=store)

    second = restored_worker.run_once()

    assert second == []
    assert second_gateway.calls == [
        "falhar",
    ]
    assert restored_worker.errors == [
        {
            "instruction": "falhar",
            "error": "falha simulada",
        }
    ]
    assert restored_worker.processed_ids == {
        first[0].approval_id
    }


def test_worker_retries_observation_when_state_persistence_fails(monkeypatch):
    gateway = FakeGateway()
    observer = Observer(
        [Observation("persistir com falha", {"source": "test"})]
    )
    worker = Worker(gateway, observer)

    calls = {"count": 0}

    def fail_persist():
        calls["count"] += 1
        raise OSError("falha ao persistir estado")

    monkeypatch.setattr(worker, "_persist_state", fail_persist)

    first = worker.run_once()
    second = worker.run_once()

    assert first == []
    assert second == []
    assert calls["count"] == 2
    assert len(gateway.calls) == 2
    assert worker.processed_ids == set()
    assert worker.errors == [
        {
            "instruction": "persistir com falha",
            "error": "falha ao persistir estado",
        }
    ]


def test_worker_persists_only_successfully_processed_observations(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")
    observer = Observer(
        [
            Observation("falhar", {"source": "test"}),
            Observation("funcionar", {"source": "test"}),
        ]
    )

    gateway = FailingGateway()
    worker = Worker(gateway, observer, store=store)

    worker.run_once()

    persisted = store.load()

    assert persisted["processed"] == [
        {
            "instruction": "funcionar",
            "metadata": {"source": "test"},
        }
    ]
    assert len(persisted["processed_ids"]) == 1


def test_observer_rejects_empty_instruction():
    import pytest
    from core.observer import Observer
    from core.observation import Observation

    with pytest.raises(ValueError, match="instrução.*vazia"):
        Observer().add(Observation("   ", {}))


def test_worker_rejects_empty_instruction():
    import pytest
    from core.worker import Worker
    from core.observation import Observation

    with pytest.raises(ValueError, match="instrução.*vazia"):
        Worker(object(), Observer()).process_observation(Observation("   ", {}))


def test_worker_rejects_duplicate_observation():
    import pytest
    from core.worker import Worker
    from core.observation import Observation
    from core.observer import Observer

    class Gateway:
        def create_task(self, instruction):
            return {
                "instruction": instruction,
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    worker = Worker(Gateway(), Observer())
    observation = Observation("teste", {})

    worker.process_observation(observation)

    with pytest.raises(ValueError, match="já processada"):
        worker.process_observation(observation)


def test_worker_load_state_rejects_invalid_processed_ids():
    import pytest
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def create_task(self, instruction):
            return {
                "instruction": instruction,
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    with pytest.raises(ValueError, match="IDs processados"):
        Worker(Gateway(), Observer()).restore_state({
            "processed": [],
            "processed_ids": "invalid",
        })


def test_worker_load_state_rejects_invalid_record():
    import pytest
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def create_task(self, instruction):
            return {
                "instruction": instruction,
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    with pytest.raises(ValueError, match="Registro de estado inválido"):
        Worker(Gateway(), Observer()).restore_state({
            "processed": [object()],
            "processed_ids": [],
        })


def test_worker_load_state_rejects_invalid_instruction():
    import pytest
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def create_task(self, instruction):
            return {
                "instruction": instruction,
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    with pytest.raises(ValueError, match="Instrução processada inválida"):
        Worker(Gateway(), Observer()).restore_state({
            "processed": [{"instruction": "   ", "metadata": {}}],
            "processed_ids": [],
        })


def test_worker_load_state_rejects_invalid_metadata():
    import pytest
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def create_task(self, instruction):
            return {
                "instruction": instruction,
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    with pytest.raises(ValueError, match="Metadados processados inválidos"):
        Worker(Gateway(), Observer()).restore_state({
            "processed": [{"instruction": "teste", "metadata": []}],
            "processed_ids": [],
        })

def test_worker_persists_processed_observation_across_restart(tmp_path):
    from agent import DevAgent
    from core.gateway import DevAgentGateway
    from core.observation import Observation
    from core.observation_store import ObservationStore
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

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

    observation = Observation(
        instruction=(
            "crie restart_test.py contendo "
            "def test_restart(): assert 2 + 2 == 4"
        ),
        metadata={"source": "restart"},
    )

    observer = Observer(store=observation_store)
    observer.add(observation)

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)

    worker = Worker(
        gateway,
        observer,
        store=worker_state_store,
    )

    first = worker.run_once()

    assert len(first) == 1
    assert first[0].status == "pending"

    restarted_observer = Observer(store=observation_store)
    restarted_worker = Worker(
        gateway,
        restarted_observer,
        store=worker_state_store,
    )

    second = restarted_worker.run_once()

    assert second == []
    assert len(restarted_worker.processed_ids) == 1
    assert first[0].approval_id in restarted_worker.processed_ids

def test_worker_processes_new_observation_after_restart(tmp_path):
    from agent import DevAgent
    from core.gateway import DevAgentGateway
    from core.observation import Observation
    from core.observation_store import ObservationStore
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

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

    observer = Observer(store=observation_store)
    observer.add(
        Observation(
            instruction=(
                "crie first.py contendo "
                "def test_first(): assert 1 == 1"
            ),
            metadata={"source": "restart"},
        )
    )

    agent = DevAgent(tmp_path)
    gateway = DevAgentGateway(agent, tmp_path)

    worker = Worker(
        gateway,
        observer,
        store=worker_state_store,
    )

    first = worker.run_once()

    assert len(first) == 1

    restarted_observer = Observer(store=observation_store)
    restarted_observer.add(
        Observation(
            instruction=(
                "crie second.py contendo "
                "def test_second(): assert 2 == 2"
            ),
            metadata={"source": "restart-new"},
        )
    )

    restarted_worker = Worker(
        gateway,
        restarted_observer,
        store=worker_state_store,
    )

    second = restarted_worker.run_once()

    assert len(second) == 1
    assert second[0].status == "pending"
    assert second[0].approval_id != first[0].approval_id
    assert len(restarted_worker.processed_ids) == 2


def test_observer_refreshes_from_store_on_each_observe(tmp_path):
    from core.observation_store import ObservationStore

    store = ObservationStore(tmp_path / "observations.json")

    first = Observation("primeira", {"source": "test"})
    second = Observation("segunda", {"source": "test"})

    store.save([first])

    observer = Observer(store=store)

    assert observer.observe() == [first]

    store.append(second)

    assert observer.observe() == [first, second]
def test_observer_add_if_absent_rejects_missing_transaction_id_without_store():
    observation = Observation(
        instruction="resultado",
        metadata={"source": "transaction_result"},
    )

    observer = Observer()

    with pytest.raises(ValueError, match="transaction_id"):
        observer.add_if_absent(observation)


def test_observer_add_if_absent_rejects_non_transaction_result_without_store():
    observation = Observation(
        instruction="resultado",
        metadata={"source": "other"},
    )

    observer = Observer()

    with pytest.raises(ValueError, match="resultado de transação"):
        observer.add_if_absent(observation)
