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
