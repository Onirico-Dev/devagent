import json

import pytest

from core.memory.task_history import TaskHistory


def test_task_history_starts_empty_when_file_is_missing(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    assert history.list_all() == []
    assert history.list_pending() == []
    assert history.latest() is None


def test_task_history_create_persists_task(tmp_path):
    path = tmp_path / "tasks.json"
    history = TaskHistory(path)

    task = history.create(
        "approval-1",
        "criar arquivo",
        {"changes": []},
    )

    assert task["task_id"] == "approval-1"
    assert task["approval_id"] == "approval-1"
    assert task["instruction"] == "criar arquivo"
    assert task["plan"] == {"changes": []}
    assert task["status"] == "pending"
    assert task["transaction_id"] is None
    assert task["created_at"] == task["updated_at"]

    reloaded = TaskHistory(path)

    assert reloaded.get("approval-1") == task


def test_task_history_loads_valid_dict(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "1": {
                    "task_id": "1",
                    "status": "completed",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.get("1")["status"] == "completed"


def test_task_history_loads_non_dict_as_empty(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(["invalid", "shape"]),
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.list_all() == []


def test_task_history_recovers_from_corrupt_json(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{invalid", encoding="utf-8")

    history = TaskHistory(path)

    assert history.list_all() == []


def test_task_history_recovers_from_os_error(tmp_path, monkeypatch):
    path = tmp_path / "tasks.json"
    path.write_text("{}", encoding="utf-8")

    original_read_text = type(path).read_text

    def failing_read_text(self, *args, **kwargs):
        if self == path:
            raise OSError("read failure")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", failing_read_text)

    history = TaskHistory(path)

    assert history.list_all() == []


def test_task_history_update_changes_status(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.create(
        "1",
        "teste",
        {},
    )

    result = history.update(
        "1",
        status="completed",
    )

    assert result["status"] == "completed"
    assert result["transaction_id"] is None


def test_task_history_update_changes_transaction_id(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.create(
        "1",
        "teste",
        {},
    )

    result = history.update(
        "1",
        transaction_id="tx-123",
    )

    assert result["transaction_id"] == "tx-123"


def test_task_history_update_applies_extra_fields(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.create(
        "1",
        "teste",
        {},
    )

    result = history.update(
        "1",
        extra={
            "error": "falha",
            "repair_attempts": 2,
        },
    )

    assert result["error"] == "falha"
    assert result["repair_attempts"] == 2


def test_task_history_update_rejects_missing_task(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    with pytest.raises(KeyError, match="Tarefa não encontrada"):
        history.update("missing", status="failed")


def test_task_history_get_uses_string_task_id(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.create(
        123,
        "teste",
        {},
    )

    assert history.get(123) == history.get("123")


def test_task_history_list_pending_filters_status(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.create("pending", "teste", {})
    history.create("done", "teste", {})

    history.update("done", status="completed")

    pending = history.list_pending()

    assert len(pending) == 1
    assert pending[0]["task_id"] == "pending"


def test_task_history_latest_returns_most_recent_updated_task(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    first = history.create("1", "primeira", {})
    second = history.create("2", "segunda", {})

    first["updated_at"] = "2026-01-01T00:00:00+00:00"
    second["updated_at"] = "2026-02-01T00:00:00+00:00"

    history.tasks["1"] = first
    history.tasks["2"] = second

    assert history.latest()["task_id"] == "2"


def test_task_history_latest_uses_empty_string_for_missing_updated_at(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")

    history.tasks = {
        "1": {
            "task_id": "1",
        }
    }

    assert history.latest()["task_id"] == "1"
