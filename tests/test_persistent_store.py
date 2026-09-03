import os
import json
import pytest
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

def test_persistent_store_save_ignores_temporary_cleanup_error(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    original_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name.startswith(".state.json.") and self.name.endswith(".tmp"):
            raise OSError("cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    store.save({"value": 1})

    assert path.exists()
    assert store.load() == {"value": 1}

def test_persistent_store_save_ignores_temporary_cleanup_error(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    original_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name.startswith(".state.json.") and self.name.endswith(".tmp"):
            raise OSError("cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    store.save({"value": 1})

    assert path.exists()
    assert store.load() == {"value": 1}


def test_persistent_store_save_removes_existing_temporary_file_when_replace_fails(
    tmp_path, monkeypatch
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    original_replace = os.replace

    def failing_replace(source, destination):
        raise OSError("replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    original_exists = Path.exists

    def fake_exists(self):
        if self.parent == tmp_path and self.name.startswith(".state.json.") and self.name.endswith(".tmp"):
            return True
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    original_unlink = Path.unlink
    removed = []

    def tracking_unlink(self, *args, **kwargs):
        removed.append(self)
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", tracking_unlink)

    try:
        store.save({"value": 1})
        assert False
    except OSError as exc:
        assert str(exc) == "replace failure"

    assert len(removed) == 1
    assert removed[0].name.startswith(".state.json.")
    assert removed[0].name.endswith(".tmp")


def test_persistent_store_save_ignores_cleanup_error_after_replace(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    original_exists = Path.exists
    original_unlink = Path.unlink

    def fake_exists(self):
        if (
            self.parent == tmp_path
            and self.name.startswith(".state.json.")
            and self.name.endswith(".tmp")
        ):
            return True
        return original_exists(self)

    def failing_unlink(self, *args, **kwargs):
        if (
            self.parent == tmp_path
            and self.name.startswith(".state.json.")
            and self.name.endswith(".tmp")
        ):
            raise OSError("cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    store.save({"value": 1})

    assert path.exists()
    assert store.load() == {"value": 1}


def test_persistent_store_save_preserves_previous_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    store.save({"version": 1})

    with pytest.raises(TypeError):
        store.save({"version": 2, "invalid": object()})

    assert store.load() == {"version": 1}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_persistent_store_update_preserves_state_when_updater_fails(tmp_path):
    path = tmp_path / "state.json"
    store = PersistentStore(path)

    store.save({"count": 1})

    def failing_updater(state):
        state["count"] = 999
        raise RuntimeError("update failure")

    with pytest.raises(RuntimeError, match="update failure"):
        store.update(failing_updater)

    assert store.load() == {"count": 1}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_persistent_store_serializes_concurrent_updates_across_instances(
    tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "state.json"

    stores = [
        PersistentStore(path),
        PersistentStore(path),
    ]

    stores[0].save({"count": 0})

    def increment(index):
        store = stores[index % 2]

        def updater(state):
            return {
                "count": state["count"] + 1,
            }

        store.update(updater)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(32)))

    reloaded = PersistentStore(path)

    assert reloaded.load() == {"count": 32}

def test_persistent_store_fsyncs_parent_directory_after_replace(
    tmp_path,
    monkeypatch,
):
    import os

    path = tmp_path / "state.json"
    store = PersistentStore(path)

    fsync_calls = []
    original_open = os.open
    original_fsync = os.fsync
    original_close = os.close

    def tracking_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        fsync_calls.append(("open", args[0], fd))
        return fd

    def tracking_fsync(fd):
        fsync_calls.append(("fsync", fd))
        return original_fsync(fd)

    def tracking_close(fd):
        fsync_calls.append(("close", fd))
        return original_close(fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "fsync", tracking_fsync)
    monkeypatch.setattr(os, "close", tracking_close)

    store.save({"value": 1})

    directory_fsyncs = [
        call
        for call in fsync_calls
        if call[0] == "fsync"
        and any(
            item[0] == "open"
            and item[2] == call[1]
            and item[1] == str(tmp_path)
            for item in fsync_calls
        )
    ]

    assert directory_fsyncs

