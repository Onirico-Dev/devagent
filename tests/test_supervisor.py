import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from core.supervisor import ApprovalStatus, Supervisor


def test_supervisor_loads_non_dict_json_as_empty(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("[]", encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_recovers_from_invalid_json(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("not json", encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_request_approval_rejects_invalid_plan(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(ValueError, match="Plano de aprovação inválido"):
        supervisor.request_approval(None)


def test_supervisor_ignores_non_numeric_approval_ids(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps(
            {
                "abc": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {"changes": []},
                },
                "7": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {"changes": []},
                },
            }
        ),
        encoding="utf-8",
    )

    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"changes": []})

    assert approval_id == "8"


def test_supervisor_approve_missing_request_raises_key_error(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(KeyError, match="Tarefa não encontrada"):
        supervisor.approve("999")


def test_supervisor_get_missing_request_returns_none(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    assert supervisor.get("999") is None


def test_supervisor_list_all_returns_isolated_copy(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    approval_id = supervisor.request_approval({"changes": []})

    result = supervisor.list_all()

    assert approval_id in result
    result[approval_id]["status"] = ApprovalStatus.REJECTED.value

    assert (
        supervisor.get(approval_id)["status"]
        == ApprovalStatus.PENDING.value
    )


def test_supervisor_list_pending_returns_only_pending_requests(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    pending_id = supervisor.request_approval({"name": "pending"})
    rejected_id = supervisor.request_approval({"name": "rejected"})

    supervisor.reject(rejected_id)

    result = supervisor.list_pending()

    assert list(result) == [pending_id]
    assert result[pending_id]["status"] == ApprovalStatus.PENDING.value
    assert rejected_id not in result
import json

import pytest

from core.supervisor import ApprovalStatus, Supervisor


def test_supervisor_recovers_non_dict_json(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text('["invalid"]', encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_recovers_invalid_json(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("not json", encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_rejects_invalid_plan(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(ValueError, match="Plano de aprovação inválido"):
        supervisor.request_approval(None)


def test_supervisor_ignores_non_numeric_approval_ids(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps(
            {
                "abc": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {"changes": []},
                },
                "7": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {"changes": []},
                },
            }
        ),
        encoding="utf-8",
    )

    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"changes": []})

    assert approval_id == "8"


def test_supervisor_approve_missing_request(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(KeyError, match="Tarefa não encontrada"):
        supervisor.approve("999")


def test_supervisor_get_missing_request(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    assert supervisor.get("999") is None


def test_supervisor_list_all_returns_copy(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    approval_id = supervisor.request_approval({"changes": []})
    result = supervisor.list_all()

    result[approval_id]["status"] = ApprovalStatus.REJECTED.value

    assert supervisor.get(approval_id)["status"] == ApprovalStatus.PENDING.value


def test_supervisor_list_pending_filters_non_pending(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    pending_id = supervisor.request_approval({"changes": []})
    approved_id = supervisor.request_approval({"changes": []})

    supervisor.approve(approved_id)

    pending = supervisor.list_pending()

    assert pending_id in pending
    assert approved_id not in pending
    assert pending[pending_id]["status"] == ApprovalStatus.PENDING.value

import json

import pytest

from core.supervisor import ApprovalStatus, Supervisor


def test_supervisor_recovers_from_non_dict_json(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("[]", encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_recovers_from_invalid_json(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text("not json", encoding="utf-8")

    supervisor = Supervisor(path)

    assert supervisor.list_all() == {}


def test_supervisor_rejects_invalid_plan(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(
        ValueError,
        match="Plano de aprovação inválido.",
    ):
        supervisor.request_approval(None)


def test_supervisor_ignores_non_numeric_approval_ids(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps(
            {
                "abc": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {},
                },
                "1": {
                    "status": ApprovalStatus.PENDING.value,
                    "plan": {},
                },
            }
        ),
        encoding="utf-8",
    )

    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"changes": []})

    assert approval_id == "2"


def test_supervisor_approve_missing_request(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(
        KeyError,
        match="Tarefa não encontrada.",
    ):
        supervisor.approve("999")


def test_supervisor_get_missing_request(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    assert supervisor.get("999") is None


def test_supervisor_list_all_returns_copy(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    approval_id = supervisor.request_approval({"changes": []})

    result = supervisor.list_all()

    assert approval_id in result
    assert result[approval_id]["status"] == ApprovalStatus.PENDING.value

    result[approval_id]["status"] = "corrupted"

    assert supervisor.get(approval_id)["status"] == ApprovalStatus.PENDING.value


def test_supervisor_list_pending_filters_non_pending(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    pending_id = supervisor.request_approval({"changes": []})
    approved_id = supervisor.request_approval({"changes": []})

    supervisor.approve(approved_id)

    pending = supervisor.list_pending()

    assert pending_id in pending
    assert approved_id not in pending

def test_supervisor_request_approval_preserves_in_memory_state_on_save_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    def failing_save():
        raise OSError("simulated save failure")

    monkeypatch.setattr(supervisor, "_save", failing_save)

    with pytest.raises(OSError, match="simulated save failure"):
        supervisor.request_approval({"name": "new"})

    assert supervisor.pending == {}
    assert Supervisor(path).pending == {}


def test_supervisor_approve_preserves_in_memory_state_on_save_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"name": "approval"})
    original = copy.deepcopy(supervisor.pending[approval_id])

    def failing_save():
        raise OSError("simulated save failure")

    monkeypatch.setattr(supervisor, "_save", failing_save)

    with pytest.raises(OSError, match="simulated save failure"):
        supervisor.approve(approval_id)

    assert supervisor.pending[approval_id] == original
    assert Supervisor(path).pending[approval_id] == original


def test_supervisor_reject_preserves_in_memory_state_on_save_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"name": "approval"})
    original = copy.deepcopy(supervisor.pending[approval_id])

    def failing_save():
        raise OSError("simulated save failure")

    monkeypatch.setattr(supervisor, "_save", failing_save)

    with pytest.raises(OSError, match="simulated save failure"):
        supervisor.reject(approval_id)

    assert supervisor.pending[approval_id] == original
    assert Supervisor(path).pending[approval_id] == original



def test_supervisor_serializes_concurrent_request_approval(tmp_path):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    def create_approval(index):
        return supervisor.request_approval({"index": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        approval_ids = list(
            executor.map(create_approval, range(32))
        )

    assert len(approval_ids) == 32
    assert len(set(approval_ids)) == 32
    assert sorted(map(int, approval_ids)) == list(range(1, 33))

    reloaded = Supervisor(path)
    assert len(reloaded.pending) == 32
    assert set(reloaded.pending) == set(approval_ids)


def test_supervisor_serializes_concurrent_approve_for_same_request(
    tmp_path,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"name": "approval"})

    def approve():
        try:
            return supervisor.approve(approval_id)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: approve(), range(16)))

    successful = [result for result in results if result is not None]

    assert len(successful) == 1
    assert successful[0]["status"] == ApprovalStatus.APPROVED.value
    assert supervisor.pending[approval_id]["status"] == (
        ApprovalStatus.APPROVED.value
    )


def test_supervisor_serializes_concurrent_reject_for_same_request(
    tmp_path,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    approval_id = supervisor.request_approval({"name": "approval"})

    def reject():
        try:
            return supervisor.reject(approval_id)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: reject(), range(16)))

    successful = [result for result in results if result is not None]

    assert len(successful) == 1
    assert successful[0]["status"] == ApprovalStatus.REJECTED.value
    assert supervisor.pending[approval_id]["status"] == (
        ApprovalStatus.REJECTED.value
    )


def test_supervisor_serializes_concurrent_requests_across_instances(
    tmp_path,
):
    path = tmp_path / "approvals.json"
    supervisors = [
        Supervisor(path),
        Supervisor(path),
    ]

    def create_approval(index):
        supervisor = supervisors[index % 2]
        return supervisor.request_approval({"index": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        approval_ids = list(
            executor.map(create_approval, range(32))
        )

    assert len(approval_ids) == 32
    assert len(set(approval_ids)) == 32

    reloaded = Supervisor(path)
    assert len(reloaded.pending) == 32

def test_supervisor_save_fsyncs_storage_directory(
    tmp_path,
    monkeypatch,
):
    import os

    from core.supervisor import Supervisor

    storage = tmp_path / "approvals.json"
    supervisor = Supervisor(storage_path=str(storage))

    fsync_calls = []
    original_fsync = os.fsync

    def tracking_fsync(fd):
        fsync_calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(
        "core.supervisor.os.fsync",
        tracking_fsync,
    )

    supervisor.pending = {
        "approval-1": {
            "status": "pending",
        }
    }
    supervisor._save()

    assert storage.exists()
    assert len(fsync_calls) >= 2


def test_supervisor_save_propagates_directory_fsync_failure(
    tmp_path,
    monkeypatch,
):
    from core.supervisor import Supervisor

    storage = tmp_path / "approvals.json"
    supervisor = Supervisor(storage_path=str(storage))

    supervisor.pending = {
        "approval-1": {
            "status": "pending",
        }
    }

    calls = {"count": 0}

    def failing_fsync(fd):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(
        "core.supervisor.os.fsync",
        failing_fsync,
    )

    try:
        supervisor._save()
    except OSError as error:
        assert "simulated directory fsync failure" in str(error)
    else:
        raise AssertionError(
            "A falha no fsync do diretório deveria ser propagada."
        )

def test_supervisor_save_cleans_temporary_file_after_replace_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    original_replace = Path.replace

    def fail_replace(self, target):
        if self.parent == path.parent and self.name != path.name:
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        supervisor._save()

    temporary_files = list(tmp_path.glob(".approvals.json.*.tmp"))

    assert temporary_files == []


def test_supervisor_save_ignores_temporary_unlink_oserror(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approvals.json"
    supervisor = Supervisor(path)

    original_replace = Path.replace

    def keep_temporary(self, target):
        if self.parent == path.parent and self.name != path.name:
            return None
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", keep_temporary)

    original_unlink = Path.unlink

    def fail_unlink(self, *args, **kwargs):
        if self.parent == path.parent and self.name != path.name:
            raise OSError("unlink failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    supervisor._save()

    temporary_files = list(tmp_path.glob(".approvals.json.*.tmp"))

    assert len(temporary_files) == 1

    original_unlink(temporary_files[0])

def test_supervisor_prepare_approval_returns_pending_copy(tmp_path):
    supervisor = Supervisor(tmp_path / "approvals.json")

    approval_id = supervisor.request_approval(
        {"changes": []}
    )

    result = supervisor.prepare_approval(approval_id)

    assert result["status"] == ApprovalStatus.PENDING.value
    assert result["plan"] == {"changes": []}

    result["plan"]["changes"].append({"path": "mutated"})

    assert supervisor.get(approval_id)["plan"] == {"changes": []}


def test_supervisor_prepare_approval_missing_request_raises_key_error(
    tmp_path,
):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(
        KeyError,
        match="Tarefa não encontrada",
    ):
        supervisor.prepare_approval("999")


def test_supervisor_prepare_approval_rejects_non_pending_request(
    tmp_path,
):
    supervisor = Supervisor(tmp_path / "approvals.json")

    approval_id = supervisor.request_approval(
        {"changes": []}
    )
    supervisor.approve(approval_id)

    with pytest.raises(
        ValueError,
        match="Solicitação não está pendente",
    ):
        supervisor.prepare_approval(approval_id)


def test_supervisor_reject_missing_request_raises_key_error(
    tmp_path,
):
    supervisor = Supervisor(tmp_path / "approvals.json")

    with pytest.raises(
        KeyError,
        match="Solicitação não encontrada",
    ):
        supervisor.reject("999")
