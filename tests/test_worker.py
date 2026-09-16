
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
