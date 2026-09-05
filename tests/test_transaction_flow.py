from types import SimpleNamespace

import pytest

from core.engine.transaction_flow import TransactionFlow
from core.memory.task_history import TaskHistoryStatus
from core.schemas.models import TransactionStatus


class FakeRepairState:
    def __init__(self):
        self.attempts = 0
        self.status = "initial"
        self.persisted = 0

    def persist(self, transaction):
        self.persisted += 1
        transaction.repair_state = {
            "status": self.status,
            "attempts": self.attempts,
        }

    def mark_testing(self):
        self.status = "testing"

    def mark_committed(self):
        self.status = "committed"

    def mark_rolled_back(self, error=""):
        self.status = "rolled_back"
        self.error = error

    def mark_failed(self, error):
        self.status = "failed"
        self.error = error


class FakeController:
    def __init__(self):
        self.started = []
        self.reset_calls = []

    def start(self, transaction_id):
        self.started.append(transaction_id)

    def reset(self, transaction_id):
        self.reset_calls.append(transaction_id)


class FakeHistory:
    def __init__(self):
        self.items = {}
        self.created = []

    def get(self, approval_id):
        return self.items.get(approval_id)

    def create(self, **kwargs):
        self.created.append(kwargs)
        self.items[kwargs["approval_id"]] = kwargs


class FakeSupervisor:
    def __init__(self, request):
        self.request = request
        self.approved = []
        self.prepared = []

    def prepare_approval(self, approval_id):
        self.prepared.append(approval_id)
        return self.request

    def approve(self, approval_id):
        self.approved.append(approval_id)


class FakeAgent:
    def __init__(self, transaction):
        self.transaction = transaction
        self.calls = []

    def build_transaction_from_approved_plan(self, plan):
        self.calls.append(plan)
        return self.transaction


class FakeTransactions:
    def __init__(self):
        self.begin_calls = []
        self.registered = []
        self.backups = []
        self.rollback_calls = []
        self.persisted = []

    def begin(self, transaction):
        self.begin_calls.append(transaction)
        return transaction

    def register_created(self, transaction, path):
        self.registered.append((transaction, path))

    def backup_file(self, transaction, path):
        self.backups.append((transaction, path))

    def rollback(self, transaction):
        self.rollback_calls.append(transaction)

    def persist_manifest(self, transaction):
        self.persisted.append(transaction)


class FakeSecurity:
    def __init__(self):
        self.paths = []

    def validate_path(self, path):
        self.paths.append(path)


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, transaction):
        self.calls.append(transaction)


class FakeTests:
    def __init__(self, result=None, semantic_result=None):
        self.result = result or {"success": True}
        self.semantic_result = semantic_result or {"success": True}
        self.run_calls = []
        self.semantic_calls = []

    def run(self, paths):
        self.run_calls.append(paths)
        return dict(self.result)

    def run_tests(self, paths):
        self.semantic_calls.append(paths)
        return dict(self.semantic_result)


class FakeGit:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def commit_transaction(self, transaction_id, instruction, paths):
        self.calls.append(
            (transaction_id, instruction, paths)
        )
        return self.result


class FakeRepairFlow:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(
        self,
        *,
        instruction,
        transaction,
        test_result,
        repair_state,
    ):
        self.calls.append(
            {
                "instruction": instruction,
                "transaction": transaction,
                "test_result": test_result,
                "repair_state": repair_state,
            }
        )
        return self.result


def make_transaction(
    *,
    changes=None,
    metadata=None,
):
    changes = changes or [
        SimpleNamespace(
            path="app.py",
            change_type=SimpleNamespace(value="create"),
        )
    ]

    return SimpleNamespace(
        transaction_id="tx-1",
        changes=changes,
        metadata=metadata or {},
        status=TransactionStatus.EXECUTING,
        repair_state={},
    )


_UNSET = object()


def make_flow(
    *,
    transaction=None,
    test_result=None,
    semantic_result=None,
    git_result=_UNSET,
    repair_result=None,
):
    transaction = transaction or make_transaction()

    request = {
        "plan": {
            "instruction": "criar app.py",
        }
    }

    supervisor = FakeSupervisor(request)
    security = FakeSecurity()
    executor = FakeExecutor()
    transactions = FakeTransactions()
    tests = FakeTests(
        result=test_result,
        semantic_result=semantic_result,
    )
    if git_result is _UNSET:
        git_result = {
            "status": "committed",
            "commit": "abc123",
        }

    git = FakeGit(git_result)
    controller = FakeController()
    history = FakeHistory()
    repair_flow = FakeRepairFlow(
        repair_result
        or {
            "success": True,
            "tests": {"success": True},
            "repair": {"action": "fixed"},
        }
    )
    repair_state = FakeRepairState()

    history_updates = []

    def history_update(*args, **kwargs):
        history_updates.append((args, kwargs))

    def restore_state(tx):
        tx._repair_state = repair_state
        return repair_state

    def repair_cycle(**kwargs):
        return repair_flow(**kwargs)

    flow = TransactionFlow(
        agent=FakeAgent(transaction),
        supervisor=supervisor,
        security=security,
        executor=executor,
        transactions=transactions,
        tests=tests,
        git=git,
        repair_controller=controller,
        repair_flow=repair_flow,
        history=history,
        history_update_fn=history_update,
        restore_repair_state_fn=restore_state,
        repair_cycle_fn=repair_cycle,
    )

    return SimpleNamespace(
        flow=flow,
        transaction=transaction,
        supervisor=supervisor,
        security=security,
        executor=executor,
        transactions=transactions,
        tests=tests,
        git=git,
        controller=controller,
        history=history,
        repair_state=repair_state,
        history_updates=history_updates,
    )


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, "rollback"),
        ({}, "repair"),
        ({"success": False}, "repair"),
        (
            {
                "success": True,
                "verification": "invalid",
            },
            "repair",
        ),
        (
            {
                "success": True,
                "tests": "invalid",
            },
            "repair",
        ),
        (
            {
                "success": True,
                "verification": {"success": True},
                "tests": {"success": False},
            },
            "repair",
        ),
        (
            {
                "success": True,
                "verification": {"success": True},
                "tests": {"success": True},
            },
            "commit",
        ),
    ],
)
def test_evaluate_execution(result, expected):
    ctx = make_flow()
    assert ctx.flow.evaluate_execution(result) == expected


def test_commit_transaction_commits_only_after_git_success():
    ctx = make_flow()

    result = ctx.flow.commit_transaction(
        approval_id="approval-1",
        instruction="criar app.py",
        transaction=ctx.transaction,
        test_result={"success": True},
        repair_state=ctx.repair_state,
    )

    assert result["status"] == TransactionStatus.COMMITTED.value
    assert ctx.transaction.status == TransactionStatus.COMMITTED
    assert ctx.repair_state.status == "committed"
    assert ctx.controller.reset_calls == ["tx-1"]
    assert ctx.git.calls == [
        ("tx-1", "criar app.py", ["app.py"])
    ]


def test_commit_transaction_rejects_invalid_git_result():
    for invalid in (None, [], "invalid"):
        ctx = make_flow(git_result=invalid)

        with pytest.raises(
            RuntimeError,
            match="Resultado de commit Git inválido.",
        ):
            ctx.flow.commit_transaction(
                approval_id="approval-1",
                instruction="criar app.py",
                transaction=ctx.transaction,
                test_result={"success": True},
                repair_state=ctx.repair_state,
            )

        assert ctx.transaction.status != TransactionStatus.COMMITTED
        assert ctx.repair_state.status != "committed"


def test_commit_transaction_rejects_git_failure():
    ctx = make_flow(
        git_result={
            "status": "failed",
            "message": "COMMIT_FAILURE_TEST",
        }
    )

    with pytest.raises(
        RuntimeError,
        match="COMMIT_FAILURE_TEST",
    ):
        ctx.flow.commit_transaction(
            approval_id="approval-1",
            instruction="criar app.py",
            transaction=ctx.transaction,
            test_result={"success": True},
            repair_state=ctx.repair_state,
        )


def test_rollback_transaction_success():
    ctx = make_flow()

    result = ctx.flow.rollback_transaction(
        approval_id="approval-1",
        transaction=ctx.transaction,
        repair_state=ctx.repair_state,
        test_result={"success": False},
        repair={"action": "failed"},
        error="test failure",
    )

    assert result["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert result["success"] is False
    assert result["transaction_id"] == "tx-1"
    assert ctx.transactions.rollback_calls == [
        ctx.transaction
    ]
    assert ctx.repair_state.status == "rolled_back"
    assert ctx.controller.reset_calls == ["tx-1"]


def test_rollback_transaction_failure():
    ctx = make_flow()

    def fail_rollback(transaction):
        raise RuntimeError("ROLLBACK_FAILURE")

    ctx.transactions.rollback = fail_rollback

    result = ctx.flow.rollback_transaction(
        approval_id="approval-1",
        transaction=ctx.transaction,
        repair_state=ctx.repair_state,
        error="original failure",
    )

    assert result["status"] == TaskHistoryStatus.FAILED.value
    assert result["rollback_error"] == "ROLLBACK_FAILURE"
    assert ctx.transaction.status == TransactionStatus.FAILED
    assert ctx.repair_state.status == "failed"


def test_approve_locked_commits_when_initial_tests_pass():
    ctx = make_flow(
        test_result={"success": True}
    )

    commit_calls = []

    def commit_fn(**kwargs):
        commit_calls.append(kwargs)
        return {
            "status": "committed",
            "transaction_id": "tx-1",
        }

    def rollback_fn(**kwargs):
        raise AssertionError("rollback não deveria ocorrer")

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=commit_fn,
        rollback_fn=rollback_fn,
    )

    assert result["status"] == "committed"
    assert ctx.supervisor.approved == ["approval-1"]
    assert ctx.executor.calls == [ctx.transaction]
    assert commit_calls[0]["transaction"] is ctx.transaction


def test_approve_locked_runs_repair_after_test_failure():
    ctx = make_flow(
        test_result={"success": False}
    )

    commit_calls = []
    repair_calls = []

    def commit_fn(**kwargs):
        commit_calls.append(kwargs)
        return {"status": "committed"}

    def rollback_fn(**kwargs):
        raise AssertionError("rollback não deveria ocorrer")

    def repair_fn(**kwargs):
        repair_calls.append(kwargs)
        return {
            "success": True,
            "tests": {"success": True},
            "repair": {"action": "fixed"},
        }

    ctx.flow._repair_cycle = repair_fn

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=commit_fn,
        rollback_fn=rollback_fn,
    )

    assert result["status"] == "committed"
    assert len(repair_calls) == 1
    assert len(commit_calls) == 1


def test_approve_locked_rolls_back_after_repair_failure():
    ctx = make_flow(
        test_result={"success": False}
    )

    rollback_calls = []

    def commit_fn(**kwargs):
        raise AssertionError("commit não deveria ocorrer")

    def rollback_fn(**kwargs):
        rollback_calls.append(kwargs)
        return {
            "status": "rolled_back",
            "success": False,
        }

    ctx.flow._repair_cycle = lambda **kwargs: {
        "success": False,
        "tests": {"success": False},
        "repair": {"status": "failed"},
        "error": "REPAIR_FAILED",
    }

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=commit_fn,
        rollback_fn=rollback_fn,
    )

    assert result["status"] == "rolled_back"
    assert len(rollback_calls) == 1


def test_approve_locked_runs_declared_semantic_tests():
    transaction = make_transaction(
        metadata={"tests": ["tests/test_app.py"]}
    )

    ctx = make_flow(
        transaction=transaction,
        test_result={"success": True},
        semantic_result={"success": True},
    )

    commit_calls = []

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=lambda **kwargs: (
            commit_calls.append(kwargs)
            or {"status": "committed"}
        ),
        rollback_fn=lambda **kwargs: {
            "status": "rolled_back"
        },
    )

    assert result["status"] == "committed"
    assert ctx.tests.semantic_calls == [
        ["tests/test_app.py"]
    ]


def test_approve_locked_semantic_failure_enters_repair():
    transaction = make_transaction(
        metadata={"tests": ["tests/test_app.py"]}
    )

    ctx = make_flow(
        transaction=transaction,
        test_result={"success": True},
        semantic_result={"success": False},
    )

    ctx.flow._repair_cycle = lambda **kwargs: {
        "success": False,
        "tests": {"success": False},
        "repair": None,
        "error": "SEMANTIC_FAILURE",
    }

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=lambda **kwargs: {
            "status": "committed"
        },
        rollback_fn=lambda **kwargs: {
            "status": "rolled_back",
            "success": False,
        },
    )

    assert result["status"] == "rolled_back"


def test_approve_locked_preserves_existing_history():
    ctx = make_flow()

    ctx.history.items["approval-1"] = {
        "approval_id": "approval-1"
    }

    ctx.flow.approve_locked(
        "approval-1",
        commit_fn=lambda **kwargs: {
            "status": "committed"
        },
        rollback_fn=lambda **kwargs: {
            "status": "rolled_back"
        },
    )

    assert ctx.history.created == []


def test_approve_locked_build_failure_happens_before_transaction_begin():
    ctx = make_flow()

    original = ctx.flow.agent.build_transaction_from_approved_plan

    def fail(plan):
        raise RuntimeError("BUILD_FAILURE")

    ctx.flow.agent.build_transaction_from_approved_plan = fail

    with pytest.raises(RuntimeError, match="BUILD_FAILURE"):
        ctx.flow.approve_locked(
            "approval-1",
            commit_fn=lambda **kwargs: None,
            rollback_fn=lambda **kwargs: None,
        )

    assert ctx.transactions.begin_calls == []
    assert ctx.supervisor.approved == []


def test_approve_locked_begin_failure_happens_before_supervisor_approval():
    ctx = make_flow()

    def fail(transaction):
        raise RuntimeError("BEGIN_FAILURE")

    ctx.transactions.begin = fail

    with pytest.raises(RuntimeError, match="BEGIN_FAILURE"):
        ctx.flow.approve_locked(
            "approval-1",
            commit_fn=lambda **kwargs: None,
            rollback_fn=lambda **kwargs: None,
        )

    assert ctx.supervisor.approved == []


def test_approve_locked_rolls_back_unexpected_exception():
    ctx = make_flow()

    def fail(transaction):
        raise RuntimeError("EXECUTION_FAILURE")

    ctx.executor.execute = fail

    rollback_calls = []

    def rollback_fn(**kwargs):
        rollback_calls.append(kwargs)
        return {
            "status": "failed",
            "rollback_error": "SECONDARY_FAILURE",
        }

    with pytest.raises(
        RuntimeError,
        match="SECONDARY_FAILURE",
    ):
        ctx.flow.approve_locked(
            "approval-1",
            commit_fn=lambda **kwargs: None,
            rollback_fn=rollback_fn,
        )

    assert len(rollback_calls) == 1

def test_commit_transaction_records_repair_metadata():
    ctx = make_flow()

    result = ctx.flow.commit_transaction(
        approval_id="approval-1",
        instruction="fix",
        transaction=ctx.transaction,
        test_result={"success": True},
        repair_state=ctx.repair_state,
        repair={"attempt": 1, "status": "verified"},
    )

    assert result["status"] == "committed"
    assert result["repair"] == {
        "attempt": 1,
        "status": "verified",
    }
    assert ctx.history_updates
    history_call = ctx.history_updates[-1]
    assert history_call[0] == ("approval-1",)
    assert history_call[1]["status"] == "committed"
    assert history_call[1]["extra"]["repair"] == {
        "attempt": 1,
        "status": "verified",
    }


def test_prepare_transaction_backs_up_existing_file():
    ctx = make_flow()

    change = ctx.transaction.changes[0]
    original_change_type = change.change_type

    try:
        change.change_type = SimpleNamespace(value="modify")
        ctx.flow._prepare_transaction(ctx.transaction)
    finally:
        change.change_type = original_change_type

    assert ctx.transactions.backups == [
        (ctx.transaction, change.path)
    ]


def test_approve_locked_commit_error_preserves_rollback_result():
    ctx = make_flow()

    class CommitFailure(RuntimeError):
        def __init__(self, message):
            super().__init__(message)
            self.result = {"git": {"status": "failed"}}

    ctx.flow.commit_error_type = CommitFailure

    def commit_fn(**kwargs):
        raise CommitFailure("commit failure")

    def rollback_fn(**kwargs):
        return {
            "status": "rolled_back",
            "success": False,
            "transaction_id": ctx.transaction.transaction_id,
        }

    try:
        ctx.flow.approve_locked(
            "approval-1",
            commit_fn=commit_fn,
            rollback_fn=rollback_fn,
        )
    except CommitFailure as error:
        assert error.result["git"] == {"status": "failed"}
        assert "rollback" in error.result
        assert error.result["rollback"]["status"] == "rolled_back"
    else:
        raise AssertionError("CommitFailure deveria ter sido propagado")


def test_approve_locked_unexpected_exception_with_rollback_failure_raises():
    ctx = make_flow()

    def rollback_fn(**kwargs):
        return {
            "status": "failed",
            "success": False,
            "transaction_id": ctx.transaction.transaction_id,
            "rollback_error": "SECONDARY_FAILURE",
        }

    def commit_fn(**kwargs):
        raise ValueError("unexpected failure")

    try:
        ctx.flow.approve_locked(
            "approval-1",
            commit_fn=commit_fn,
            rollback_fn=rollback_fn,
        )
    except RuntimeError as error:
        assert str(error) == "SECONDARY_FAILURE"
    else:
        raise AssertionError(
            "RuntimeError deveria ser levantado quando o rollback falha"
        )


def test_approve_locked_unexpected_exception_returns_rollback_result():
    ctx = make_flow()

    def rollback_fn(**kwargs):
        return {
            "status": "failed",
            "success": False,
            "transaction_id": ctx.transaction.transaction_id,
        }

    def commit_fn(**kwargs):
        raise ValueError("unexpected failure")

    result = ctx.flow.approve_locked(
        "approval-1",
        commit_fn=commit_fn,
        rollback_fn=rollback_fn,
    )

    assert result["status"] == "failed"
    assert result["success"] is False
    assert result["transaction_id"] == ctx.transaction.transaction_id
