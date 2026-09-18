import pytest

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
