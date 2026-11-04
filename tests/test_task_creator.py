from core.task.task_creator import TaskCreator


def test_plans_equal_when_plans_are_identical():
    plan = {
        "objective": "teste",
        "changes": [
            {
                "change_type": "create",
                "path": "app.py",
                "content": "print('ok')",
                "reason": "teste",
            }
        ],
        "tests": [],
        "risks": [],
    }

    assert TaskCreator._plans_equal(plan, plan.copy()) is True


def test_plans_equal_rejects_stale_plan():
    old_plan = {
        "objective": "criar arquivos",
        "changes": [
            {
                "change_type": "create",
                "path": "test_calculator.py",
                "content": "old",
                "reason": "teste",
            }
        ],
        "tests": [],
        "risks": [],
    }

    new_plan = {
        "objective": "criar arquivos",
        "changes": [
            {
                "change_type": "create",
                "path": "calculator.py",
                "content": "def add(a, b):\n    return a + b\n",
                "reason": "teste",
            },
            {
                "change_type": "create",
                "path": "test_calculator.py",
                "content": "from calculator import add\n",
                "reason": "teste",
            },
        ],
        "tests": [],
        "risks": [],
    }

    assert TaskCreator._plans_equal(old_plan, new_plan) is False

from unittest.mock import Mock

import pytest

from core.task.task_creator import TaskCreator


def make_plan(
    *,
    change_type="create",
    path="app.py",
    content="print('ok')",
):
    change = {
        "change_type": change_type,
        "path": path,
    }

    if change_type != "delete":
        change["content"] = content

    return {
        "objective": "teste",
        "changes": [change],
        "tests": [],
        "risks": [],
    }


@pytest.fixture
def creator():
    security = Mock()
    history = Mock()
    supervisor = Mock()

    return TaskCreator(
        security=security,
        history=history,
        supervisor=supervisor,
    )


def test_validate_plan_rejects_non_dict(creator):
    with pytest.raises(ValueError, match="Plano inválido"):
        creator.validate_plan(None)


def test_validate_plan_rejects_missing_changes(creator):
    with pytest.raises(ValueError, match="lista de alterações"):
        creator.validate_plan({})


def test_validate_plan_rejects_empty_changes(creator):
    with pytest.raises(ValueError, match="lista de alterações"):
        creator.validate_plan({"changes": []})


def test_validate_plan_rejects_invalid_change(creator):
    with pytest.raises(ValueError, match="Alteração inválida"):
        creator.validate_plan({"changes": [None]})


def test_validate_plan_rejects_missing_path(creator):
    with pytest.raises(ValueError, match="sem caminho"):
        creator.validate_plan(
            {
                "changes": [
                    {
                        "change_type": "create",
                        "content": "print('ok')",
                    }
                ]
            }
        )


def test_validate_plan_calls_security_for_path(creator):
    plan = make_plan()

    creator.validate_plan(plan)

    creator.security.validate_path.assert_called_once_with(
        "app.py"
    )


def test_validate_plan_calls_security_for_content(creator):
    plan = make_plan(
        content="print('ok')",
    )

    creator.validate_plan(plan)

    creator.security.validate_content.assert_called_once_with(
        "print('ok')"
    )


def test_validate_plan_rejects_non_string_content(creator):
    plan = make_plan(content=None)

    with pytest.raises(ValueError, match="Conteúdo inválido"):
        creator.validate_plan(plan)


def test_validate_plan_rejects_high_risk_content(creator):
    creator.security.validate_content.side_effect = PermissionError(
        "conteúdo de alto risco"
    )

    plan = make_plan(
        content="import subprocess"
    )

    with pytest.raises(PermissionError, match="alto risco"):
        creator.validate_plan(plan)


def test_validate_plan_accepts_delete_without_content(creator):
    plan = make_plan(
        change_type="delete",
        path="app.py",
    )

    creator.validate_plan(plan)

    creator.security.validate_path.assert_called_once_with(
        "app.py"
    )
    creator.security.validate_content.assert_not_called()


def test_validate_plan_propagates_blocked_path(creator):
    creator.security.validate_path.side_effect = PermissionError(
        "Caminho bloqueado"
    )

    with pytest.raises(PermissionError, match="Caminho bloqueado"):
        creator.validate_plan(make_plan())


def test_create_or_reuse_creates_new_task(creator):
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {}
    creator.supervisor.request_approval.return_value = "123"

    plan = make_plan()

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
    )

    assert result == {
        "approval_id": "123",
        "status": "pending",
        "plan": plan,
    }

    creator.supervisor.request_approval.assert_called_once_with(
        plan, instruction="crie app.py"
    )
    creator.history.create.assert_called_once_with(
        approval_id="123",
        instruction="crie app.py",
        plan=plan,
    )


def test_create_or_reuse_reuses_identical_pending_task(creator):
    plan = make_plan()

    creator.history.list_pending.return_value = [
        {
            "approval_id": "42",
            "status": "pending",
            "instruction": "crie   app.py",
            "plan": plan,
        }
    ]

    result = creator.create_or_reuse(
        "crie app.py",
        plan.copy(),
    )

    assert result == {
        "approval_id": "42",
        "status": "pending",
        "plan": plan,
    }

    creator.supervisor.request_approval.assert_not_called()
    creator.history.create.assert_not_called()


def test_create_or_reuse_does_not_reuse_different_plan(creator):
    old_plan = make_plan(
        path="old.py",
        content="old",
    )
    new_plan = make_plan(
        path="new.py",
        content="new",
    )

    creator.history.list_pending.return_value = [
        {
            "approval_id": "42",
            "status": "pending",
            "instruction": "crie app.py",
            "plan": old_plan,
        }
    ]
    creator.supervisor.request_approval.return_value = "43"

    result = creator.create_or_reuse(
        "crie app.py",
        new_plan,
    )

    assert result["approval_id"] == "43"
    creator.supervisor.request_approval.assert_called_once_with(
        new_plan, instruction="crie app.py"
    )


def test_create_or_reuse_does_not_reuse_different_instruction(creator):
    plan = make_plan()

    creator.history.list_pending.return_value = [
        {
            "approval_id": "42",
            "status": "pending",
            "instruction": "crie outro arquivo",
            "plan": plan,
        }
    ]
    creator.supervisor.request_approval.return_value = "43"

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
    )

    assert result["approval_id"] == "43"
    creator.supervisor.request_approval.assert_called_once_with(
        plan, instruction="crie app.py"
    )


def test_create_or_reuse_ignores_pending_task_with_invalid_instruction(
    creator,
):
    plan = make_plan()

    creator.history.list_pending.return_value = [
        {
            "approval_id": "42",
            "status": "pending",
            "instruction": None,
            "plan": plan,
        }
    ]
    creator.supervisor.request_approval.return_value = "43"

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
    )

    assert result["approval_id"] == "43"


def test_create_or_reuse_normalizes_instruction_whitespace(creator):
    plan = make_plan()

    creator.history.list_pending.return_value = [
        {
            "approval_id": "42",
            "status": "pending",
            "instruction": "crie    app.py",
            "plan": plan,
        }
    ]

    result = creator.create_or_reuse(
        "  crie app.py  ",
        plan,
    )

    assert result["approval_id"] == "42"
    creator.supervisor.request_approval.assert_not_called()


def test_create_or_reuse_loads_history_before_listing_pending(creator):
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {}
    creator.supervisor.request_approval.return_value = "123"

    creator.create_or_reuse(
        "crie app.py",
        make_plan(),
    )

    creator.history._load.assert_called_once_with()

def test_plans_equal_rejects_non_dict_plans():
    assert TaskCreator._plans_equal(None, {}) is False
    assert TaskCreator._plans_equal({}, None) is False

def test_create_or_reuse_reconciles_orphan_pending_approval_after_history_crash(
    creator,
):
    plan = make_plan()
    creator.history.list_pending.return_value = []

    creator.supervisor.list_pending.return_value = {}
    creator.supervisor.request_approval.return_value = "123"
    creator.history.create.side_effect = RuntimeError("CRASH_AFTER_HISTORY")

    with pytest.raises(RuntimeError, match="CRASH_AFTER_HISTORY"):
        creator.create_or_reuse("crie app.py", plan)

    creator.history.create.side_effect = None
    creator.supervisor.list_pending.return_value = {
        "123": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
        }
    }

    result = creator.create_or_reuse("crie app.py", plan)

    assert result == {
        "approval_id": "123",
        "status": "pending",
        "plan": plan,
    }

    creator.supervisor.request_approval.assert_called_once_with(
        plan, instruction="crie app.py"
    )
    assert creator.history.create.call_count == 2
    creator.history.create.assert_called_with(
        approval_id="123",
        instruction="crie app.py",
        plan=plan,
    )

def test_create_or_reuse_does_not_reuse_ambiguous_orphan_approval(creator):
    plan = make_plan()
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {
        "123": {
            "status": "pending",
            "plan": plan,
        },
        "124": {
            "status": "pending",
            "plan": plan,
        },
    }
    creator.supervisor.request_approval.return_value = "125"

    result = creator.create_or_reuse("crie app.py", plan)

    assert result == {
        "approval_id": "125",
        "status": "pending",
        "plan": plan,
    }

    creator.supervisor.request_approval.assert_called_once_with(
        plan, instruction="crie app.py"
    )
    creator.history.create.assert_called_once_with(
        approval_id="125",
        instruction="crie app.py",
        plan=plan,
    )

def test_find_orphan_approval_skips_invalid_and_non_matching_requests(creator):
    result = {
        "objective": "teste",
        "tests": [],
        "risks": [],
        "changes": [],
    }

    creator.supervisor.list_pending.return_value = {
        "approval-invalid": "registro inválido",
        "approval-different": {
            "status": "pending",
            "plan": {
                "objective": "outro",
                "tests": [],
                "risks": [],
                "changes": [],
            },
        },
        "approval-valid": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": result,
        },
    }

    assert creator._find_orphan_approval(result, "crie app.py") == {
        "approval_id": "approval-valid",
        "status": "pending",
        "plan": result,
    }



def test_orphan_approval_does_not_reuse_different_instruction(creator):
    plan = make_plan()
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {
        "123": {
            "status": "pending",
            "instruction": "crie outro arquivo",
            "plan": plan,
        }
    }
    creator.supervisor.request_approval.return_value = "124"

    result = creator.create_or_reuse("crie app.py", plan)

    assert result["approval_id"] == "124"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
    )


def test_orphan_approval_does_not_reuse_legacy_request_without_instruction(
    creator,
):
    plan = make_plan()
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {
        "123": {
            "status": "pending",
            "plan": plan,
        }
    }
    creator.supervisor.request_approval.return_value = "124"

    result = creator.create_or_reuse("crie app.py", plan)

    assert result["approval_id"] == "124"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
    )


def test_orphan_approval_reuses_matching_normalized_instruction(creator):
    plan = make_plan()
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {
        "123": {
            "status": "pending",
            "instruction": "  crie    app.py  ",
            "plan": plan,
        }
    }

    result = creator.create_or_reuse("crie app.py", plan)

    assert result["approval_id"] == "123"
    creator.supervisor.request_approval.assert_not_called()


def test_find_orphan_approval_rejects_empty_instruction(creator):
    result = creator._find_orphan_approval(
        make_plan(),
        "  \n\t ",
    )

    assert result is None
    creator.supervisor.list_pending.assert_not_called()


def test_find_orphan_approval_rejects_different_plan(creator):
    creator.supervisor.list_pending.return_value = {
        "approval-1": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": make_plan(path="other.py"),
        }
    }

    result = creator._find_orphan_approval(
        make_plan(path="app.py"),
        "crie app.py",
    )

    assert result is None


def test_create_or_reuse_rejects_empty_instruction(creator):
    with pytest.raises(ValueError, match="Instrução inválida"):
        creator.create_or_reuse(
            "  \n\t ",
            make_plan(),
        )

    creator.history._load.assert_not_called()

def test_create_or_reuse_persists_idempotency_key(creator):
    plan = make_plan()
    creator.history.list_all.return_value = []
    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {}
    creator.supervisor.request_approval.return_value = "approval-key-1"

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
        idempotency_key="operation-001",
    )

    assert result["approval_id"] == "approval-key-1"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
        idempotency_key="operation-001",
    )
    creator.history.create.assert_called_once_with(
        approval_id="approval-key-1",
        instruction="crie app.py",
        plan=plan,
        idempotency_key="operation-001",
    )


def test_create_or_reuse_reuses_committed_task_by_idempotency_key(creator):
    plan = make_plan()
    creator.history.list_all.return_value = [
        {
            "approval_id": "approval-committed",
            "status": "committed",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-committed",
        }
    ]

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
        idempotency_key="operation-committed",
    )

    assert result == {
        "approval_id": "approval-committed",
        "status": "committed",
        "plan": plan,
    }
    creator.supervisor.request_approval.assert_not_called()
    creator.history.create.assert_not_called()


def test_create_or_reuse_rejects_idempotency_key_payload_conflict(creator):
    plan = make_plan()
    different_plan = make_plan(path="different.py")
    creator.history.list_all.return_value = [
        {
            "approval_id": "approval-existing",
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-conflict",
        }
    ]

    with pytest.raises(ValueError, match="dados diferentes"):
        creator.create_or_reuse(
            "crie app.py",
            different_plan,
            idempotency_key="operation-conflict",
        )

    creator.supervisor.request_approval.assert_not_called()


def test_create_or_reuse_recovers_orphan_approval_by_idempotency_key(creator):
    plan = make_plan()
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-orphan": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-orphan",
        }
    }

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
        idempotency_key="operation-orphan",
    )

    assert result["approval_id"] == "approval-orphan"
    creator.supervisor.request_approval.assert_not_called()
    creator.history.create.assert_called_once_with(
        approval_id="approval-orphan",
        instruction="crie app.py",
        plan=plan,
        idempotency_key="operation-orphan",
    )


def test_create_or_reuse_does_not_recover_orphan_with_different_key(creator):
    plan = make_plan()
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-other": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "another-operation",
        }
    }
    creator.supervisor.request_approval.return_value = "approval-new"

    result = creator.create_or_reuse(
        "crie app.py",
        plan,
        idempotency_key="operation-new",
    )

    assert result["approval_id"] == "approval-new"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
        idempotency_key="operation-new",
    )


@pytest.mark.parametrize("invalid_key", ["", "   ", 123, [], {}])
def test_create_or_reuse_rejects_invalid_idempotency_key(creator, invalid_key):
    with pytest.raises(ValueError, match="Chave de idempotência inválida"):
        creator.create_or_reuse(
            "crie app.py",
            make_plan(),
            idempotency_key=invalid_key,
        )

    creator.supervisor.request_approval.assert_not_called()

def test_find_existing_by_idempotency_key_reuses_history_without_plan(
    creator,
):
    plan = make_plan()
    creator.history.list_all.return_value = [
        {
            "approval_id": "approval-existing",
            "status": "committed",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-existing",
        }
    ]

    result = creator.find_existing_by_idempotency_key(
        "crie app.py",
        "operation-existing",
    )

    assert result == {
        "approval_id": "approval-existing",
        "status": "committed",
        "plan": plan,
    }
    creator.supervisor.list_pending.assert_not_called()
    creator.history.create.assert_not_called()


def test_find_existing_by_idempotency_key_recovers_orphan_without_plan(
    creator,
):
    plan = make_plan()
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-orphan": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-orphan",
        }
    }

    result = creator.find_existing_by_idempotency_key(
        "crie app.py",
        "operation-orphan",
    )

    assert result == {
        "approval_id": "approval-orphan",
        "status": "pending",
        "plan": plan,
    }
    creator.history.create.assert_called_once_with(
        approval_id="approval-orphan",
        instruction="crie app.py",
        plan=plan,
        idempotency_key="operation-orphan",
    )


def test_find_existing_by_idempotency_key_rejects_instruction_conflict(
    creator,
):
    creator.history.list_all.return_value = [
        {
            "approval_id": "approval-existing",
            "status": "pending",
            "instruction": "crie app.py",
            "plan": make_plan(),
            "idempotency_key": "operation-conflict",
        }
    ]

    with pytest.raises(ValueError, match="dados diferentes"):
        creator.find_existing_by_idempotency_key(
            "crie outro arquivo.py",
            "operation-conflict",
        )

    creator.supervisor.list_pending.assert_not_called()
    creator.history.create.assert_not_called()


def test_find_existing_by_idempotency_key_returns_none_when_missing(
    creator,
):
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {}

    result = creator.find_existing_by_idempotency_key(
        "crie app.py",
        "operation-missing",
    )

    assert result is None
    creator.history.create.assert_not_called()


def test_create_or_reuse_without_key_does_not_reuse_keyed_history_task(creator):
    plan = make_plan()

    creator.history.list_pending.return_value = [
        {
            "approval_id": "approval-keyed",
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-001",
        }
    ]
    creator.supervisor.list_pending.return_value = {}
    creator.supervisor.request_approval.return_value = "approval-new"

    result = creator.create_or_reuse("crie app.py", plan)

    assert result["approval_id"] == "approval-new"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
    )


def test_create_or_reuse_without_key_does_not_reuse_keyed_orphan_approval(creator):
    plan = make_plan()

    creator.history.list_pending.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-keyed": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": plan,
            "idempotency_key": "operation-001",
        }
    }
    creator.supervisor.request_approval.return_value = "approval-new"

    result = creator.create_or_reuse("crie app.py", plan)

    assert result["approval_id"] == "approval-new"
    creator.supervisor.request_approval.assert_called_once_with(
        plan,
        instruction="crie app.py",
    )

def test_task_creator_concurrent_create_or_reuse_recovers_same_task(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from core.memory.task_history import TaskHistory
    from core.supervisor import Supervisor

    instruction = "crie app.py"
    idempotency_key = "concurrent-create-001"
    plan = make_plan()
    tasks_path = tmp_path / "tasks.json"
    approvals_path = tmp_path / "approvals.json"
    barrier = Barrier(2, timeout=10)

    class BarrierTaskHistory(TaskHistory):
        def create(self, *args, **kwargs):
            barrier.wait()
            return super().create(*args, **kwargs)

    histories = [
        BarrierTaskHistory(tasks_path),
        BarrierTaskHistory(tasks_path),
    ]
    supervisors = [
        Supervisor(approvals_path),
        Supervisor(approvals_path),
    ]
    creators = [
        TaskCreator(Mock(), histories[index], supervisors[index])
        for index in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                creator.create_or_reuse,
                instruction,
                plan,
                idempotency_key,
            )
            for creator in creators
        ]
        results = [future.result(timeout=20) for future in futures]

    assert results[0]["approval_id"] == results[1]["approval_id"]
    assert results[0]["status"] == results[1]["status"] == "pending"
    assert results[0]["plan"] == results[1]["plan"] == plan

    persisted_history = TaskHistory(tasks_path)
    persisted_tasks = [
        task
        for task in persisted_history.list_all()
        if task.get("idempotency_key") == idempotency_key
    ]
    assert len(persisted_tasks) == 1
    assert persisted_tasks[0]["approval_id"] == results[0]["approval_id"]

    persisted_approvals = Supervisor(approvals_path).list_pending()
    assert len(persisted_approvals) == 1
    assert results[0]["approval_id"] in persisted_approvals


def test_task_creator_concurrent_orphan_recovery_creates_one_task(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from core.memory.task_history import TaskHistory
    from core.supervisor import Supervisor

    instruction = "crie app.py"
    idempotency_key = "concurrent-orphan-001"
    plan = make_plan()
    tasks_path = tmp_path / "tasks.json"
    approvals_path = tmp_path / "approvals.json"
    barrier = Barrier(2, timeout=10)

    seed_supervisor = Supervisor(approvals_path)
    approval_id = seed_supervisor.request_approval(
        plan,
        instruction=instruction,
        idempotency_key=idempotency_key,
    )

    class BarrierTaskHistory(TaskHistory):
        def create(self, *args, **kwargs):
            barrier.wait()
            return super().create(*args, **kwargs)

    histories = [
        BarrierTaskHistory(tasks_path),
        BarrierTaskHistory(tasks_path),
    ]
    supervisors = [
        Supervisor(approvals_path),
        Supervisor(approvals_path),
    ]
    creators = [
        TaskCreator(Mock(), histories[index], supervisors[index])
        for index in range(2)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                creator.find_existing_by_idempotency_key,
                instruction,
                idempotency_key,
            )
            for creator in creators
        ]
        results = [future.result(timeout=20) for future in futures]

    assert results[0]["approval_id"] == results[1]["approval_id"] == approval_id
    assert results[0]["status"] == results[1]["status"] == "pending"
    assert results[0]["plan"] == results[1]["plan"] == plan

    persisted_history = TaskHistory(tasks_path)
    persisted_tasks = [
        task
        for task in persisted_history.list_all()
        if task.get("idempotency_key") == idempotency_key
    ]
    assert len(persisted_tasks) == 1
    assert persisted_tasks[0]["approval_id"] == approval_id

def _duplicate_task(*, approval_id="approval-1", instruction="crie app.py", plan=None, idempotency_key="operation-coverage"):
    return {
        "approval_id": approval_id,
        "status": "pending",
        "instruction": instruction,
        "plan": make_plan() if plan is None else plan,
        "idempotency_key": idempotency_key,
    }


def test_create_or_recover_task_propagates_unrelated_value_error(creator):
    creator.history.create.side_effect = ValueError("falha diferente")
    with pytest.raises(ValueError, match="falha diferente"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan(), idempotency_key="operation-coverage")
    creator.history.refresh.assert_not_called()


def test_create_or_recover_task_propagates_duplicate_without_key(creator):
    creator.history.create.side_effect = ValueError("Tarefa já existe.")
    with pytest.raises(ValueError, match="Tarefa já existe"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan())
    creator.history.refresh.assert_not_called()


def test_create_or_recover_task_rejects_multiple_matching_tasks(creator):
    creator.history.create.side_effect = ValueError("Chave de idempotência já utilizada.")
    creator.history.list_all.return_value = [_duplicate_task(), _duplicate_task(approval_id="approval-2")]
    with pytest.raises(RuntimeError, match="múltiplas tarefas"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan(), idempotency_key="operation-coverage")


def test_create_or_recover_task_reraises_when_duplicate_is_not_found(creator):
    creator.history.create.side_effect = ValueError("Tarefa já existe.")
    creator.history.list_all.return_value = []
    with pytest.raises(ValueError, match="Tarefa já existe"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan(), idempotency_key="operation-coverage")


def test_create_or_recover_task_rejects_different_approval(creator):
    creator.history.create.side_effect = ValueError("Tarefa já existe.")
    creator.history.list_all.return_value = [_duplicate_task(approval_id="approval-other")]
    with pytest.raises(RuntimeError, match="aprovação diferente"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan(), idempotency_key="operation-coverage")


def test_create_or_recover_task_rejects_payload_conflict(creator):
    creator.history.create.side_effect = ValueError("Tarefa já existe.")
    creator.history.list_all.return_value = [
        _duplicate_task(instruction="crie outro arquivo.py", plan=make_plan(path="other.py"))
    ]
    with pytest.raises(ValueError, match="dados diferentes"):
        creator._create_or_recover_task("approval-1", "crie app.py", make_plan(), idempotency_key="operation-coverage")


def test_find_orphan_approval_rejects_multiple_keyed_matches(creator):
    plan = make_plan()
    request = {
        "status": "pending",
        "instruction": "crie app.py",
        "plan": plan,
        "idempotency_key": "operation-coverage",
    }
    creator.supervisor.list_pending.return_value = {
        "approval-1": dict(request),
        "approval-2": dict(request),
    }
    with pytest.raises(RuntimeError, match="múltiplas aprovações"):
        creator._find_orphan_approval(plan, "crie app.py", idempotency_key="operation-coverage")


def test_find_orphan_approval_returns_none_for_multiple_unkeyed_matches(creator):
    plan = make_plan()
    request = {"status": "pending", "instruction": "crie app.py", "plan": plan}
    creator.supervisor.list_pending.return_value = {
        "approval-1": dict(request),
        "approval-2": dict(request),
    }
    assert creator._find_orphan_approval(plan, "crie app.py") is None


@pytest.mark.parametrize("instruction", ["", "  \n\t "])
def test_find_existing_rejects_invalid_instruction(creator, instruction):
    with pytest.raises(ValueError, match="Instrução inválida"):
        creator.find_existing_by_idempotency_key(instruction, "operation-coverage")
    creator.history._load.assert_not_called()


@pytest.mark.parametrize("invalid_key", ["", "   ", 123, [], {}])
def test_find_existing_rejects_invalid_idempotency_key(creator, invalid_key):
    with pytest.raises(ValueError, match="Chave de idempotência inválida"):
        creator.find_existing_by_idempotency_key("crie app.py", invalid_key)
    creator.history._load.assert_not_called()


def test_find_existing_rejects_multiple_matching_history_tasks(creator):
    creator.history.list_all.return_value = [_duplicate_task(), _duplicate_task(approval_id="approval-2")]
    with pytest.raises(RuntimeError, match="múltiplas tarefas"):
        creator.find_existing_by_idempotency_key("crie app.py", "operation-coverage")
    creator.supervisor.list_pending.assert_not_called()


def test_find_existing_returns_none_for_non_dict_pending_state(creator):
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = ["invalid"]
    assert creator.find_existing_by_idempotency_key("crie app.py", "operation-coverage") is None


def test_find_existing_rejects_multiple_orphan_approvals(creator):
    plan = make_plan()
    request = {
        "status": "pending",
        "instruction": "crie app.py",
        "plan": plan,
        "idempotency_key": "operation-coverage",
    }
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-1": dict(request),
        "approval-2": dict(request),
    }
    with pytest.raises(RuntimeError, match="múltiplas aprovações"):
        creator.find_existing_by_idempotency_key("crie app.py", "operation-coverage")


def test_find_existing_rejects_orphan_instruction_conflict(creator):
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-1": {
            "status": "pending",
            "instruction": "crie outro arquivo.py",
            "plan": make_plan(),
            "idempotency_key": "operation-coverage",
        }
    }
    with pytest.raises(ValueError, match="dados diferentes"):
        creator.find_existing_by_idempotency_key("crie app.py", "operation-coverage")
    creator.history.create.assert_not_called()


def test_find_existing_rejects_orphan_with_invalid_plan(creator):
    creator.history.list_all.return_value = []
    creator.supervisor.list_pending.return_value = {
        "approval-1": {
            "status": "pending",
            "instruction": "crie app.py",
            "plan": [],
            "idempotency_key": "operation-coverage",
        }
    }
    with pytest.raises(RuntimeError, match="Plano inválido na aprovação órfã"):
        creator.find_existing_by_idempotency_key("crie app.py", "operation-coverage")
    creator.history.create.assert_not_called()


def test_create_or_reuse_rejects_multiple_matching_history_tasks(creator):
    creator.history.list_all.return_value = [_duplicate_task(), _duplicate_task(approval_id="approval-2")]
    with pytest.raises(RuntimeError, match="múltiplas tarefas"):
        creator.create_or_reuse("crie app.py", make_plan(), idempotency_key="operation-coverage")
    creator.supervisor.request_approval.assert_not_called()


# Testes reais de concorrência entre processos independentes.
class _ProcessBarrierTaskHistory:
    def __new__(cls, storage_path, barrier):
        from core.memory.task_history import TaskHistory

        class BarrierTaskHistory(TaskHistory):
            def create(self, *args, **kwargs):
                barrier.wait(timeout=20)
                return super().create(*args, **kwargs)

        return BarrierTaskHistory(storage_path)


def _task_creator_multiprocess_worker(
    tasks_path,
    approvals_path,
    instruction,
    plan,
    idempotency_key,
    barrier,
    mode,
    queue,
):
    try:
        from unittest.mock import Mock

        from core.supervisor import Supervisor
        from core.task.task_creator import TaskCreator

        history = _ProcessBarrierTaskHistory(tasks_path, barrier)
        supervisor = Supervisor(approvals_path)
        creator = TaskCreator(Mock(), history, supervisor)

        if mode == "create":
            result = creator.create_or_reuse(
                instruction,
                plan,
                idempotency_key,
            )
        elif mode == "orphan":
            result = creator.find_existing_by_idempotency_key(
                instruction,
                idempotency_key,
            )
        else:
            raise ValueError(f"Modo desconhecido: {mode}")

        queue.put(("ok", result))
    except Exception as error:
        queue.put(("error", type(error).__name__, str(error)))


def _run_task_creator_multiprocess_race(
    context,
    tasks_path,
    approvals_path,
    instruction,
    plan,
    idempotency_key,
    mode,
):
    barrier = context.Barrier(2)
    queue = context.Queue()

    processes = [
        context.Process(
            target=_task_creator_multiprocess_worker,
            args=(
                str(tasks_path),
                str(approvals_path),
                instruction,
                plan,
                idempotency_key,
                barrier,
                mode,
                queue,
            ),
        )
        for _ in range(2)
    ]

    try:
        for process in processes:
            process.start()

        for process in processes:
            process.join(timeout=35)

        alive = [process for process in processes if process.is_alive()]
        for process in alive:
            process.terminate()
        for process in alive:
            process.join(timeout=5)

        assert not alive, "Processos não terminaram dentro do prazo."
        assert all(process.exitcode == 0 for process in processes), [
            process.exitcode for process in processes
        ]

        results = [queue.get(timeout=10) for _ in processes]
        assert all(result[0] == "ok" for result in results), results

        return [result[1] for result in results]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
        queue.join_thread()


def test_task_creator_multiprocess_same_idempotency_key_creates_one_task(
    tmp_path,
):
    import multiprocessing as mp

    from core.memory.task_history import TaskHistory
    from core.supervisor import Supervisor

    instruction = "crie app.py"
    idempotency_key = "multiprocess-create-001"
    plan = make_plan()
    tasks_path = tmp_path / "tasks.json"
    approvals_path = tmp_path / "approvals.json"
    context = mp.get_context("spawn")

    results = _run_task_creator_multiprocess_race(
        context,
        tasks_path,
        approvals_path,
        instruction,
        plan,
        idempotency_key,
        "create",
    )

    assert results[0] == results[1]
    assert results[0]["status"] == "pending"
    assert results[0]["plan"] == plan

    tasks = [
        task
        for task in TaskHistory(tasks_path).list_all()
        if task.get("idempotency_key") == idempotency_key
    ]
    approvals = Supervisor(approvals_path).list_all()

    assert len(tasks) == 1
    assert tasks[0]["approval_id"] == results[0]["approval_id"]
    assert len(approvals) == 1
    assert results[0]["approval_id"] in approvals


def test_task_creator_multiprocess_orphan_recovery_creates_one_task(
    tmp_path,
):
    import multiprocessing as mp

    from core.memory.task_history import TaskHistory
    from core.supervisor import Supervisor

    instruction = "crie app.py"
    idempotency_key = "multiprocess-orphan-001"
    plan = make_plan()
    tasks_path = tmp_path / "tasks.json"
    approvals_path = tmp_path / "approvals.json"
    context = mp.get_context("spawn")

    seed_supervisor = Supervisor(approvals_path)
    approval_id = seed_supervisor.request_approval(
        plan,
        instruction=instruction,
        idempotency_key=idempotency_key,
    )

    results = _run_task_creator_multiprocess_race(
        context,
        tasks_path,
        approvals_path,
        instruction,
        plan,
        idempotency_key,
        "orphan",
    )

    assert results[0] == results[1]
    assert results[0]["approval_id"] == approval_id
    assert results[0]["status"] == "pending"
    assert results[0]["plan"] == plan

    tasks = [
        task
        for task in TaskHistory(tasks_path).list_all()
        if task.get("idempotency_key") == idempotency_key
    ]
    approvals = Supervisor(approvals_path).list_all()

    assert len(tasks) == 1
    assert tasks[0]["approval_id"] == approval_id
    assert len(approvals) == 1
    assert approval_id in approvals
