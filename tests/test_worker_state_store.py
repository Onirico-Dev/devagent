import json

import pytest

from core.worker_state_store import WorkerStateStore


def test_store_returns_empty_state_when_missing(tmp_path):
    store = WorkerStateStore(tmp_path / "worker.json")

    assert store.load() == {}


def test_store_saves_and_loads_state(tmp_path):
    store = WorkerStateStore(tmp_path / "worker.json")

    state = {
        "processed": [
            {
                "instruction": "criar arquivo",
                "metadata": {"source": "test"},
            }
        ],
        "processed_ids": ["1"],
    }

    store.save(state)

    assert store.load() == state


def test_store_rejects_non_dict_state(tmp_path):
    store = WorkerStateStore(tmp_path / "worker.json")

    with pytest.raises(ValueError, match="Estado do Worker inválido"):
        store.save([])


def test_store_rejects_invalid_persisted_data(tmp_path):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps([]), encoding="utf-8")

    store = WorkerStateStore(path)

    with pytest.raises(ValueError, match="Armazenamento do Worker inválido"):
        store.load()


def test_store_writes_valid_json(tmp_path):
    path = tmp_path / "worker.json"
    store = WorkerStateStore(path)

    store.save({"processed": [], "processed_ids": []})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "processed": [],
        "processed_ids": [],
    }


def test_save_removes_temporary_file_on_failure(monkeypatch, tmp_path):
    import pytest
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "state.json")

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.save({"processed": [], "processed_ids": []})

    assert not list(tmp_path.glob("*.tmp"))


def _save_worker_state_process(path, index):
    from core.worker_state_store import WorkerStateStore

    WorkerStateStore(path).save(
        {
            "processed": [
                {
                    "instruction": f"instrucao-{index}",
                    "metadata": {"index": index},
                }
            ],
            "processed_ids": [str(index)],
        }
    )


def test_store_concurrent_process_saves_leave_valid_state(tmp_path):
    import multiprocessing

    path = tmp_path / "worker.json"
    ctx = multiprocessing.get_context("fork")
    processes = [
        ctx.Process(
            target=_save_worker_state_process,
            args=(path, index),
        )
        for index in range(8)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    state = WorkerStateStore(path).load()

    assert isinstance(state, dict)
    assert len(state["processed"]) == 1
    assert len(state["processed_ids"]) == 1

def test_save_suppresses_temporary_file_not_found(monkeypatch, tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "state.json")

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    def fail_unlink(*args, **kwargs):
        raise FileNotFoundError("temporary file already gone")

    monkeypatch.setattr("os.replace", fail_replace)
    monkeypatch.setattr("os.unlink", fail_unlink)

    with pytest.raises(OSError, match="replace failed"):
        store.save({"processed": [], "processed_ids": []})


def test_update_rejects_non_callable_transform(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "state.json")

    with pytest.raises(ValueError, match="Transformação de estado inválida"):
        store.update(None)


def test_update_rejects_non_dict_transform_result(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "state.json")

    with pytest.raises(ValueError, match="Transformação produziu estado inválido"):
        store.update(lambda state: [])


def test_update_accepts_callable_transform(tmp_path):
    from core.worker_state_store import WorkerStateStore

    store = WorkerStateStore(tmp_path / "state.json")
    store.save({"count": 1})

    result = store.update(lambda state: {"count": state["count"] + 1})

    assert result == {"count": 2}
    assert store.load() == {"count": 2}
