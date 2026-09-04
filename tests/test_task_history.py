import json

import pytest

from core.memory.task_history import TaskHistory, TaskHistoryStatus


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


def test_task_history_rejects_non_dict_root(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(["invalid", "shape"]),
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.list_all() == []


def test_task_history_rejects_corrupt_json(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="Estado persistido inválido"):
        TaskHistory(path)


def test_task_history_propagates_os_error(tmp_path, monkeypatch):
    path = tmp_path / "tasks.json"
    path.write_text("{}", encoding="utf-8")

    original_read_text = type(path).read_text

    def failing_read_text(self, *args, **kwargs):
        if self == path:
            raise OSError("read failure")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", failing_read_text)

    with pytest.raises(OSError, match="read failure"):
        TaskHistory(path)


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


@pytest.mark.parametrize("extra", [None, [], "invalid", 123])
def test_task_history_update_rejects_non_dict_extra(tmp_path, extra):
    history = TaskHistory(tmp_path / "tasks.json")
    history.create("1", "teste", {})

    if extra is None:
        result = history.update("1", extra=extra)
        assert result["task_id"] == "1"
        return

    with pytest.raises(TypeError, match="extra deve ser um dicionário"):
        history.update("1", extra=extra)


def test_task_history_update_rejects_structural_extra_fields(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")
    history.create("1", "teste", {})

    with pytest.raises(
        ValueError,
        match="Campos estruturais não podem ser sobrescritos",
    ):
        history.update(
            "1",
            extra={"task_id": "attacker"},
        )


def test_task_history_rejects_non_dict_task_records(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        '{"1": "invalid", "2": 123, "3": null}',
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.tasks == {}


def test_task_history_rejects_task_with_missing_required_fields(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        '{"1": {"task_id": "1", "status": "pending"}}',
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.tasks == {}


def test_task_history_rejects_task_with_invalid_status(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        '{"1": {'
        '"task_id": "1", '
        '"approval_id": "1", '
        '"instruction": "teste", '
        '"plan": {}, '
        '"status": "invalid", '
        '"transaction_id": null, '
        '"created_at": "2026-09-02T00:00:00+00:00", '
        '"updated_at": "2026-09-02T00:00:00+00:00"'
        '}}',
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.tasks == {}


def test_task_history_load_preserves_valid_task_records(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        '{"1": {'
        '"task_id": "1", '
        '"approval_id": "1", '
        '"instruction": "teste", '
        '"plan": {}, '
        '"status": "pending", '
        '"transaction_id": null, '
        '"created_at": "2026-09-02T00:00:00+00:00", '
        '"updated_at": "2026-09-02T00:00:00+00:00"'
        '}}',
        encoding="utf-8",
    )

    history = TaskHistory(path)

    assert history.get("1") == {
        "task_id": "1",
        "approval_id": "1",
        "instruction": "teste",
        "plan": {},
        "status": "pending",
        "transaction_id": None,
        "created_at": "2026-09-02T00:00:00+00:00",
        "updated_at": "2026-09-02T00:00:00+00:00",
    }


def test_task_history_update_rejects_lifecycle_fields_in_extra(tmp_path):
    path = tmp_path / "tasks.json"
    history = TaskHistory(path)

    created = history.create(
        "approval-1",
        "test instruction",
        {"changes": []},
    )

    with pytest.raises(
        ValueError,
        match="Campos estruturais não podem ser sobrescritos",
    ):
        history.update(
            created["task_id"],
            extra={"status": TaskHistoryStatus.FAILED.value},
        )

    with pytest.raises(
        ValueError,
        match="Campos estruturais não podem ser sobrescritos",
    ):
        history.update(
            created["task_id"],
            extra={"transaction_id": "forged-transaction"},
        )

    task = history.get(created["task_id"])

    assert task["status"] == TaskHistoryStatus.PENDING.value
    assert task["transaction_id"] is None


def test_task_history_update_rejects_invalid_status(tmp_path):
    path = tmp_path / "tasks.json"
    history = TaskHistory(path)

    created = history.create(
        "approval-1",
        "test instruction",
        {"changes": []},
    )

    with pytest.raises(
        ValueError,
        match="status inválido",
    ):
        history.update(
            created["task_id"],
            status="forged-status",
        )

    task = history.get(created["task_id"])

    assert task["status"] == TaskHistoryStatus.PENDING.value

def test_task_history_create_preserves_in_memory_state_on_persistence_failure(
    tmp_path,
):
    path = tmp_path / "tasks.json"
    history = TaskHistory(path)

    with pytest.raises(TypeError):
        history.create(
            "failed-task",
            "instruction",
            {"invalid": object()},
        )

    assert history.get("failed-task") is None
    assert TaskHistory(path).get("failed-task") is None


def test_task_history_update_preserves_in_memory_state_on_persistence_failure(
    tmp_path,
):
    path = tmp_path / "tasks.json"
    history = TaskHistory(path)

    original = history.create(
        "task-1",
        "instruction",
        {"ok": True},
    )
    original_snapshot = dict(original)

    with pytest.raises(TypeError):
        history.update(
            "task-1",
            extra={"invalid": object()},
        )

    assert history.get("task-1") == original_snapshot
    assert TaskHistory(path).get("task-1") == original_snapshot



def test_task_history_serializes_concurrent_creates_across_instances(
    tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "tasks.json"

    histories = [
        TaskHistory(path),
        TaskHistory(path),
    ]

    def create_task(index):
        history = histories[index % 2]

        return history.create(
            approval_id=f"approval-{index}",
            instruction=f"instruction-{index}",
            plan={"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        tasks = list(
            executor.map(create_task, range(32))
        )

    assert len(tasks) == 32

    reloaded = TaskHistory(path)

    assert len(reloaded.tasks) == 32
    assert {
        task["approval_id"]
        for task in reloaded.tasks.values()
    } == {
        f"approval-{index}"
        for index in range(32)
    }

    assert all(
        task["transaction_id"] is None
        for task in reloaded.tasks.values()
    )

def test_task_history_serializes_concurrent_updates_across_instances(
    tmp_path,
):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "tasks.json"

    histories = [
        TaskHistory(path),
        TaskHistory(path),
    ]

    for index in range(32):
        histories[0].create(
            approval_id=f"approval-{index}",
            instruction=f"instruction-{index}",
            plan={"index": index},
        )

    def update_task(index):
        history = histories[index % 2]

        return history.update(
            f"approval-{index}",
            transaction_id=f"transaction-{index}",
            extra={"worker": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        updated = list(
            executor.map(update_task, range(32))
        )

    assert len(updated) == 32

    reloaded = TaskHistory(path)

    assert len(reloaded.tasks) == 32

    assert {
        task["approval_id"]
        for task in reloaded.tasks.values()
    } == {
        f"approval-{index}"
        for index in range(32)
    }

    assert {
        task["transaction_id"]
        for task in reloaded.tasks.values()
    } == {
        f"transaction-{index}"
        for index in range(32)
    }

    assert {
        task["worker"]
        for task in reloaded.tasks.values()
    } == set(range(32))
