import json
from pathlib import Path

from core.memory.persistent_store import PersistentStore


def test_persistent_store_loads_missing_file(tmp_path):
    store = PersistentStore(tmp_path / "state.json")

    assert store.load(default={}) == {}


def test_persistent_store_saves_and_loads_json(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    data = {
        "task": "123",
        "status": "pending",
        "unicode": "ação",
    }

    store.save(data)

    assert path.exists()
    assert store.load() == data


def test_persistent_store_write_is_valid_json(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    store.save({"value": 123})

    parsed = json.loads(path.read_text(encoding="utf-8"))

    assert parsed == {"value": 123}


def test_persistent_store_replaces_previous_state_atomically(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    store.save({"version": 1})
    store.save({"version": 2})

    assert store.load() == {"version": 2}


def test_persistent_store_corrupt_json_returns_default(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{invalid", encoding="utf-8")

    store = PersistentStore(path)

    assert store.load(default={"recovered": True}) == {
        "recovered": True
    }
