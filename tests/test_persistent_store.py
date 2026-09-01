import os
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

def test_persistent_store_load_returns_default_on_os_error(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    def fake_read_text(*args, **kwargs):
        raise OSError("read failure")

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert store.load(default={"fallback": True}) == {"fallback": True}


def test_persistent_store_load_returns_default_on_unicode_error(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    def fake_read_text(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert store.load(default={"fallback": True}) == {"fallback": True}


def test_persistent_store_update_rejects_non_callable(tmp_path):
    store = PersistentStore(tmp_path / "state.json")

    try:
        store.update("not callable")
        assert False
    except TypeError as exc:
        assert str(exc) == "updater deve ser chamável."


def test_persistent_store_update_returns_and_persists_new_state(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    store.save({"count": 1})

    result = store.update(
        lambda state: {
            **state,
            "count": state["count"] + 1,
        }
    )

    assert result == {"count": 2}
    assert store.load() == {"count": 2}


def test_persistent_store_update_uses_default_when_file_is_missing(tmp_path):
    store = PersistentStore(tmp_path / "state.json")

    result = store.update(
        lambda state: {
            **state,
            "created": True,
        },
        default={},
    )

    assert result == {"created": True}
    assert store.load() == {"created": True}


def test_persistent_store_save_cleans_temporary_file_when_replace_fails(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    original_replace = os.replace

    def failing_replace(*args, **kwargs):
        raise OSError("replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    try:
        store.save({"value": 1})
        assert False
    except OSError as exc:
        assert str(exc) == "replace failure"

    temporary_files = list(tmp_path.glob(".state.json.*.tmp"))
    assert temporary_files == []

    monkeypatch.setattr(os, "replace", original_replace)


def test_persistent_store_save_recreates_parent_directory(tmp_path):
    parent = tmp_path / "nested" / "directory"
    path = parent / "state.json"

    store = PersistentStore(path)
    assert parent.exists()

    store.save({"ok": True})

    assert path.exists()
    assert store.load() == {"ok": True}


def test_persistent_store_update_serializes_read_modify_write(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)
    store.save({"count": 0})

    import threading

    errors = []

    def increment():
        try:
            store.update(
                lambda state: {
                    "count": state["count"] + 1,
                }
            )
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=increment)
        for _ in range(20)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert errors == []
    assert store.load() == {"count": 20}
