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


def test_worker_create_feedback_task_signature_introspection_failure(monkeypatch):
    import inspect
    from core.worker import Worker

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-signature-fallback",
                "status": "pending",
                "plan": {},
            }

    original = inspect.signature

    def broken_signature(_):
        raise TypeError("signature indisponível")

    monkeypatch.setattr(inspect, "signature", broken_signature)

    worker = Worker(Gateway(), Observer([]))

    result = worker._create_feedback_task("corrigir falha", {"transaction_id": "tx-1"})

    assert result["approval_id"] == "approval-signature-fallback"

    monkeypatch.setattr(inspect, "signature", original)


def test_worker_rejects_invalid_feedback_proposal():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("não deveria criar tarefa")

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "proposal": "proposta inválida",
            }

    observation = Observation(
        instruction="resultado",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-invalid-proposal",
            "status": "failed",
        },
    )

    worker = Worker(
        Gateway(),
        Observer([observation]),
        feedback_handler=FeedbackHandler(),
    )

    worker.run_once()

    assert len(worker.errors) == 1
    assert "Proposta de feedback inválida." in worker.errors[0]["error"]


def test_worker_rejects_feedback_proposal_without_instruction():
    class Gateway:
        def create_task(self, instruction):
            raise AssertionError("não deveria criar tarefa")

    class FeedbackHandler:
        def handle(self, observation):
            return {
                "handled": True,
                "proposal": {},
            }

    observation = Observation(
        instruction="resultado",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-missing-instruction",
            "status": "failed",
        },
    )

    worker = Worker(
        Gateway(),
        Observer([observation]),
        feedback_handler=FeedbackHandler(),
    )

    worker.run_once()

    assert len(worker.errors) == 1
    assert "Proposta de feedback sem instrução." in worker.errors[0]["error"]



@pytest.mark.parametrize(
    ("state", "message"),
    [
        (None, "Estado do Worker inválido."),
        ({"processed": {}}, "Estado de observações processadas inválido."),
        ({"processed": [], "processed_ids": {}}, "Estado de IDs processados inválido."),
        (
            {
                "processed": [],
                "processed_ids": [],
                "retry_instructions": "inválido",
            },
            "Estado de instruções de retry inválido.",
        ),
        (
            {
                "processed": ["inválido"],
                "processed_ids": [],
            },
            "Registro de estado inválido.",
        ),
        (
            {
                "processed": [{"instruction": "", "metadata": {}}],
                "processed_ids": [],
            },
            "Instrução processada inválida.",
        ),
        (
            {
                "processed": [{"instruction": "ok", "metadata": []}],
                "processed_ids": [],
            },
            "Metadados processados inválidos.",
        ),
        (
            {
                "processed": [],
                "processed_ids": [123],
            },
            "ID processado inválido.",
        ),
    ],
)

def test_worker_restore_state_rejects_invalid_state(state, message):
    class Gateway:
        pass

    worker = Worker(Gateway(), Observer([]))

    with pytest.raises(ValueError, match=message):
        worker.restore_state(state)


@pytest.mark.parametrize(
    "gateway",
    [None],
)
def test_worker_rejects_invalid_gateway(gateway):
    with pytest.raises(ValueError, match="Gateway inválido."):
        Worker(gateway, Observer([]))


def test_worker_rejects_invalid_observer():
    with pytest.raises(ValueError, match="Observer inválido."):
        Worker(object(), object())


def test_worker_rejects_invalid_store():
    with pytest.raises(ValueError, match="Store do Worker inválido."):
        Worker(object(), Observer([]), store=object())


@pytest.mark.parametrize(
    "observation",
    [None, "observação inválida", {}],
)
def test_worker_rejects_invalid_observation(observation):
    worker = Worker(object(), Observer([]))

    with pytest.raises(ValueError, match="Observação inválida."):
        worker.process_observation(observation)


def test_worker_rejects_empty_observation_instruction():
    worker = Worker(object(), Observer([]))

    observation = Observation(
        instruction="   ",
        metadata={},
    )

    with pytest.raises(
        ValueError,
        match="A instrução da observação não pode ser vazia.",
    ):
        worker.process_observation(observation)

def test_worker_rejects_invalid_retry_state(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "worker.json")

    store.save({
        "processed": [],
        "processed_ids": [],
        "retry_instructions": [123],
    })

    with pytest.raises(
        ValueError,
        match="Estado de instruções de retry inválido.",
    ):
        Worker(
            object(),
            Observer([]),
            store=store,
        )


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

def test_worker_does_not_retry_when_repair_cycle_is_exhausted():
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
                    "transaction_id": "tx-exhausted",
                    "status": "rolled_back",
                    "action_required": True,
                    "failure_type": "syntax_error",
                    "repair_attempts": 2,
                    "evidence": {
                        "transaction_metadata": {
                            "instruction": instruction,
                            "repair_cycle": {
                                "status": "repair_failed",
                                "attempts": 2,
                                "max_attempts": 2,
                                "remaining": 0,
                            },
                        },
                    },
                },
                "proposal": {
                    "instruction": (
                        "Analise a transação tx-exhausted, que terminou "
                        "com status 'rolled_back', identifique a causa "
                        "da falha e proponha uma correção segura."
                    ),
                },
            }

    instruction = "crie arquivo exhausted_smoke.py com conteúdo inválido"

    feedback = Observation(
        instruction="resultado da transação tx-exhausted",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-exhausted",
            "status": "rolled_back",
        },
    )

    worker = Worker(
        Gateway(),
        Observer(observations=[feedback]),
        feedback_handler=FeedbackHandler(),
    )

    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].status == "pending"
    assert instruction not in worker._retry_instructions

def test_worker_modify_existing_file_preserves_exhausted_retry_state():
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
                    "transaction_id": "tx-exhausted",
                    "status": "rolled_back",
                    "action_required": True,
                    "failure_type": "syntax_error",
                    "repair_attempts": 2,
                    "evidence": {
                        "transaction_metadata": {
                            "instruction": instruction,
                            "repair_cycle": {
                                "status": "repair_failed",
                                "attempts": 2,
                                "max_attempts": 2,
                                "remaining": 0,
                            },
                        },
                    },
                },
                "proposal": {
                    "instruction": "Analise a transação tx-exhausted, que terminou com status 'rolled_back', identifique a causa da falha e proponha uma correção segura.",
                },
            }

    instruction = "crie arquivo exhausted_smoke.py com conteúdo inválido"
    feedback = Observation(
        instruction="resultado da transação tx-exhausted",
        metadata={
            "source": "transaction_result",
            "transaction_id": "tx-exhausted",
            "status": "rolled_back",
        },
    )

    worker = Worker(
        Gateway(),
        Observer(observations=[feedback]),
        feedback_handler=FeedbackHandler(),
    )

    proposals = worker.run_once()

    assert len(proposals) == 1
    assert proposals[0].status == "pending"
    assert instruction not in worker._retry_instructions

def test_worker_allow_retry_removes_previous_processed_observation(tmp_path):
    from core.observation import Observation
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": "approval-retry",
                "status": "pending",
                "plan": {
                    "objective": instruction,
                    "changes": [],
                    "tests": [],
                    "risks": [],
                },
            }

    instruction = "reprocessar após falha"

    observation = Observation(
        instruction=instruction,
        metadata={"source": "transaction_result", "transaction_id": "tx-retry"},
    )

    worker = Worker(
        Gateway(),
        Observer([observation]),
        store=WorkerStateStore(
            tmp_path / "worker.json"
        ),
    )

    worker.process_observation(observation)

    assert worker._observation_key(observation) in worker._processed

    retry_observation = Observation(
        instruction=instruction,
        metadata={"source": "transaction_result", "transaction_id": "tx-retry"},
    )

    proposal = worker.process_observation(
        retry_observation,
        allow_retry=True,
    )

    assert proposal.status == "pending"
    assert proposal.approval_id == "approval-retry"
def test_worker_retry_consumption_preserves_other_persisted_retries(tmp_path):
    from core.worker_state_store import WorkerStateStore

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

    store = WorkerStateStore(tmp_path / "worker.json")
    worker = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    retry_a = "corrigir arquivo A"
    retry_b = "corrigir arquivo B"

    worker._retry_instructions.update({retry_a, retry_b})
    worker._persist_state()

    worker.process_observation(
        Observation(instruction=retry_a, metadata={}),
        allow_retry=True,
    )
    worker._retry_instructions.discard(retry_a)
    worker._persist_state()

    restarted = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    assert retry_a not in restarted._retry_instructions
    assert retry_b in restarted._retry_instructions
def test_process_observation_crash_after_atomic_persist_preserves_other_retries(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def create_task(self, instruction):
            return {
                "approval_id": f"approval-{instruction}",
                "status": "pending",
                "plan": {},
            }

    class CrashAfterPersistStore(WorkerStateStore):
        def _save_unlocked(self, state):
            super()._save_unlocked(state)
            raise RuntimeError("simulated crash after durable persist")

    path = tmp_path / "worker.json"

    store = WorkerStateStore(path)
    worker = Worker(
        Gateway(),
        Observer([]),
        store=store,
    )

    retry_a = "corrigir arquivo A"
    retry_b = "corrigir arquivo B"

    worker._retry_instructions.update({retry_a, retry_b})
    worker._persist_state()

    crashing_worker = Worker(
        Gateway(),
        Observer([]),
        store=CrashAfterPersistStore(path),
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing_worker.process_observation(
            Observation(retry_a, {}),
            allow_retry=True,
        )

    restarted = Worker(
        Gateway(),
        Observer([]),
        store=WorkerStateStore(path),
    )

    assert retry_a not in restarted._retry_instructions
    assert retry_b in restarted._retry_instructions

def test_worker_restart_reuses_pending_proposal_after_crash_before_persist(
    tmp_path,
):
    from core.observation import Observation
    from core.observer import Observer
    from core.worker import Worker
    from core.worker_state_store import WorkerStateStore

    class Gateway:
        def __init__(self):
            self.pending = []
            self.create_calls = 0

        def list_pending(self):
            return list(self.pending)

        def create_task(self, instruction):
            self.create_calls += 1
            result = {
                "approval_id": f"approval-{self.create_calls}",
                "status": "pending",
                "plan": {},
            }
            self.pending.append(
                {
                    "instruction": instruction,
                    **result,
                }
            )
            return result

    class CrashBeforePersistStore(WorkerStateStore):
        def _save_unlocked(self, state):
            raise RuntimeError("simulated crash before durable persist")

    path = tmp_path / "worker.json"
    gateway = Gateway()
    observation = Observation("nova tarefa", {})

    crashing_worker = Worker(
        gateway,
        Observer([]),
        store=CrashBeforePersistStore(path),
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing_worker.process_observation(observation)

    assert gateway.create_calls == 1
    assert gateway.pending[0]["approval_id"] == "approval-1"
    assert not path.exists()

    restarted = Worker(
        gateway,
        Observer([]),
        store=WorkerStateStore(path),
    )

    proposal = restarted.process_observation(observation)

    assert proposal.approval_id == "approval-1"
    assert gateway.create_calls == 1
    assert restarted.processed_ids == {"approval-1"}

    persisted = WorkerStateStore(path).load()
    assert persisted["processed"] == [
        {
            "instruction": "nova tarefa",
            "metadata": {},
        }
    ]
    assert persisted["processed_ids"] == ["approval-1"]
def test_worker_reconcile_terminal_feedback_filters_invalid_tasks():
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_tasks(self):
            return [
                {
                    "task_id": "task-committed",
                    "approval_id": "approval-committed",
                    "transaction_id": "tx-committed",
                    "status": "committed",
                },
                {
                    "task_id": "task-failed",
                    "approval_id": "approval-failed",
                    "transaction_id": "tx-failed",
                    "status": "failed",
                },
                {
                    "task_id": "task-rolled-back",
                    "approval_id": "approval-rolled-back",
                    "transaction_id": "tx-rolled-back",
                    "status": "rolled_back",
                },
                {
                    "task_id": "task-pending",
                    "approval_id": "approval-pending",
                    "transaction_id": "tx-pending",
                    "status": "pending",
                },
                {
                    "task_id": "task-no-tx",
                    "approval_id": "approval-no-tx",
                    "status": "failed",
                },
                {
                    "task_id": "task-recovery",
                    "approval_id": "approval-recovery",
                    "transaction_id": "tx-recovery",
                    "status": "failed",
                    "recovery": True,
                },
            ]

    observer = Observer()
    worker = Worker(Gateway(), observer)

    worker._reconcile_terminal_feedback()

    observations = observer.observe()

    assert len(observations) == 3

    assert {
        observation.metadata["transaction_id"]
        for observation in observations
    } == {
        "tx-committed",
        "tx-failed",
        "tx-rolled-back",
    }

    assert all(
        observation.metadata["source"] == "transaction_result"
        for observation in observations
    )

def test_persist_processed_state_restores_state_when_persistence_fails(monkeypatch):
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        pass

    worker = Worker(Gateway(), Observer([]))

    worker._processed = {"original"}
    worker._processed_ids = {"id-original"}
    worker._processed_observations = {
        "key-original": {"value": 1},
    }

    def operation():
        worker._processed.add("novo")
        worker._processed_ids.add("id-novo")
        worker._processed_observations["key-novo"] = {"value": 2}

    def fail_persist():
        raise OSError("falha de persistência")

    monkeypatch.setattr(worker, "_persist_state", fail_persist)

    with pytest.raises(OSError, match="falha de persistência"):
        worker._persist_processed_state(operation)

    assert worker._processed == {"original"}
    assert worker._processed_ids == {"id-original"}
    assert worker._processed_observations == {
        "key-original": {"value": 1},
    }


def test_worker_reconcile_terminal_feedback_returns_when_tasks_is_not_list():
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_tasks(self):
            return {"invalid": True}

    observer = Observer([])
    worker = Worker(Gateway(), observer)

    worker._reconcile_terminal_feedback()

    assert observer.observe() == []


def test_worker_reconcile_terminal_feedback_skips_non_dict_task():
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_tasks(self):
            return [
                "registro inválido",
                {
                    "task_id": "task-valid",
                    "approval_id": "approval-valid",
                    "transaction_id": "tx-valid",
                    "status": "committed",
                },
            ]

    observer = Observer([])
    worker = Worker(Gateway(), observer)

    worker._reconcile_terminal_feedback()

    observations = observer.observe()

    assert len(observations) == 1
    assert observations[0].metadata["transaction_id"] == "tx-valid"


def test_worker_reconcile_terminal_feedback_skips_when_feedback_builder_returns_none(
    monkeypatch,
):
    from core.execution_feedback import ExecutionFeedback
    from core.observer import Observer
    from core.worker import Worker

    class Gateway:
        def list_tasks(self):
            return [
                {
                    "task_id": "task-valid",
                    "approval_id": "approval-valid",
                    "transaction_id": "tx-valid",
                    "status": "committed",
                },
            ]

    observer = Observer([])
    worker = Worker(Gateway(), observer)

    monkeypatch.setattr(
        ExecutionFeedback,
        "build",
        lambda self, result: None,
    )

    worker._reconcile_terminal_feedback()

    assert observer.observe() == []
