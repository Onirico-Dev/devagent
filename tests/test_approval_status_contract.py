from core.supervisor import ApprovalStatus, Supervisor


def test_approval_status_enum_contract():
    assert ApprovalStatus.PENDING.value == "pending"
    assert ApprovalStatus.APPROVED.value == "approved"
    assert ApprovalStatus.REJECTED.value == "rejected"

    assert len(ApprovalStatus) == 3


def test_approval_status_is_string_enum():
    assert isinstance(ApprovalStatus.PENDING, str)
    assert isinstance(ApprovalStatus.APPROVED, str)
    assert isinstance(ApprovalStatus.REJECTED, str)


def test_supervisor_persists_enum_values_as_strings(tmp_path):
    supervisor = Supervisor(
        storage_path=tmp_path / "approvals.json",
    )

    approval_id = supervisor.request_approval({"name": "test"})

    pending = supervisor.get(approval_id)
    assert pending["status"] == ApprovalStatus.PENDING.value

    supervisor.approve(approval_id)

    approved = supervisor.get(approval_id)
    assert approved["status"] == ApprovalStatus.APPROVED.value


def test_supervisor_reject_persists_enum_value(tmp_path):
    supervisor = Supervisor(
        storage_path=tmp_path / "approvals.json",
    )

    approval_id = supervisor.request_approval({"name": "test"})
    supervisor.reject(approval_id)

    rejected = supervisor.get(approval_id)
    assert rejected["status"] == ApprovalStatus.REJECTED.value


def test_supervisor_list_pending_uses_pending_contract(tmp_path):
    supervisor = Supervisor(
        storage_path=tmp_path / "approvals.json",
    )

    pending_id = supervisor.request_approval({"name": "pending"})
    approved_id = supervisor.request_approval({"name": "approved"})

    supervisor.approve(approved_id)

    pending = supervisor.list_pending()

    assert list(pending) == [pending_id]
    assert pending[pending_id]["status"] == ApprovalStatus.PENDING.value
    assert approved_id not in pending
