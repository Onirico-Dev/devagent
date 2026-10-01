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

    creator.supervisor.request_approval.assert_called_once_with(plan)
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
        new_plan
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
        plan
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
            "plan": plan,
        }
    }

    result = creator.create_or_reuse("crie app.py", plan)

    assert result == {
        "approval_id": "123",
        "status": "pending",
        "plan": plan,
    }

    creator.supervisor.request_approval.assert_called_once_with(plan)
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

    creator.supervisor.request_approval.assert_called_once_with(plan)
    creator.history.create.assert_called_once_with(
        approval_id="125",
        instruction="crie app.py",
        plan=plan,
    )
