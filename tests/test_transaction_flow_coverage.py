from types import SimpleNamespace

import pytest

from core.engine.transaction_flow import TransactionFlow
from core.memory.task_history import TaskHistoryStatus
from core.schemas.models import ChangeType, TransactionStatus


class State:
    def __init__(self, attempts=0):
        self.attempts = attempts
        self.status = "initial"
        self.persist_count = 0

    def persist(self, transaction):
        self.persist_count += 1
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


class Controller:
    def __init__(self):
        self.started = []
        self.reset_calls = []

    def start(self, tx):
        self.started.append(tx)

    def reset(self, tx):
        self.reset_calls.append(tx)


class Supervisor:
    def __init__(self, request=None):
        self.request = request or {"plan": {"instruction": "fazer"}}
        self.approved = []

    def prepare_approval(self, approval_id):
        return self.request

    def approve(self, approval_id):
        self.approved.append(approval_id)


class History:
    def __init__(self, existing=None):
        self.items = {} if existing is None else existing
        self.created = []

    def get(self, key):
        return self.items.get(key)

    def create(self, **kwargs):
        self.created.append(kwargs)
        self.items[kwargs["approval_id"]] = kwargs


class Transactions:
    def __init__(self):
        self.begun = []
        self.registered = []
        self.backups = []
        self.rollbacks = []
        self.manifests = []

    def begin(self, tx):
        self.begun.append(tx)
        return tx

    def register_created(self, tx, path):
        self.registered.append((tx, path))

    def backup_file(self, tx, path):
        self.backups.append((tx, path))

    def rollback(self, tx):
        self.rollbacks.append(tx)

    def persist_manifest(self, tx):
        self.manifests.append(tx)


class Security:
    def __init__(self):
        self.paths = []

    def validate_path(self, path):
        self.paths.append(path)


class Executor:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def execute(self, tx):
        self.calls.append(tx)
        if self.error:
            raise self.error


class FakeTestRunner:
    def __init__(self, result=None, semantic=None):
        self.result = {"success": True} if result is None else result
        self.semantic = {"success": True} if semantic is None else semantic
        self.run_calls = []
        self.declared_calls = []

    def run(self, paths):
        self.run_calls.append(paths)
        return dict(self.result)

    def run_tests(self, paths):
        self.declared_calls.append(paths)
        return dict(self.semantic)


class Git:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def commit_transaction(self, transaction_id, instruction, paths):
        self.calls.append((transaction_id, instruction, paths))
        return self.result


class Agent:
    def __init__(self, tx):
        self.tx = tx

    def build_transaction_from_approved_plan(self, plan):
        return self.tx


def tx(*, changes=None, metadata=None):
    if changes is None:
        changes = [
            SimpleNamespace(
                path="a.py",
                change_type=SimpleNamespace(value="create"),
            )
        ]
    return SimpleNamespace(
        transaction_id="tx-1",
        changes=changes,
        metadata={} if metadata is None else metadata,
        status=TransactionStatus.EXECUTING,
        repair_state={},
    )


def build(
    *,
    transaction=None,
    test_result=None,
    semantic_result=None,
    git_result=None,
    repair_result=None,
    executor_error=None,
):
    transaction = transaction or tx()
    supervisor = Supervisor()
    security = Security()
    executor = Executor(executor_error)
    transactions = Transactions()
    tests = FakeTestRunner(test_result, semantic_result)
    git = Git(
        {"status": "committed", "commit": "abc"}
        if git_result is None
        else git_result
    )
    controller = Controller()
    history = History()
    state = State()
    updates = []

    repair_result = (
        {
            "success": True,
            "tests": {"success": True},
            "repair": {"action": "fixed"},
        }
        if repair_result is None
        else repair_result
    )

    class Repair:
        def __init__(self):
            self.calls = []

        def run(self, **kwargs):
            self.calls.append(kwargs)
            return repair_result

        def __call__(self, **kwargs):
            return self.run(**kwargs)

    repair = Repair()

    def update(*args, **kwargs):
        updates.append((args, kwargs))

    def restore(txn):
        return state

    flow = TransactionFlow(
        agent=Agent(transaction),
        supervisor=supervisor,
        security=security,
        executor=executor,
        transactions=transactions,
        tests=tests,
        git=git,
        repair_controller=controller,
        repair_flow=repair,
        history=history,
        history_update_fn=update,
        restore_repair_state_fn=restore,
    )

    return flow, {
        "tx": transaction,
        "supervisor": supervisor,
        "security": security,
        "executor": executor,
        "transactions": transactions,
        "tests": tests,
        "git": git,
        "controller": controller,
        "history": history,
        "state": state,
        "updates": updates,
        "repair": repair,
    }


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, "rollback"),
        ("bad", "rollback"),
        ({}, "repair"),
        ({"success": False}, "repair"),
        ({"success": True, "verification": None}, "commit"),
        ({"success": True, "verification": {}}, "repair"),
        ({"success": True, "verification": {"success": True}}, "commit"),
        ({"success": True, "tests": {}}, "repair"),
        ({"success": True, "tests": {"success": True}}, "commit"),
    ],
)
def test_evaluate_execution_branches(result, expected):
    flow, _ = build()
    assert flow.evaluate_execution(result) == expected


def test_build_transaction_and_prepare_create():
    flow, data = build()
    transaction = data["tx"]

    built = flow._build_transaction({"instruction": "x"})
    flow._prepare_transaction(transaction)

    assert built is transaction
    assert data["security"].paths == ["a.py"]
    assert len(data["transactions"].registered) == 1
    assert data["transactions"].backups == []


def test_prepare_modify_uses_backup():
    change = SimpleNamespace(
        path="b.py",
        change_type=SimpleNamespace(value="modify"),
    )
    transaction = tx(changes=[change])
    flow, data = build(transaction=transaction)

    flow._prepare_transaction(transaction)

    assert data["transactions"].backups == [(transaction, "b.py")]
    assert data["transactions"].registered == []


def test_run_declared_tests_success_combines_output():
    flow, data = build(
        transaction=tx(metadata={"tests": ["test_x.py"]}),
        test_result={
            "success": True,
            "returncode": 0,
            "stdout": "base",
            "stderr": "",
        },
        semantic_result={
            "success": True,
            "returncode": 0,
            "stdout": "semantic",
            "stderr": "warning",
        },
    )

    result = flow._run_declared_tests(
        data["tx"],
        {"success": True, "returncode": 0, "stdout": "base", "stderr": ""},
    )

    assert result["success"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "base\nsemantic"
    assert result["stderr"] == "warning"
    assert data["tests"].declared_calls == [["test_x.py"]]


def test_run_declared_tests_semantic_failure():
    flow, data = build(
        transaction=tx(metadata={"tests": ["test_x.py"]}),
        semantic_result={
            "success": False,
            "returncode": 7,
            "stdout": "semantic out",
            "stderr": "semantic err",
        },
    )

    result = flow._run_declared_tests(
        data["tx"],
        {"success": True, "returncode": 0, "stdout": "", "stderr": ""},
    )

    assert result["success"] is False
    assert result["returncode"] == 7
    assert result["stdout"] == "semantic out"
    assert result["stderr"] == "semantic err"


def test_run_declared_tests_without_declared_tests_returns_original():
    flow, data = build(transaction=tx(metadata={}))
    original = {"success": False, "stderr": "x"}

    assert flow._run_declared_tests(data["tx"], original) is original


def test_run_declared_tests_does_not_run_semantic_when_base_fails():
    flow, data = build(
        transaction=tx(metadata={"tests": ["test_x.py"]}),
        test_result={"success": False, "stderr": "base"},
    )

    original = {"success": False, "stderr": "base"}
    assert flow._run_declared_tests(data["tx"], original) is original
    assert data["tests"].declared_calls == []


def test_commit_transaction_success_without_repair():
    flow, data = build()
    result = flow.commit_transaction(
        approval_id="a1",
        instruction="fazer",
        transaction=data["tx"],
        test_result={"success": True},
        repair_state=data["state"],
    )

    assert result["status"] == "committed"
    assert result["transaction_id"] == "tx-1"
    assert "repair" not in result
    assert data["tx"].status == TransactionStatus.COMMITTED
    assert data["state"].status == "committed"
    assert data["controller"].reset_calls == ["tx-1"]
    assert data["git"].calls == [("tx-1", "fazer", ["a.py"])]


def test_commit_transaction_success_with_repair():
    flow, data = build()
    repair = {"action": "fixed"}

    result = flow.commit_transaction(
        approval_id="a1",
        instruction="fazer",
        transaction=data["tx"],
        test_result={"success": True},
        repair_state=data["state"],
        repair=repair,
    )

    assert result["repair"] == repair


@pytest.mark.parametrize(
    "git_result",
    [
        [],
        {"status": "rolled_back", "message": "não commitou"},
    ],
)
def test_commit_transaction_rejects_invalid_git_result(git_result):
    flow, data = build(git_result=git_result)

    with pytest.raises(RuntimeError) as exc:
        flow.commit_transaction(
            "a1",
            "fazer",
            data["tx"],
            {"success": True},
            data["state"],
        )

    assert hasattr(exc.value, "result")
    assert data["tx"].status == TransactionStatus.EXECUTING


def test_commit_transaction_uses_custom_commit_error_type():
    class CommitError(Exception):
        pass

    flow, data = build()
    flow.commit_error_type = CommitError

    data["git"].result = {"status": "failed", "message": "erro"}

    with pytest.raises(CommitError) as exc:
        flow.commit_transaction(
            "a1",
            "fazer",
            data["tx"],
            {"success": True},
            data["state"],
        )

    assert exc.value.result["status"] == "failed"


def test_rollback_success():
    flow, data = build()
    result = flow.rollback_transaction(
        approval_id="a1",
        transaction=data["tx"],
        repair_state=data["state"],
        test_result={"success": False},
        repair={"action": "bad"},
        error="erro",
    )

    assert result["success"] is False
    assert result["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert result["error"] == "erro"
    assert data["state"].status == "rolled_back"
    assert data["transactions"].rollbacks == [data["tx"]]
    assert data["controller"].reset_calls == ["tx-1"]


def test_rollback_failure_marks_failed_and_changes_status():
    class BadTransactions(Transactions):
        def rollback(self, tx):
            raise RuntimeError("rollback quebrado")

    flow, data = build()
    bad = BadTransactions()
    flow.transactions = bad

    result = flow.rollback_transaction(
        approval_id="a1",
        transaction=data["tx"],
        repair_state=data["state"],
        status=TaskHistoryStatus.ROLLED_BACK.value,
    )

    assert result["status"] == TaskHistoryStatus.FAILED.value
    assert result["rollback_error"] == "rollback quebrado"
    assert data["state"].status == "failed"


def test_attempt_rollback_returns_none_on_success():
    flow, data = build()
    assert flow._attempt_rollback(data["tx"]) is None


def test_attempt_rollback_returns_exception():
    flow, data = build()

    class Bad(Transactions):
        def rollback(self, tx):
            raise ValueError("x")

    flow.transactions = Bad()
    error = flow._attempt_rollback(data["tx"])

    assert isinstance(error, ValueError)
    assert str(error) == "x"


def test_build_rollback_extra_all_optional_fields():
    flow, data = build()
    extra, attempts = flow._build_rollback_extra(
        data["tx"],
        data["state"],
        {"success": False},
        {"action": "fix"},
        ValueError("x"),
        RuntimeError("rollback"),
    )

    assert attempts == 0
    assert extra["tests"] == {"success": False}
    assert extra["repair"] == {"action": "fix"}
    assert extra["error"] == "x"
    assert extra["rollback_error"] == "rollback"


def test_build_rollback_extra_without_optional_fields():
    flow, data = build()
    extra, attempts = flow._build_rollback_extra(
        data["tx"],
        data["state"],
        None,
        None,
        None,
        None,
    )

    assert attempts == 0
    assert "tests" not in extra
    assert "repair" not in extra
    assert "error" not in extra
    assert "rollback_error" not in extra


def test_finalize_rollback_status():
    flow, _ = build()
    assert (
        flow._finalize_rollback_status("rolled_back", None)
        == "rolled_back"
    )
    assert (
        flow._finalize_rollback_status(
            "rolled_back", RuntimeError("x")
        )
        == "failed"
    )


def test_build_rollback_result_without_errors():
    flow, data = build()
    result = flow._build_rollback_result(
        "a1",
        "rolled_back",
        data["tx"],
        {"success": False},
        None,
        0,
        None,
        None,
    )

    assert result["success"] is False
    assert "error" not in result
    assert "rollback_error" not in result


def test_handle_non_commit_exception_returns_rollback_result():
    flow, data = build()

    result = flow._handle_transaction_exception(
        error=ValueError("execução"),
        approval_id="a1",
        transaction=data["tx"],
        repair_state=data["state"],
        rollback_fn=flow.rollback_transaction,
    )

    assert result["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert result["error"] == "execução"


def test_handle_commit_exception_rolls_back_and_reraises():
    flow, data = build()

    class CommitError(RuntimeError):
        pass

    flow.commit_error_type = CommitError
    error = CommitError("commit falhou")
    error.result = {}

    try:
        raise error
    except CommitError as active_error:
        with pytest.raises(CommitError) as exc:
            flow._handle_transaction_exception(
                error=active_error,
                approval_id="a1",
                transaction=data["tx"],
                repair_state=data["state"],
                rollback_fn=flow.rollback_transaction,
            )

    assert exc.value is error
    assert error.result["rollback"]["status"] == "rolled_back"

def test_handle_commit_exception_raises_when_rollback_fails():
    flow, data = build()

    class CommitError(RuntimeError):
        pass

    flow.commit_error_type = CommitError

    def rollback(**kwargs):
        return {"rollback_error": "rollback falhou"}

    with pytest.raises(RuntimeError, match="rollback falhou"):
        flow._handle_transaction_exception(
            error=CommitError("commit"),
            approval_id="a1",
            transaction=data["tx"],
            repair_state=data["state"],
            rollback_fn=rollback,
        )


def test_handle_normal_exception_raises_when_rollback_fails():
    flow, data = build()

    def rollback(**kwargs):
        return {"rollback_error": "rollback falhou"}

    with pytest.raises(RuntimeError, match="rollback falhou"):
        flow._handle_transaction_exception(
            error=ValueError("execução"),
            approval_id="a1",
            transaction=data["tx"],
            repair_state=data["state"],
            rollback_fn=rollback,
        )


def test_finalize_execution_result_commits_directly():
    flow, data = build()

    result = flow._finalize_execution_result(
        "a1",
        "fazer",
        data["tx"],
        data["state"],
        {"success": True},
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"


def test_finalize_execution_result_uses_repair_cycle():
    flow, data = build(
        repair_result={
            "success": True,
            "tests": {"success": True},
            "repair": {"action": "fixed"},
        }
    )

    result = flow._finalize_execution_result(
        "a1",
        "fazer",
        data["tx"],
        data["state"],
        {"success": False},
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"
    assert result["repair"] == {"action": "fixed"}
    assert len(data["repair"].calls) == 1


def test_finalize_execution_result_uses_repair_flow_fallback():
    flow, data = build(
        repair_result={
            "success": True,
            "tests": {"success": True},
            "repair": None,
        }
    )
    flow._repair_cycle = None

    result = flow._finalize_execution_result(
        "a1",
        "fazer",
        data["tx"],
        data["state"],
        {"success": False},
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"


def test_finalize_execution_result_rolls_back_after_failed_repair():
    flow, data = build(
        repair_result={
            "success": False,
            "tests": {"success": False},
            "repair": {"action": "failed"},
            "error": "não corrigido",
        }
    )

    result = flow._finalize_execution_result(
        "a1",
        "fazer",
        data["tx"],
        data["state"],
        {"success": False},
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert result["error"] == "não corrigido"


def test_execute_and_test_transaction_full_path():
    flow, data = build(
        transaction=tx(metadata={"tests": ["test_x.py"]}),
        test_result={"success": True, "stdout": "ok"},
    )

    result = flow._execute_and_test_transaction(
        data["tx"],
        data["state"],
        "a1",
    )

    assert result["success"] is True
    assert data["executor"].calls == [data["tx"]]
    assert data["state"].status == "testing"
    assert data["tx"].status == TransactionStatus.TESTING
    assert data["tests"].run_calls == [["a.py"]]
    assert data["tests"].declared_calls == [["test_x.py"]]


def test_approve_locked_success():
    flow, data = build(
        transaction=tx(metadata={"tests": []}),
        test_result={"success": True},
    )

    result = flow.approve_locked(
        "approval-1",
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"
    assert data["history"].created
    assert data["supervisor"].approved == ["approval-1"]
    assert data["controller"].started == ["tx-1"]


def test_approve_locked_reuses_existing_history():
    flow, data = build()
    data["history"].items["approval-1"] = {"existing": True}

    result = flow.approve_locked(
        "approval-1",
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"
    assert data["history"].created == []


def test_approve_locked_uses_repair_state_fallback():
    flow, data = build()
    flow._restore_repair_state = None

    class RepairFlow:
        def restore_state(self, transaction):
            return data["state"]

        def __call__(self, **kwargs):
            return {"success": True, "tests": {"success": True}}

    flow.repair_flow = RepairFlow()

    result = flow.approve_locked(
        "approval-1",
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == "committed"


def test_approve_locked_handles_execution_exception():
    flow, data = build(executor_error=ValueError("executor"))

    result = flow.approve_locked(
        "approval-1",
        flow.commit_transaction,
        flow.rollback_transaction,
    )

    assert result["status"] == TaskHistoryStatus.FAILED.value

    execution = data["tx"].metadata["execution"]
    assert execution["phase"] == "executing"
    assert execution["changes_applied"] == 0


def test_approve_locked_commit_exception_path():
    class CommitError(RuntimeError):
        pass

    flow, data = build()
    flow.commit_error_type = CommitError

    def commit(**kwargs):
        error = CommitError("git")
        error.result = {}
        raise error

    with pytest.raises(CommitError):
        flow.approve_locked(
            "approval-1",
            commit,
            flow.rollback_transaction,
        )


def test_approve_locked_commit_exception_with_rollback_failure():
    class CommitError(RuntimeError):
        pass

    flow, data = build()
    flow.commit_error_type = CommitError

    def commit(**kwargs):
        raise CommitError("git")

    def rollback(**kwargs):
        return {"rollback_error": "rollback"}

    with pytest.raises(RuntimeError, match="rollback"):
        flow.approve_locked(
            "approval-1",
            commit,
            rollback,
        )
