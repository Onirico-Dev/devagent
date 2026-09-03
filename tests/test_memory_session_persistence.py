import pytest
import json
import threading

from core.memory.memory import Memory
from core.memory.session import Session


def test_memory_creates_default_file(tmp_path):
    path = tmp_path / "memory.json"

    memory = Memory(path)

    assert path.exists()
    assert memory.all() == []


def test_memory_add_and_load(tmp_path):
    path = tmp_path / "memory.json"

    memory = Memory(path)
    memory.add("test.event", {"value": 123})

    loaded = Memory(path)

    events = loaded.all()

    assert len(events) == 1
    assert events[0]["event"] == "test.event"
    assert events[0]["data"] == {"value": 123}
    assert "timestamp" in events[0]


def test_memory_last(tmp_path):
    path = tmp_path / "memory.json"

    memory = Memory(path)

    for index in range(5):
        memory.add(f"event.{index}")

    assert len(memory.last(2)) == 2
    assert memory.last(2)[0]["event"] == "event.3"
    assert memory.last(2)[1]["event"] == "event.4"


def test_memory_rejects_invalid_event(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    try:
        memory.add("")
        assert False
    except ValueError:
        pass


def test_memory_recovers_from_invalid_root_json(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text('{"invalid": true}', encoding="utf-8")

    memory = Memory(path)

    assert memory.all() == []


def test_session_creates_default_file(tmp_path):
    path = tmp_path / "session.json"

    session = Session(path)

    assert path.exists()
    assert session.context() == {
        "instructions": [],
        "plans": [],
    }


def test_session_persists_instruction_and_plan(tmp_path):
    path = tmp_path / "session.json"

    session = Session(path)

    session.add_instruction("Crie arquivo teste.py")
    session.add_plan({"changes": []})

    loaded = Session(path)
    context = loaded.context()

    assert context["instructions"] == ["Crie arquivo teste.py"]
    assert context["plans"] == [{"changes": []}]


def test_session_preserves_extra_fields(tmp_path):
    path = tmp_path / "session.json"

    session = Session(path)

    session.save(
        {
            "instructions": [],
            "plans": [],
            "metadata": {
                "version": 1,
            },
        }
    )

    loaded = Session(path)

    assert loaded.context()["metadata"] == {"version": 1}


def test_session_recovers_invalid_root_json(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("not json", encoding="utf-8")

    session = Session(path)

    assert session.context() == {
        "instructions": [],
        "plans": [],
    }


def test_memory_file_is_valid_json_after_save(tmp_path):
    path = tmp_path / "memory.json"

    memory = Memory(path)
    memory.add("json.test", {"ok": True})

    data = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(data, list)
    assert data[0]["data"]["ok"] is True


def test_session_file_is_valid_json_after_save(tmp_path):
    path = tmp_path / "session.json"

    session = Session(path)
    session.add_instruction("teste")

    data = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert data["instructions"] == ["teste"]


def test_memory_concurrent_process_local_writes_remain_valid(tmp_path):
    path = tmp_path / "memory.json"
    memory = Memory(path)

    errors = []

    def writer(index):
        try:
            memory.add(f"event.{index}", {"index": index})
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(index,))
        for index in range(20)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert errors == []

    data = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(data, list)
    assert len(data) == 20


def test_session_concurrent_writes_remain_valid(tmp_path):
    path = tmp_path / "session.json"
    session = Session(path)

    errors = []

    def writer(index):
        try:
            session.add_instruction(f"instruction.{index}")
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(index,))
        for index in range(20)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert errors == []

    data = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert isinstance(data["instructions"], list)
    assert len(data["instructions"]) == 20


def test_session_load_normalizes_non_dict_root(tmp_path):
    path = tmp_path / "session.json"
    session = Session(path)

    session.store.load = lambda default=None: ["invalid"]

    assert session.load() == {
        "instructions": [],
        "plans": [],
    }


def test_session_load_normalizes_invalid_collections(tmp_path):
    path = tmp_path / "session.json"
    session = Session(path)

    session.store.load = lambda default=None: {
        "instructions": "invalid",
        "plans": {"invalid": True},
        "metadata": {"version": 2},
    }

    assert session.load() == {
        "instructions": [],
        "plans": [],
        "metadata": {"version": 2},
    }


def test_session_save_rejects_non_dict(tmp_path):
    session = Session(tmp_path / "session.json")

    try:
        session.save([])
        assert False
    except ValueError as exc:
        assert str(exc) == "A sessão deve ser um objeto JSON."


def test_session_save_rejects_invalid_instructions(tmp_path):
    session = Session(tmp_path / "session.json")

    try:
        session.save({
            "instructions": "invalid",
            "plans": [],
        })
        assert False
    except ValueError as exc:
        assert str(exc) == "instructions deve ser uma lista."


def test_session_save_rejects_invalid_plans(tmp_path):
    session = Session(tmp_path / "session.json")

    try:
        session.save({
            "instructions": [],
            "plans": "invalid",
        })
        assert False
    except ValueError as exc:
        assert str(exc) == "plans deve ser uma lista."


def test_session_add_instruction_recovers_invalid_root(tmp_path):
    session = Session(tmp_path / "session.json")

    session.store.update = lambda updater, default=None: updater([])

    session.add_instruction("teste")

    assert True


def test_session_add_instruction_recovers_invalid_collection(tmp_path):
    session = Session(tmp_path / "session.json")

    captured = {}

    def fake_update(updater, default=None):
        captured["result"] = updater({
            "instructions": "invalid",
            "plans": [],
        })

    session.store.update = fake_update

    session.add_instruction("teste")

    assert captured["result"]["instructions"] == ["teste"]


def test_session_add_plan_recovers_invalid_root(tmp_path):
    session = Session(tmp_path / "session.json")

    session.store.update = lambda updater, default=None: updater([])

    session.add_plan({"changes": []})

    assert True


def test_session_add_plan_recovers_invalid_collection(tmp_path):
    session = Session(tmp_path / "session.json")

    captured = {}

    def fake_update(updater, default=None):
        captured["result"] = updater({
            "instructions": [],
            "plans": "invalid",
        })

    session.store.update = fake_update

    session.add_plan({"changes": []})

    assert captured["result"]["plans"] == [{"changes": []}]


def test_memory_load_recovers_non_list_data(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.json")

    monkeypatch.setattr(
        memory.store,
        "load",
        lambda default=None: {"invalid": True},
    )

    assert memory._load() == []


def test_memory_save_rejects_non_list_data(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    try:
        memory._save({"invalid": True})
        assert False
    except ValueError as exc:
        assert str(exc) == "A memória deve ser uma lista."


def test_memory_add_recovers_non_list_store_state(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.json")
    captured = {}

    def fake_update(updater, default=None):
        captured["result"] = updater("invalid")

    monkeypatch.setattr(memory.store, "update", fake_update)

    memory.add("recovered.event")

    assert isinstance(captured["result"], list)
    assert len(captured["result"]) == 1
    assert captured["result"][0]["event"] == "recovered.event"
    assert captured["result"][0]["data"] is None
    assert "timestamp" in captured["result"][0]


def test_memory_last_rejects_non_integer_amount(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    try:
        memory.last("2")
        assert False
    except TypeError as exc:
        assert str(exc) == "amount deve ser um inteiro."


def test_memory_last_rejects_negative_amount(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    try:
        memory.last(-1)
        assert False
    except ValueError as exc:
        assert str(exc) == "amount não pode ser negativo."


def test_memory_last_zero_returns_empty_list(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    memory.add("event")

    assert memory.last(0) == []


def test_memory_save_rejects_non_list(tmp_path):
    memory = Memory(tmp_path / "memory.json")

    try:
        memory._save({"invalid": True})
        assert False
    except ValueError as exc:
        assert str(exc) == "A memória deve ser uma lista."


def test_memory_save_persists_valid_list(tmp_path):
    path = tmp_path / "memory.json"
    memory = Memory(path)

    data = [
        {
            "event": "manual.save",
            "data": {"ok": True},
        }
    ]

    memory._save(data)

    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded == data


def test_memory_save_accepts_list(tmp_path):
    path = tmp_path / "memory.json"
    memory = Memory(path)

    memory._save([
        {
            "event": "manual.save",
            "data": {"ok": True},
        }
    ])

    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert loaded == [
        {
            "event": "manual.save",
            "data": {"ok": True},
        }
    ]


def test_session_save_preserves_previous_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "session.json"
    session = Session(path)

    session.save(
        {
            "instructions": ["original"],
            "plans": [{"ok": True}],
        }
    )

    with pytest.raises(TypeError):
        session.save(
            {
                "instructions": ["updated"],
                "plans": [{"invalid": object()}],
            }
        )

    assert Session(path).context() == {
        "instructions": ["original"],
        "plans": [{"ok": True}],
    }


def test_session_add_instruction_preserves_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "session.json"
    session = Session(path)

    session.add_instruction("original")

    with pytest.raises(TypeError):
        session.add_instruction(object())

    assert Session(path).context() == {
        "instructions": ["original"],
        "plans": [],
    }


def test_session_add_plan_preserves_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "session.json"
    session = Session(path)

    session.add_plan({"original": True})

    with pytest.raises(TypeError):
        session.add_plan({"invalid": object()})

    assert Session(path).context() == {
        "instructions": [],
        "plans": [{"original": True}],
    }


def test_memory_save_preserves_previous_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "memory.json"
    memory = Memory(path)

    memory._save(
        [
            {
                "event": "original",
                "data": {"ok": True},
            }
        ]
    )

    with pytest.raises(TypeError):
        memory._save(
            [
                {
                    "event": "updated",
                    "data": {"invalid": object()},
                }
            ]
        )

    assert Memory(path).all() == [
        {
            "event": "original",
            "data": {"ok": True},
        }
    ]


def test_memory_add_preserves_previous_state_on_serialization_failure(
    tmp_path,
):
    path = tmp_path / "memory.json"
    memory = Memory(path)

    memory.add("original", {"ok": True})

    with pytest.raises(TypeError):
        memory.add("invalid", object())

    entries = Memory(path).all()

    assert len(entries) == 1
    assert entries[0]["event"] == "original"
    assert entries[0]["data"] == {"ok": True}
