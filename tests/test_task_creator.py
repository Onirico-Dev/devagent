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
