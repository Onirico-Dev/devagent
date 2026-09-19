

def test_acquire_releases_thread_lock_when_process_lock_fails(tmp_path, monkeypatch):
    from core.approval.approval_coordinator import ApprovalCoordinator

    coordinator = ApprovalCoordinator(tmp_path)

    def fail_process_lock(_approval_id):
        raise RuntimeError("process lock failure")

    monkeypatch.setattr(
        coordinator,
        "process_lock",
        fail_process_lock,
    )

    try:
        coordinator.acquire("approval-id")
    except RuntimeError as exc:
        assert str(exc) == "process lock failure"
    else:
        raise AssertionError("RuntimeError esperado")

    thread_lock = coordinator._lock_for("approval-id")

    assert thread_lock.acquire(blocking=False)
    thread_lock.release()
