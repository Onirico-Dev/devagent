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
