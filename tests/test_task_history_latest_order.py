"""Latest means chronological update time, with a safe creation-time fallback."""
import copy

import pytest

from agent import DevAgent
from core.api.service import APIService
from core.gateway import DevAgentGateway
from core.memory.task_history import TaskHistory


@pytest.mark.parametrize("first, second", [
    ("2026-11-07T13:00:00+02:00", "2026-11-07T10:00:00-03:00"),
    ("2026-11-08T00:30:00+02:00", "2026-11-07T23:00:00Z"),
    ("2026-11-07T12:00:00Z", "2026-11-07T12:00:00.001+00:00"),
])
def test_latest_compares_instants_instead_of_iso_text(tmp_path, first, second):
    history = TaskHistory(tmp_path / "tasks.json")
    for task_id, updated in [("184", first), ("189", second)]:
        history.create(task_id, "instrução", {})
    for task_id, updated in [("184", first), ("189", second)]:
        history.tasks[task_id]["updated_at"] = updated
    before = copy.deepcopy(history.tasks)
    assert history.latest()["task_id"] == "189"
    assert history.tasks == before


@pytest.mark.parametrize("updated", ["not-a-date", "", None, 123])
def test_latest_falls_back_to_creation_time(tmp_path, updated):
    history = TaskHistory(tmp_path / "tasks.json")
    history.create("184", "anterior", {})
    history.create("189", "nova", {})
    first, second = history.tasks["184"], history.tasks["189"]
    first["updated_at"] = "2026-11-07T12:00:00Z"
    second.update(updated_at=updated, created_at="2026-11-07T13:00:00Z")
    assert history.latest()["task_id"] == "189"


def test_invalid_dates_do_not_hide_valid_latest_task(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")
    history.create("184", "anterior", {})
    history.create("189", "nova", {})
    first, second = history.tasks["184"], history.tasks["189"]
    first.update(updated_at="zzz", created_at="invalid")
    second["updated_at"] = "2026-11-07T13:00:00+00:00"
    assert history.latest()["task_id"] == "189"


def test_legacy_naive_dates_use_utc_and_equal_instants_keep_existing_order(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")
    history.create("1", "primeira", {})
    history.create("2", "segunda", {})
    first, second = history.tasks["1"], history.tasks["2"]
    first["updated_at"] = "2026-11-07T13:00:00"
    second["updated_at"] = "2026-11-07T10:00:00-03:00"
    assert history.latest()["task_id"] == "1"


def test_all_invalid_dates_keep_stable_order(tmp_path):
    history = TaskHistory(tmp_path / "tasks.json")
    history.tasks = {
        "1": {"task_id": "1", "updated_at": "aaa"},
        "2": {"task_id": "2", "updated_at": "zzz"},
    }
    assert history.latest()["task_id"] == "1"


def test_latest_api_refreshes_persisted_tasks_and_preserves_rejection(tmp_path):
    gateway = DevAgentGateway(DevAgent(tmp_path), tmp_path)
    history = gateway.history
    history.create("184", "anterior", {})
    history.create("189", "rejeitada", {})
    data = copy.deepcopy(history.tasks)
    data["184"].update(updated_at="2026-11-07T13:00:00+02:00")
    data["189"].update(updated_at="2026-11-07T10:00:00-03:00", status="rejected")
    history.store.save(data)
    stored_bytes = history.storage_path.read_bytes()
    result = APIService(gateway.agent, gateway).latest_task()
    assert result["task_id"] == "189"
    assert result["status"] == "rejected"
    assert result["transaction_id"] is None
    assert history.storage_path.read_bytes() == stored_bytes
