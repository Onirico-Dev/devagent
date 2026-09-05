from types import SimpleNamespace

import pytest

from core.engine.repair_controller import RepairController
from core.engine.repair_cycle_state import RepairCycleState, RepairCycleStatus
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import RepairExecutor, RepairExecutorStatus
from core.engine.repair_flow import RepairFlow
from core.memory.task_history import TaskHistoryStatus
from core.schemas.models import TransactionStatus


class FakeState:
    def __init__(self, attempts=0, max_attempts=2):
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.calls = []
        self.persist_calls = 0

    def can_continue(self):
        return self.attempts < self.max_attempts

    def mark_analyzing(self):
        self.calls.append(("analyzing",))

    def mark_failed(self, error=""):
        self.calls.append(("failed", error))

    def mark_verified(self):
        self.calls.append(("verified",))

    def mark_repair_failed(self, error=""):
        self.calls.append(("repair_failed", error))

    def record(self, action, status):
        self.attempts += 1
        self.calls.append(("record", action, status))

    def persist(self, transaction):
        self.persist_calls += 1


class FakeController:
    def __init__(self):
        self.max_attempts = None
        self.restore_calls = []

    def restore_state(self, transaction_id, attempts):
        self.restore_calls.append((transaction_id, attempts))


class FakeEngine:
    def __init__(self, diagnosis):
        self.diagnosis = diagnosis
        self.calls = []

    def analyze_failure(self, **kwargs):
        self.calls.append(kwargs)
        return self.diagnosis


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute_repair(self, diagnosis, instruction, transaction):
        self.calls.append((diagnosis, instruction, transaction))
        return self.result


def make_transaction():
    return SimpleNamespace(transaction_id="tx-123")


def make_flow(
    diagnosis=None,
    executor_result=None,
    controller=None,
    max_attempts=2,
):
    controller = controller or FakeController()
    return (
        RepairFlow(
            repair_engine=FakeEngine(diagnosis),
            repair_executor=FakeExecutor(executor_result),
            repair_controller=controller,
            max_attempts=max_attempts,
        ),
        controller,
    )


def test_init_stores_dependencies():
    engine = object()
    executor = object()
    controller = object()

    flow = RepairFlow(
        repair_engine=engine,
        repair_executor=executor,
        repair_controller=controller,
        max_attempts=7,
    )

    assert flow.repair_engine is engine
    assert flow.repair_executor is executor
    assert flow.repair_controller is controller
    assert flow.max_attempts == 7


def test_restore_state_restores_cycle_and_controller(monkeypatch):
    flow, controller = make_flow(max_attempts=5)
    transaction = make_transaction()
    state = FakeState(attempts=1, max_attempts=99)

    monkeypatch.setattr(
        "core.engine.repair_flow.RepairCycleState.restore",
        lambda tx: state,
    )

    result = flow.restore_state(transaction)

    assert result is state
    assert state.max_attempts == 5
    assert controller.max_attempts == 5
    assert controller.restore_calls == [("tx-123", 1)]


def test_sync_controller_updates_controller_state():
    flow, controller = make_flow()
    transaction = make_transaction()
    state = FakeState(attempts=1, max_attempts=7)

    result = flow.sync_controller(transaction, state)

    assert result is None
    assert controller.max_attempts == 7
    assert controller.restore_calls == [("tx-123", 1)]


def test_attempt_stops_when_limit_already_reached():
    flow, controller = make_flow()
    transaction = make_transaction()
    state = FakeState(attempts=2, max_attempts=2)

    result = flow.attempt(
        instruction="corrigir bug",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["status"] == RepairCycleStatus.LIMIT_REACHED.value
    assert result["success"] is False
    assert result["repair"]["action"] == "none"
    assert result["repair"]["risk"] == "baixo"
    assert result["repair"]["path"] == ""
    assert result["repair"]["content"] == ""
    assert controller.restore_calls == [("tx-123", 2)]


def test_attempt_normalizes_invalid_diagnosis():
    diagnosis_engine = FakeEngine(None)
    executor = FakeExecutor(None)
    controller = FakeController()
    flow = RepairFlow(
        diagnosis_engine,
        executor,
        controller,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={
            "success": False,
            "stderr": "erro",
            "stdout": "saida",
        },
        repair_state=state,
    )

    assert result["status"] == RepairCycleStatus.NO_REPAIR.value
    assert result["success"] is False
    assert result["repair"] == {
        "action": "none",
        "risk": "baixo",
        "path": "",
        "content": "",
        "diagnosis": "Diagnóstico de reparo inválido.",
        "correction": "",
    }
    assert state.attempts == 0
    assert state.persist_calls == 1
    assert diagnosis_engine.calls[0]["instruction"] == "corrigir"
    assert diagnosis_engine.calls[0]["error"] == "erro"
    assert diagnosis_engine.calls[0]["test_output"] == "saida"


def test_attempt_high_risk_rolls_back_without_consuming_attempt():
    diagnosis = {
        "action": "modify",
        "risk": "alto",
        "path": "x.py",
        "content": "x = 1",
    }
    flow, _ = make_flow(diagnosis=diagnosis)
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"stderr": "falha", "stdout": ""},
        repair_state=state,
    )

    assert result == {
        "status": TransactionStatus.ROLLED_BACK.value,
        "success": False,
        "repair": diagnosis,
    }
    assert state.attempts == 0


def test_attempt_none_action_returns_no_repair():
    diagnosis = {
        "action": "none",
        "risk": "baixo",
        "path": "",
        "content": "",
        "diagnosis": "Sem correção segura.",
        "correction": "",
    }
    flow, _ = make_flow(diagnosis=diagnosis)
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["status"] == RepairCycleStatus.NO_REPAIR.value
    assert result["success"] is False
    assert result["repair"] == diagnosis
    assert state.attempts == 0


def test_attempt_rechecks_limit_after_analysis(monkeypatch):
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    flow, _ = make_flow(diagnosis=diagnosis)
    transaction = make_transaction()
    state = FakeState()

    calls = {"count": 0}

    def can_continue():
        calls["count"] += 1
        return calls["count"] == 1

    monkeypatch.setattr(state, "can_continue", can_continue)

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["status"] == RepairCycleStatus.LIMIT_REACHED.value
    assert result["success"] is False
    assert result["repair"] == diagnosis
    assert calls["count"] == 2
    assert state.attempts == 0


def test_attempt_applies_repair_and_marks_verified():
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    executor_result = {
        "success": True,
        "status": RepairExecutorStatus.REPAIR_APPLIED.value,
        "tests": {
            "success": True,
            "stdout": "passed",
            "stderr": "",
        },
    }

    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=executor_result,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is True
    assert result["status"] == RepairExecutorStatus.REPAIR_VERIFIED.value
    assert result["repair"] == diagnosis
    assert result["transaction_id"] == "tx-123"
    assert result["repair_attempts"] == 1
    assert state.attempts == 1
    assert ("record", "modify", TaskHistoryStatus.REPAIRING.value) in state.calls
    assert ("verified",) in state.calls


def test_attempt_uses_unknown_action_when_missing():
    diagnosis = {
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    executor_result = {
        "success": True,
        "status": RepairExecutorStatus.REPAIR_APPLIED.value,
        "tests": {"success": True},
    }

    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=executor_result,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is True
    assert ("record", "unknown", TaskHistoryStatus.REPAIRING.value) in state.calls


def test_attempt_normalizes_invalid_repair_result():
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=None,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == RepairExecutorStatus.FAILED.value
    assert result["error"] == "Resultado de reparo inválido."
    assert result["repair"] == diagnosis
    assert result["transaction_id"] == "tx-123"
    assert result["repair_attempts"] == 1
    assert ("failed", "Resultado de reparo inválido.") in state.calls


def test_attempt_handles_failed_repair_result():
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    executor_result = {
        "success": False,
        "status": RepairExecutorStatus.FAILED.value,
        "error": "falha física",
    }

    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=executor_result,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == RepairExecutorStatus.FAILED.value
    assert result["error"] == "falha física"
    assert result["repair_attempts"] == 1
    assert ("failed", "falha física") in state.calls


def test_attempt_handles_invalid_test_result():
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    executor_result = {
        "success": False,
        "status": RepairExecutorStatus.REPAIR_FAILED.value,
        "tests": None,
    }

    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=executor_result,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == RepairExecutorStatus.REPAIR_FAILED.value
    assert result["tests"]["status"] == (
        RepairExecutorStatus.INVALID_TEST_RESULT.value
    )
    assert result["tests"]["success"] is False
    assert result["tests"]["stderr"] == "Resultado de testes inválido."
    assert result["tests"]["stdout"] == ""
    assert ("failed", "Resultado de testes inválido.") in state.calls


def test_attempt_handles_repair_failed_tests():
    diagnosis = {
        "action": "modify",
        "risk": "baixo",
        "path": "x.py",
        "content": "x = 1",
    }
    executor_result = {
        "success": False,
        "status": RepairExecutorStatus.REPAIR_FAILED.value,
        "tests": {
            "success": False,
            "stderr": "teste falhou",
            "stdout": "",
        },
    }

    flow, _ = make_flow(
        diagnosis=diagnosis,
        executor_result=executor_result,
    )
    transaction = make_transaction()
    state = FakeState()

    result = flow.attempt(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == RepairExecutorStatus.REPAIR_FAILED.value
    assert result["tests"]["success"] is False
    assert result["repair_attempts"] == 1
    assert ("repair_failed", "teste falhou") in state.calls


def test_run_rejects_non_dict_initial_tests():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState(attempts=1)

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result=None,
        repair_state=state,
    )

    assert result == {
        "success": False,
        "status": TransactionStatus.ROLLED_BACK.value,
        "tests": None,
        "repair": None,
        "repair_attempts": 1,
    }


def test_run_returns_verified_when_initial_tests_pass():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": True},
        repair_state=state,
    )

    assert result == {
        "success": True,
        "status": RepairCycleStatus.VERIFIED.value,
        "tests": {"success": True},
        "repair": None,
        "repair_attempts": 0,
    }


def test_run_rolls_back_when_limit_reached_before_attempt():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState(attempts=2, max_attempts=2)

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["repair_attempts"] == 2
    assert result["repair"]["status"] == RepairCycleStatus.LIMIT_REACHED.value
    assert result["repair"]["action"] == "none"


def test_run_accepts_attempt_fn_and_returns_verified():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    calls = []

    def attempt_fn(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "status": RepairExecutorStatus.REPAIR_VERIFIED.value,
            "tests": {"success": True, "stdout": "", "stderr": ""},
            "repair": {"action": "modify"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is True
    assert result["status"] == RepairCycleStatus.VERIFIED.value
    assert result["tests"]["success"] is True
    assert result["repair"] == {"action": "modify"}
    assert len(calls) == 1


def test_run_rolls_back_success_without_successful_tests():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        return {
            "success": True,
            "status": RepairExecutorStatus.REPAIR_VERIFIED.value,
            "tests": {"success": False},
            "repair": {"action": "modify"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["tests"] == {"success": False}
    assert result["repair"] == {"action": "modify"}


def test_run_rolls_back_success_without_test_dict():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        return {
            "success": True,
            "status": RepairExecutorStatus.REPAIR_VERIFIED.value,
            "tests": None,
            "repair": {"action": "modify"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["tests"] == {"success": False}


def test_run_retries_after_repair_failed_with_tests():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    results = iter(
        [
            {
                "success": False,
                "status": RepairExecutorStatus.REPAIR_FAILED.value,
                "tests": {
                    "success": False,
                    "stderr": "primeira falha",
                    "stdout": "",
                },
                "repair": {"action": "modify"},
            },
            {
                "success": True,
                "status": RepairExecutorStatus.REPAIR_VERIFIED.value,
                "tests": {
                    "success": True,
                    "stderr": "",
                    "stdout": "ok",
                },
                "repair": {"action": "modify"},
            },
        ]
    )

    def attempt_fn(**kwargs):
        state.attempts += 1
        return next(results)

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is True
    assert result["status"] == RepairCycleStatus.VERIFIED.value
    assert result["tests"]["success"] is True
    assert result["repair_attempts"] == 2


def test_run_rolls_back_after_repair_failed_when_limit_is_exhausted():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        state.attempts = state.max_attempts
        return {
            "success": False,
            "status": RepairExecutorStatus.REPAIR_FAILED.value,
            "tests": {"success": False},
            "repair": {
                "action": "modify",
                "status": "repair_failed",
            },
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["tests"]["success"] is False
    assert result["repair"]["status"] == RepairCycleStatus.LIMIT_REACHED.value


def test_run_rolls_back_repair_failed_without_tests():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        return {
            "success": False,
            "status": RepairExecutorStatus.REPAIR_FAILED.value,
            "repair": {"action": "modify"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["tests"] == {"success": False}
    assert result["repair"] == {"action": "modify"}


def test_run_rolls_back_failed_status_with_error():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        return {
            "success": False,
            "status": RepairExecutorStatus.FAILED.value,
            "error": "erro físico",
            "repair": {"action": "modify"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["error"] == "erro físico"
    assert result["repair"] == {"action": "modify"}


@pytest.mark.parametrize(
    "status",
    [
        RepairCycleStatus.NO_REPAIR.value,
        RepairCycleStatus.LIMIT_REACHED.value,
        TransactionStatus.ROLLED_BACK.value,
        "status_desconhecido",
    ],
)
def test_run_rolls_back_terminal_or_unknown_status(status):
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        return {
            "success": False,
            "status": status,
            "repair": {"action": "none"},
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["repair"] == {"action": "none"}


def test_run_uses_default_attempt_when_attempt_fn_is_none(monkeypatch):
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    calls = []

    def fake_attempt(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "status": RepairExecutorStatus.REPAIR_VERIFIED.value,
            "tests": {"success": True},
            "repair": {"action": "modify"},
        }

    monkeypatch.setattr(flow, "attempt", fake_attempt)

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
    )

    assert result["success"] is True
    assert result["status"] == RepairCycleStatus.VERIFIED.value
    assert len(calls) == 1


def test_run_marks_repair_none_when_limit_reached_without_repair_dict():
    flow, _ = make_flow()
    transaction = make_transaction()
    state = FakeState()

    def attempt_fn(**kwargs):
        state.attempts = state.max_attempts
        return {
            "success": False,
            "status": RepairExecutorStatus.REPAIR_FAILED.value,
            "tests": {
                "success": False,
                "stderr": "teste continua falhando",
                "stdout": "",
            },
            "repair": None,
        }

    result = flow.run(
        instruction="corrigir",
        transaction=transaction,
        test_result={"success": False},
        repair_state=state,
        attempt_fn=attempt_fn,
    )

    assert result["success"] is False
    assert result["status"] == TransactionStatus.ROLLED_BACK.value
    assert result["tests"]["success"] is False
    assert result["repair"] is None
    assert result["repair_attempts"] == state.max_attempts
