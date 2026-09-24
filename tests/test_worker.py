import pytest
from core.observation import Observation
from core.observer import Observer
from core.worker import Worker
from core.observation import Observation
from core.observer import Observer

def _run_worker_with_shared_state(path, instruction):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, value):
            return {
                "approval_id": value,
                "status": "pending",
                "plan": {},
            }

    worker = Worker(
        Gateway(),
        Observer([Observation(instruction, {})]),
        store=WorkerStateStore(path),
    )
    worker.run_once()


def test_workers_concurrent_processing_preserves_both_states(tmp_path):
    import multiprocessing

    path = tmp_path / "worker.json"
    ctx = multiprocessing.get_context("fork")

    processes = [
        ctx.Process(
            target=_run_worker_with_shared_state,
            args=(path, instruction),
        )
        for instruction in ("primeira", "segunda")
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    from core.worker_state_store import WorkerStateStore

    state = WorkerStateStore(path).load()

    instructions = {
        item["instruction"]
        for item in state["processed"]
    }

    assert instructions == {"primeira", "segunda"}

def test_find_pending_proposal_skips_invalid_pending_tasks():
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def list_pending(self):
            return [
                "invalido",
                {"instruction": 123},
                {"instruction": "outra instrução", "approval_id": "1", "plan": {}},
                {"instruction": "teste", "approval_id": "", "plan": {}},
                {"instruction": "teste", "approval_id": "2", "plan": "invalido"},
                {
                    "instruction": "teste",
                    "approval_id": "3",
                    "plan": {"change_type": "create"},
                    "status": "pending",
                },
            ]

    worker = Worker(Gateway(), Observer([]))

    proposal = worker._find_pending_proposal("  teste  ")

    assert proposal is not None
    assert proposal.approval_id == "3"
    assert proposal.instruction == "teste"


def test_find_pending_proposal_accepts_task_id_fallback():
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        def list_pending(self):
            return [
                {
                    "instruction": "teste",
                    "task_id": "task-1",
                    "plan": {},
                }
            ]

    worker = Worker(Gateway(), Observer([]))

    proposal = worker._find_pending_proposal("teste")

    assert proposal is not None
    assert proposal.approval_id == "task-1"


def test_find_pending_proposal_returns_none_without_list_pending():
    from core.worker import Worker
    from core.observer import Observer

    class Gateway:
        pass

    worker = Worker(Gateway(), Observer([]))

    assert worker._find_pending_proposal("teste") is None

def test_process_observation_rolls_back_reused_pending_on_persist_failure(monkeypatch):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_pending(self):
            return [{
                "instruction": "teste",
                "approval_id": "approval-1",
                "plan": {},
                "status": "pending",
            }]

    worker = Worker(Gateway(), Observer([]))
    observation = Observation("teste", {})

    def fail_persist():
        raise RuntimeError("persist failed")

    monkeypatch.setattr(worker, "_persist_state", fail_persist)

    with pytest.raises(RuntimeError, match="persist failed"):
        worker.process_observation(observation)

    assert worker.processed_ids == set()
    assert worker._processed == set()
    assert worker._processed_observations == {}


def test_process_observation_rolls_back_created_proposal_on_persist_failure(monkeypatch):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_pending(self):
            return []

        def create_task(self, instruction):
            return {
                "approval_id": "approval-2",
                "status": "pending",
                "plan": {},
            }

    worker = Worker(Gateway(), Observer([]))
    observation = Observation("nova tarefa", {})

    def fail_persist():
        raise RuntimeError("persist failed")

    monkeypatch.setattr(worker, "_persist_state", fail_persist)

    with pytest.raises(RuntimeError, match="persist failed"):
        worker.process_observation(observation)

    assert worker.processed_ids == set()
    assert worker._processed == set()
    assert worker._processed_observations == {}


def test_process_observation_reuses_pending_proposal():
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_pending(self):
            return [{
                "instruction": "teste",
                "approval_id": "approval-1",
                "plan": {},
                "status": "pending",
            }]

    worker = Worker(Gateway(), Observer([]))
    observation = Observation("teste", {})

    proposal = worker.process_observation(observation)

    assert proposal.approval_id == "approval-1"
    assert proposal.status == "pending"
    assert proposal.instruction == "teste"


def test_worker_proposal_exposes_autonomy_decision(monkeypatch, tmp_path):
    from core.autonomy_policy import AutonomyDecision, AutonomyPolicy
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {
                    "objective": instruction,
                    "changes": [
                        {
                            "change_type": "create",
                            "path": "example.py",
                            "content": "print('ok')",
                            "reason": instruction,
                        }
                    ],
                    "tests": [],
                    "risks": [],
                },
            }

    worker = Worker(
        Gateway(),
        Observer(
            [
                Observation(
                    instruction="criar example.py",
                    metadata={},
                )
            ]
        ),
        autonomy_policy=AutonomyPolicy(),
    )

    proposal = worker.run_once()[0]

    assert (
        proposal.autonomy_decision
        == AutonomyDecision.AUTO_APPROVE.value
    )


def test_worker_marks_destructive_proposal_as_human_required():
    from core.autonomy_policy import AutonomyDecision, AutonomyPolicy
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-2",
                "status": "pending",
                "plan": {
                    "objective": instruction,
                    "changes": [
                        {
                            "change_type": "delete",
                            "path": "example.py",
                            "content": None,
                            "reason": instruction,
                        }
                    ],
                    "tests": [],
                    "risks": ["Operação destrutiva"],
                },
            }

    worker = Worker(
        Gateway(),
        Observer(
            [
                Observation(
                    instruction="apagar example.py",
                    metadata={},
                )
            ]
        ),
        autonomy_policy=AutonomyPolicy(),
    )

    proposal = worker.run_once()[0]

    assert (
        proposal.autonomy_decision
        == AutonomyDecision.REQUIRE_HUMAN.value
    )


def _run_workers_same_observation(path, calls_queue):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, instruction):
            calls_queue.put(instruction)
            return {
                "approval_id": instruction,
                "status": "pending",
                "plan": {},
            }

    worker = Worker(
        Gateway(),
        Observer([Observation("mesma-observacao", {})]),
        store=WorkerStateStore(path),
    )
    worker.run_once()


def test_workers_concurrent_same_observation_are_not_processed_twice(
    tmp_path,
):
    import multiprocessing

    path = tmp_path / "worker.json"
    ctx = multiprocessing.get_context("fork")
    calls_queue = ctx.Queue()

    processes = [
        ctx.Process(
            target=_run_workers_same_observation,
            args=(path, calls_queue),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=10)

    assert all(process.exitcode == 0 for process in processes)

    calls = []
    while not calls_queue.empty():
        calls.append(calls_queue.get())

    assert calls == ["mesma-observacao"]


def test_worker_persist_state_merges_existing_state(tmp_path):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    first = Worker(
        Gateway := type(
            "Gateway",
            (),
            {
                "create_task": lambda self, instruction: {
                    "approval_id": f"id-{instruction}",
                    "status": "pending",
                    "plan": {},
                },
            },
        )(),
        Observer([]),
        store=store,
    )

    first._processed_observations[
        first._observation_key(Observation("primeira", {"source": "a"}))
    ] = Observation("primeira", {"source": "a"})
    first._processed_ids.add("id-primeira")
    first._persist_state()

    second = Worker(
        Gateway,
        Observer([]),
        store=store,
    )
    second._processed_observations[
        second._observation_key(Observation("segunda", {"source": "b"}))
    ] = Observation("segunda", {"source": "b"})
    second._processed_ids.add("id-segunda")
    second._persist_state()

    state = store.load()

    assert {
        item["instruction"]
        for item in state["processed"]
    } == {"primeira", "segunda"}
    assert state["processed_ids"] == [
        "id-primeira",
        "id-segunda",
    ]


def test_worker_persist_state_does_not_duplicate_existing_observation(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    worker = Worker(
        object(),
        Observer([]),
        store=store,
    )

    observation = Observation("mesma", {"source": "test"})
    key = worker._observation_key(observation)
    worker._processed_observations[key] = observation
    worker._processed_ids.add("approval-1")
    worker._persist_state()

    worker._processed_ids.add("approval-2")
    worker._persist_state()

    state = store.load()

    assert state["processed"] == [
        {
            "instruction": "mesma",
            "metadata": {"source": "test"},
        }
    ]
    assert state["processed_ids"] == [
        "approval-1",
        "approval-2",
    ]


def test_process_observation_with_store_reuses_pending_proposal(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def __init__(self):
            self.create_calls = 0

        def list_pending(self):
            return [
                {
                    "instruction": "teste",
                    "approval_id": "approval-pendente",
                    "status": "pending",
                    "plan": {},
                }
            ]

        def create_task(self, instruction):
            self.create_calls += 1
            raise AssertionError("não deveria criar uma nova tarefa")

    gateway = Gateway()
    worker = Worker(
        gateway,
        Observer([]),
        store=WorkerStateStore(tmp_path / "worker.json"),
    )

    proposal = worker.process_observation(
        Observation("teste", {})
    )

    assert proposal.approval_id == "approval-pendente"
    assert gateway.create_calls == 0
    assert worker.processed_ids == {"approval-pendente"}


def test_process_observation_rejects_shared_processed_observation(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-1",
                "status": "pending",
                "plan": {},
            }

    first = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(path),
    )
    observation = Observation("teste", {})
    first.process_observation(observation)

    second = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(path),
    )

    with pytest.raises(
        ValueError,
        match="Observação já processada.",
    ):
        second.process_observation(observation)


def test_process_observation_with_store_normalizes_autonomy_changes(
    tmp_path,
):
    from core.autonomy_policy import (
        AutonomyDecision,
        AutonomyPolicy,
    )
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-auto",
                "status": "pending",
                "plan": {
                    "changes": [
                        {
                            "type": "create",
                            "path": "example.py",
                            "content": "print('ok')",
                        }
                    ],
                    "tests": [],
                    "risks": [],
                },
            }

    worker = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(tmp_path / "worker.json"),
        autonomy_policy=AutonomyPolicy(),
    )

    proposal = worker.process_observation(
        Observation("criar example.py", {})
    )

    assert (
        proposal.autonomy_decision
        == AutonomyDecision.AUTO_APPROVE.value
    )


def test_restore_state_persists_when_requested(tmp_path):
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    worker = Worker(
        object(),
        Observer([]),
        store=store,
    )

    worker.restore_state(
        {
            "processed": [
                {
                    "instruction": "restaurada",
                    "metadata": {"source": "test"},
                }
            ],
            "processed_ids": ["approval-restaurada"],
        }
    )

    persisted = store.load()

    assert persisted == {
        "processed": [
            {
                "instruction": "restaurada",
                "metadata": {"source": "test"},
            }
        ],
        "processed_ids": ["approval-restaurada"],
    }


def test_process_observation_store_update_race_raises_duplicate(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-race",
                "status": "pending",
                "plan": {},
            }

    observation = Observation("teste", {})
    first = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(path),
    )
    first.process_observation(observation)

    second = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(path),
    )

    with pytest.raises(ValueError, match="Observação já processada."):
        second.process_observation(observation)


def test_process_observation_unlocked_normalizes_autonomy_changes():
    from core.autonomy_policy import (
        AutonomyDecision,
        AutonomyPolicy,
    )
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-auto",
                "status": "pending",
                "plan": {
                    "changes": [
                        {
                            "type": "create",
                            "path": "example.py",
                            "content": "print('ok')",
                        }
                    ],
                    "tests": [],
                    "risks": [],
                },
            }

    worker = Worker(
        Gateway(),
        Observer([]),
        autonomy_policy=AutonomyPolicy(),
    )

    proposal = worker.process_observation(
        Observation("criar example.py", {})
    )

    assert (
        proposal.autonomy_decision
        == AutonomyDecision.AUTO_APPROVE.value
    )


def test_process_observation_store_atomic_process_detects_existing_key(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    observation = Observation("existente", {"source": "test"})

    store.save(
        {
            "processed": [
                {
                    "instruction": "existente",
                    "metadata": {"source": "test"},
                }
            ],
            "processed_ids": ["approval-existing"],
        }
    )

    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("não deveria criar tarefa")

    worker = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    with pytest.raises(ValueError, match="Observação já processada."):
        worker.process_observation(observation)


def test_process_observation_detects_shared_state_added_after_worker_load(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("não deveria criar tarefa")

    worker = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    observation = Observation(
        "existente",
        {"source": "test"},
    )

    store.save(
        {
            "processed": [
                {
                    "instruction": "existente",
                    "metadata": {"source": "test"},
                }
            ],
            "processed_ids": ["approval-existing"],
        }
    )

    with pytest.raises(
        ValueError,
        match="Observação já processada.",
    ):
        worker.process_observation(observation)


def test_worker_routes_transaction_result_to_feedback_handler():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("Feedback não deve criar tarefa normal.")

    class FeedbackHandler:
        def __init__(self):
            self.received = []

        def handle(self, observation):
            self.received.append(observation)
            return {"handled": True}

    observer = Observer(
        observations=[
            Observation(
                instruction="Avaliar resultado da transação.",
                metadata={
                    "source": "transaction_result",
                    "transaction_id": "tx-1",
                    "status": "committed",
                },
            )
        ]
    )
    handler = FeedbackHandler()

    worker = Worker(
        Gateway(),
        observer,
        feedback_handler=handler,
    )

    proposals = worker.run_once()

    assert proposals == []
    assert len(handler.received) == 1
    assert handler.received[0].metadata["transaction_id"] == "tx-1"
    assert worker.errors == []


def test_worker_marks_handled_transaction_result_as_processed():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("Feedback não deve criar tarefa normal.")

    class FeedbackHandler:
        def handle(self, observation):
            return {"handled": True}

    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-2",
            "status": "rolled_back",
        },
    )

    observer = Observer(observations=[observation])

    worker = Worker(
        Gateway(),
        observer,
        feedback_handler=FeedbackHandler(),
    )

    worker.run_once()

    assert len(worker.processed_ids) == 0
    assert worker._observation_key(observation) in worker._processed
    assert worker.errors == []


def test_worker_allows_retry_after_failed_transaction():
    class Gateway:
        def __init__(self):
            self.instructions = []

        def create_task(self, instruction):
            self.instructions.append(instruction)
            return {
                "approval_id": f"approval-{len(self.instructions)}",
                "status": "pending",
                "plan": {
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": [],
                },
            }

        def list_pending(self):
            return []

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "analysis": {
                    "transaction_id": observation.metadata["transaction_id"],
                    "status": "rolled_back",
                    "action_required": True,
                    "failure_type": "syntax_error",
                    "repair_attempts": 2,
                    "evidence": {
                        "transaction_metadata": {
                            "instruction": instruction,
                        }
                    },
                },
                "proposal": {
                    "instruction": (
                        "Analise a transação tx-1, que terminou com status "
                        "'rolled_back', identifique a causa da falha e proponha "
                        "uma correção segura."
                    ),
                },
            }

    instruction = (
        "modifique self_evolution_smoke.py "
        "para adicionar goodbye()"
    )

    original = Observation(
        instruction=instruction,
        metadata={"source": "cli"},
    )

    feedback = Observation(
        instruction="resultado da transação tx-1",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-1",
            "status": "rolled_back",
            "transaction_metadata": {
                "instruction": instruction,
            },
        },
    )

    retry = Observation(
        instruction=instruction,
        metadata={"source": "cli"},
    )

    gateway = Gateway()
    observer = Observer(observations=[original, feedback, retry])

    worker = Worker(
        gateway,
        observer,
        feedback_handler=FeedbackHandler(),
    )

    proposals = worker.run_once()

    feedback_instruction = (
        "Analise a transação tx-1, que terminou com status "
        "'rolled_back', identifique a causa da falha e proponha "
        "uma correção segura."
    )

    assert gateway.instructions == [
        instruction,
        feedback_instruction,
        instruction,
    ]
    assert len(proposals) == 3
    assert worker.errors == []



def test_worker_keeps_feedback_unprocessed_when_handler_fails():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("Feedback não deve criar tarefa normal.")

    class FeedbackHandler:
        def handle(self, observation):
            raise RuntimeError("falha no feedback")

    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-3",
            "status": "failed",
        },
    )

    observer = Observer(observations=[observation])

    worker = Worker(
        Gateway(),
        observer,
        feedback_handler=FeedbackHandler(),
    )

    worker.run_once()

    assert worker._observation_key(observation) not in worker._processed
    assert len(worker.errors) == 1
    assert worker.errors[0]["error"] == "falha no feedback"

def test_transaction_feedback_persists_across_worker_restart(tmp_path):
    from core.feedback_handler import FeedbackHandler
    from core.observation import Observation
    from core.observation_store import ObservationStore
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    observation_path = tmp_path / "observations.json"
    worker_state_path = tmp_path / "worker.json"

    observation = Observation(
        instruction="Avaliar resultado da transação.",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-persist-1",
            "status": "committed",
        },
    )

    ObservationStore(observation_path).append(observation)

    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("Feedback não deve criar tarefa normal.")

    class RecordingHandler(FeedbackHandler):
        received = 0

        def handle(self, observation):
            type(self).received += 1
            return {"handled": True}

    handler = RecordingHandler()

    worker = Worker(
        Gateway(),
        Observer(store=ObservationStore(observation_path)),
        store=WorkerStateStore(worker_state_path),
        feedback_handler=handler,
    )

    assert worker.run_once() == []
    assert RecordingHandler.received == 1

    restarted = Worker(
        Gateway(),
        Observer(store=ObservationStore(observation_path)),
        store=WorkerStateStore(worker_state_path),
        feedback_handler=handler,
    )

    assert restarted.run_once() == []
    assert RecordingHandler.received == 1
    assert restarted._observation_key(observation) in restarted._processed


def test_worker_creates_proposal_from_failed_transaction_feedback():
    class Gateway:
        def __init__(self):
            self.created = []

        def create_task(self, instruction, context=None):
            self.created.append((instruction, context))
            return {
                "approval_id": "approval-correction-1",
                "status": "pending",
                "plan": {
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": [],
                },
            }

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "analysis": {
                    "transaction_id": "tx-failed-1",
                    "status": "failed",
                    "action_required": True,
                    "repair_attempts": 2,
                    "evidence": {
                        "error": "TEST_FAILURE",
                        "transaction_metadata": {
                            "instruction": "criar app.py",
                            "objective": "Criar app.py",
                            "changes": [
                                {
                                    "type": "create",
                                    "path": "app.py",
                                    "content": "print('quebrado')",
                                }
                            ],
                            "tests": ["tests/test_app.py"],
                            "risks": [],
                        },
                    },
                },
                "proposal": {
                    "instruction": "corrigir falha da transação tx-failed-1",
                    "transaction_id": "tx-failed-1",
                    "status": "failed",
                    "repair_attempts": 2,
                    "evidence": {
                        "error": "TEST_FAILURE",
                        "transaction_metadata": {
                            "instruction": "criar app.py",
                            "objective": "Criar app.py",
                            "changes": [
                                {
                                    "type": "create",
                                    "path": "app.py",
                                    "content": "print('quebrado')",
                                }
                            ],
                            "tests": ["tests/test_app.py"],
                            "risks": [],
                        },
                    },
                    "transaction_metadata": {
                        "instruction": "criar app.py",
                        "objective": "Criar app.py",
                        "changes": [
                            {
                                "type": "create",
                                "path": "app.py",
                                "content": "print('quebrado')",
                            }
                        ],
                        "tests": ["tests/test_app.py"],
                        "risks": [],
                    },
                },
            }

    observer = Observer(
        observations=[
            Observation(
                instruction="Avaliar resultado da transação.",
                metadata={
                    "source": "transaction_result",
                    "transaction_id": "tx-failed-1",
                    "status": "failed",
                },
            )
        ]
    )

    gateway = Gateway()
    worker = Worker(
        gateway,
        observer,
        feedback_handler=FeedbackHandler(),
    )

    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].approval_id == "approval-correction-1"
    assert len(gateway.created) == 1

    instruction, context = gateway.created[0]

    assert instruction == "corrigir falha da transação tx-failed-1"
    assert context["transaction_id"] == "tx-failed-1"
    assert context["status"] == "failed"
    assert context["repair_attempts"] == 2
    assert context["transaction_metadata"]["changes"][0]["path"] == "app.py"
    assert context["transaction_metadata"]["changes"][0]["content"] == "print('quebrado')"
    assert context["transaction_metadata"]["tests"] == ["tests/test_app.py"]
    assert worker.errors == []


def test_worker_does_not_create_proposal_for_committed_feedback():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError(
                "Feedback committed não deve criar correção."
            )

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "analysis": {
                    "transaction_id": "tx-ok-1",
                    "status": "committed",
                    "action_required": False,
                    "repair_attempts": 0,
                    "evidence": {},
                },
                "proposal": None,
            }

    worker = Worker(
        Gateway(),
        Observer(
            observations=[
                Observation(
                    instruction="Avaliar resultado da transação.",
                    metadata={
                        "source": "transaction_result",
                        "transaction_id": "tx-ok-1",
                        "status": "committed",
                    },
                )
            ]
        ),
        feedback_handler=FeedbackHandler(),
    )

    assert worker.run_once() == []
    assert worker.errors == []


def test_worker_reuses_existing_pending_feedback_proposal():
    class Gateway:
        def __init__(self):
            self.created = 0

        def list_pending(self):
            return [
                {
                    "approval_id": "approval-existing",
                    "status": "pending",
                    "instruction": "corrigir falha existente",
                    "plan": {
                        "objective": "corrigir falha existente",
                        "changes": [],
                        "tests": [],
                        "risks": [],
                    },
                }
            ]

        def create_task(self, instruction):
            self.created += 1
            raise AssertionError("Não deve criar proposta duplicada.")

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "analysis": {
                    "transaction_id": "tx-duplicate",
                    "status": "failed",
                    "action_required": True,
                    "repair_attempts": 1,
                    "evidence": {},
                },
                "proposal": {
                    "instruction": "corrigir falha existente",
                    "transaction_id": "tx-duplicate",
                },
            }

    worker = Worker(
        Gateway(),
        Observer(
            observations=[
                Observation(
                    instruction="Avaliar resultado da transação.",
                    metadata={
                        "source": "transaction_result",
                        "transaction_id": "tx-duplicate",
                        "status": "failed",
                    },
                )
            ]
        ),
        feedback_handler=FeedbackHandler(),
    )

    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].approval_id == "approval-existing"
    assert worker.errors == []


def test_retry_instructions_persist_across_worker_restart(tmp_path):
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-retry",
                "status": "pending",
                "plan": {},
            }

    instruction = "corrigir arquivo após falha"

    store = WorkerStateStore(tmp_path / "worker.json")

    worker = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    worker._retry_instructions.add(instruction)
    worker._persist_state()

    restarted = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    assert instruction in restarted._retry_instructions
