import json

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
