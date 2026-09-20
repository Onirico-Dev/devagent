import json

import pytest

from core.supervised_loop import SupervisedLoop


class FakeWorker:
    def __init__(self, proposals=None):
        self.proposals = list(proposals or [])
        self.calls = 0

    def run_once(self):
        self.calls += 1
        proposals = self.proposals
        self.proposals = []
        return proposals


class FakeGateway:
    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])
        self.created = []

    def list_tasks(self):
        return list(self.tasks)

    def create_task(self, instruction):
        self.created.append(instruction)
        task = {
            "approval_id": str(len(self.created)),
            "instruction": instruction,
            "status": "pending",
        }
        self.tasks.append(task)
        return task


def test_new_observation_creates_pending_proposal():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo_a.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0]["instruction"] == "crie arquivo_a.txt"
    assert result.proposals[0]["approval_id"] == "1"
    assert result.metadata["proposal_count"] == 1


def test_second_round_does_not_duplicate_existing_pending_proposal():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo_a.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    first = loop.run_once()
    second = loop.run_once()

    assert len(first.proposals) == 1
    assert second.proposals == []


def test_pending_state_is_reported_without_crossing_approval_barrier():
    worker = FakeWorker()
    gateway = FakeGateway(
        [
            {
                "approval_id": "10",
                "instruction": "crie arquivo.txt",
                "status": "pending",
            }
        ]
    )

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert result.proposals == []
    assert result.metadata["pending_count"] == 1


@pytest.mark.parametrize(
    "status",
    ["committed", "rejected", "rolled_back", "failed"],
)
def test_terminal_task_does_not_become_new_execution(status):
    worker = FakeWorker()
    gateway = FakeGateway(
        [
            {
                "approval_id": "10",
                "instruction": "crie arquivo.txt",
                "status": status,
            }
        ]
    )

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert result.proposals == []
    assert result.metadata["pending_count"] == 0


def test_stop_prevents_future_rounds():
    worker = FakeWorker(
        [
            {
                "instruction": "crie arquivo.txt",
                "approval_id": "1",
                "status": "pending",
                "plan": {},
            }
        ]
    )
    gateway = FakeGateway()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    loop.stop()
    result = loop.run_once()

    assert result.stopped is True
    assert result.proposals == []
    assert worker.calls == 0


def test_invalid_worker_is_rejected():
    with pytest.raises(ValueError, match="Worker inválido"):
        SupervisedLoop(worker=object(), gateway=FakeGateway())


def test_invalid_gateway_is_rejected():
    with pytest.raises(ValueError, match="Gateway inválido"):
        SupervisedLoop(worker=FakeWorker(), gateway=object())


def test_export_state_contains_loop_state():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    state = loop.export_state()

    assert isinstance(state, dict)
    assert state["stopped"] is False
    assert state["iterations"] == 0


def test_restore_state_validates_mapping():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ValueError, match="Estado inválido"):
        loop.restore_state([])


def test_restore_state_restores_iterations_and_stop():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    loop.restore_state(
        {
            "stopped": True,
            "iterations": 4,
        }
    )

    assert loop.stopped is True
    assert loop.iterations == 4


def test_supervised_loop_preserves_external_approval_barrier():
    class WorkerWithProposal:
        def __init__(self):
            self.calls = 0

        def run_once(self):
            self.calls += 1
            return [
                {
                    "instruction": "crie arquivo.txt",
                    "approval_id": "42",
                    "status": "pending",
                    "plan": {},
                }
            ]

    class GatewayWithApprovalGuard:
        def __init__(self):
            self.approve_called = False

        def list_tasks(self):
            return [
                {
                    "approval_id": "42",
                    "instruction": "crie arquivo.txt",
                    "status": "pending",
                }
            ]

        def approve(self, approval_id):
            self.approve_called = True
            raise AssertionError(
                "SupervisedLoop não deve aprovar automaticamente."
            )

    worker = WorkerWithProposal()
    gateway = GatewayWithApprovalGuard()

    loop = SupervisedLoop(worker=worker, gateway=gateway)

    result = loop.run_once()

    assert len(result.proposals) == 1
    assert result.proposals[0]["approval_id"] == "42"
    assert gateway.approve_called is False


def test_supervised_loop_does_not_execute_pending_task():
    class WorkerWithProposal:
        def run_once(self):
            return [
                {
                    "instruction": "crie arquivo.txt",
                    "approval_id": "43",
                    "status": "pending",
                    "plan": {},
                }
            ]

    class Gateway:
        def list_tasks(self):
            return [
                {
                    "approval_id": "43",
                    "instruction": "crie arquivo.txt",
                    "status": "pending",
                }
            ]

        def approve(self, approval_id):
            raise AssertionError("aprovação automática proibida")

        def execute_approved(self, approval_id):
            raise AssertionError("execução automática proibida")

    loop = SupervisedLoop(
        worker=WorkerWithProposal(),
        gateway=Gateway(),
    )

    result = loop.run_once()

    assert result.metadata["pending_count"] == 1


def test_supervised_loop_can_observe_after_external_decision():
    class Worker:
        def __init__(self):
            self.round = 0

        def run_once(self):
            self.round += 1
            if self.round == 1:
                return [
                    {
                        "instruction": "crie arquivo.txt",
                        "approval_id": "44",
                        "status": "pending",
                        "plan": {},
                    }
                ]
            return []

    class Gateway:
        def __init__(self):
            self.status = "pending"

        def list_tasks(self):
            return [
                {
                    "approval_id": "44",
                    "instruction": "crie arquivo.txt",
                    "status": self.status,
                }
            ]

    worker = Worker()
    gateway = Gateway()
    loop = SupervisedLoop(worker=worker, gateway=gateway)

    first = loop.run_once()

    assert len(first.proposals) == 1
    assert first.metadata["pending_count"] == 1

    gateway.status = "committed"

    second = loop.run_once()

    assert second.proposals == []
    assert second.metadata["pending_count"] == 0
    assert loop.iterations == 2

def test_supervised_loop_persists_iterations(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "supervised_loop.json")

    first = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    result = first.run_once()

    assert result.metadata["iterations"] == 1
    assert store.load()["iterations"] == 1


def test_supervised_loop_restores_state_across_instances(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "supervised_loop.json")

    first = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    first.run_once()
    first.run_once()

    second = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    assert second.iterations == 2
    assert second.stopped is False


def test_supervised_loop_persists_stop_state(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "supervised_loop.json")

    first = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    first.stop()

    second = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    assert second.stopped is True
    assert second.run_once().stopped is True


def test_supervised_loop_accepts_missing_state_store(tmp_path):
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    assert loop.iterations == 0
    assert loop.stopped is False

def test_supervised_loop_rejects_state_store_without_load():
    class InvalidStore:
        def save(self, state):
            pass

    with pytest.raises(ValueError, match="Armazenamento de estado inválido"):
        SupervisedLoop(
            worker=FakeWorker(),
            gateway=FakeGateway(),
            state_store=InvalidStore(),
        )


def test_supervised_loop_rejects_state_store_without_save():
    class InvalidStore:
        def load(self):
            return {}

    with pytest.raises(ValueError, match="Armazenamento de estado inválido"):
        SupervisedLoop(
            worker=FakeWorker(),
            gateway=FakeGateway(),
            state_store=InvalidStore(),
        )


@pytest.mark.parametrize("value", [0, -1])
def test_supervised_loop_rejects_non_positive_iterations(value):
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ValueError, match="max_iterations deve ser um inteiro positivo"):
        loop.run(value)


@pytest.mark.parametrize("value", [True, False, 1.0, "3", None])
def test_supervised_loop_rejects_invalid_iteration_type(value):
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ValueError, match="max_iterations deve ser um inteiro positivo"):
        loop.run(value)


def test_supervised_loop_run_stops_when_loop_is_stopped():
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    loop.stop()

    assert loop.run(3) == []


@pytest.mark.parametrize(
    "state",
    [
        {"stopped": "true", "iterations": 0},
        {"stopped": False, "iterations": True},
        {"stopped": False, "iterations": -1},
    ],
)
def test_supervised_loop_rejects_invalid_state_values(state):
    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ValueError, match="Estado inválido"):
        loop.restore_state(state)

def test_supervised_loop_run_breaks_when_stopped_during_iteration():
    loop = None

    class StoppingWorker:
        def run_once(self):
            loop.stop()
            return []

    loop = SupervisedLoop(
        worker=StoppingWorker(),
        gateway=FakeGateway(),
    )

    results = loop.run(3)

    assert len(results) == 1
    assert results[0].stopped is False
    assert loop.stopped is True
    assert loop.iterations == 1


def test_supervised_loop_auto_approves_explicit_autonomous_proposal():
    class Worker:
        def run_once(self):
            return [
                {
                    "instruction": "crie arquivo.txt",
                    "approval_id": "44",
                    "status": "pending",
                    "plan": {},
                    "autonomy_decision": "auto_approve",
                }
            ]

    class Gateway:
        def __init__(self):
            self.approved = []

        def list_tasks(self):
            return []

        def approve(self, approval_id):
            self.approved.append(approval_id)
            return {
                "approval_id": approval_id,
                "status": "committed",
            }

    gateway = Gateway()
    loop = SupervisedLoop(worker=Worker(), gateway=gateway)

    result = loop.run_once()

    assert gateway.approved == ["44"]
    assert result.proposals[0]["approval_id"] == "44"
    assert result.metadata["auto_approved_count"] == 1


def test_supervised_loop_keeps_human_proposal_pending():
    class Worker:
        def run_once(self):
            return [
                {
                    "instruction": "apague arquivo.txt",
                    "approval_id": "45",
                    "status": "pending",
                    "plan": {},
                    "autonomy_decision": "require_human",
                }
            ]

    class Gateway:
        def __init__(self):
            self.approved = []

        def list_tasks(self):
            return [
                {
                    "approval_id": "45",
                    "status": "pending",
                }
            ]

        def approve(self, approval_id):
            self.approved.append(approval_id)

    gateway = Gateway()
    loop = SupervisedLoop(worker=Worker(), gateway=gateway)

    result = loop.run_once()

    assert gateway.approved == []
    assert result.metadata["auto_approved_count"] == 0
    assert result.metadata["pending_count"] == 1


def test_supervised_loop_auto_approves_real_worker_proposal():
    from core.worker import Proposal

    class Worker:
        def run_once(self):
            return [
                Proposal(
                    instruction="crie arquivo.txt",
                    approval_id="46",
                    status="pending",
                    plan={},
                    autonomy_decision="auto_approve",
                )
            ]

    class Gateway:
        def __init__(self):
            self.approved = []

        def list_tasks(self):
            return []

        def approve(self, approval_id):
            self.approved.append(approval_id)
            return {"approval_id": approval_id, "status": "committed"}

    gateway = Gateway()
    loop = SupervisedLoop(worker=Worker(), gateway=gateway)

    result = loop.run_once()

    assert gateway.approved == ["46"]
    assert result.metadata["auto_approved_count"] == 1


def test_supervised_loop_persists_start_state(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "supervised_loop.json")

    first = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    first.stop()
    assert store.load()["stopped"] is True

    first.start()

    assert first.stopped is False
    assert store.load()["stopped"] is False


def test_supervised_loop_start_allows_future_round(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "supervised_loop.json")

    loop = SupervisedLoop(
        worker=FakeWorker(),
        gateway=FakeGateway(),
        state_store=store,
    )

    loop.stop()
    stopped = loop.run_once()

    assert stopped.stopped is True
    assert loop.iterations == 0

    loop.start()
    result = loop.run_once()

    assert result.stopped is False
    assert loop.iterations == 1


def test_supervised_loop_detects_observation_added_after_creation(tmp_path):
    from core.observation import Observation
    from core.observation_store import ObservationStore
    from core.observer import Observer
    from core.supervised_loop import SupervisedLoop
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    store = ObservationStore(tmp_path / "observations.json")
    store.save([])

    observer = Observer(store=store)

    class RecordingGateway(FakeGateway):
        def __init__(self):
            super().__init__()
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

    gateway = RecordingGateway()
    worker = Worker(
        gateway,
        observer,
        store=WorkerStateStore(tmp_path / "worker.json"),
    )

    loop = SupervisedLoop(worker, gateway)

    first = loop.run_once()

    assert first.proposals == []
    assert gateway.calls == []

    store.append(
        Observation(
            "nova tarefa",
            {"source": "external"},
        )
    )

    second = loop.run_once()

    assert len(second.proposals) == 1
    assert second.proposals[0].instruction == "nova tarefa"
    assert gateway.calls == ["nova tarefa"]
