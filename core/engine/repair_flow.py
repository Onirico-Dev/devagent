from core.engine.repair_controller import RepairController
from core.engine.repair_cycle_state import (
    RepairCycleState,
    RepairCycleStatus,
)
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import (
    RepairExecutor,
    RepairExecutorStatus,
)
from core.schemas.models import TransactionStatus
from core.memory.task_history import TaskHistoryStatus


class RepairFlow:
    """Orquestra análise, aplicação e validação de reparos."""

    def __init__(
        self,
        repair_engine: RepairEngine,
        repair_executor: RepairExecutor,
        repair_controller: RepairController,
        max_attempts: int = 2,
    ):
        self.repair_engine = repair_engine
        self.repair_executor = repair_executor
        self.repair_controller = repair_controller
        self.max_attempts = max_attempts

    def restore_state(self, transaction):
        state = RepairCycleState.restore(transaction)
        state.max_attempts = self.max_attempts

        self.repair_controller.max_attempts = (
            state.max_attempts
        )
        self.repair_controller.restore_state(
            transaction.transaction_id,
            state.attempts,
        )

        return state

    def sync_controller(
        self,
        transaction,
        state,
    ):
        self.repair_controller.max_attempts = (
            state.max_attempts
        )
        self.repair_controller.restore_state(
            transaction.transaction_id,
            state.attempts,
        )

    def attempt(
        self,
        instruction,
        transaction,
        test_result,
        repair_state,
    ):
        """
        Executa exatamente uma tentativa de reparo.

        A análise ocorre antes do consumo da tentativa.
        Somente uma correção aplicável consome uma tentativa.
        repair_failed com testes representa uma correção aplicada
        cujos testes continuam falhando; o ciclo decide se haverá
        nova tentativa ou rollback.
        """
        self.sync_controller(
            transaction,
            repair_state,
        )

        if not repair_state.can_continue():
            return {
                "status": RepairCycleStatus.LIMIT_REACHED.value,
                "success": False,
                "repair": {
                    "status": (
                        RepairCycleStatus.LIMIT_REACHED.value
                    ),
                    "action": "none",
                    "risk": "baixo",
                    "path": "",
                    "content": "",
                    "diagnosis": (
                        "Limite máximo de tentativas "
                        "de reparo atingido."
                    ),
                    "correction": (
                        "Nenhuma nova correção automática "
                        "será tentada."
                    ),
                },
            }

        repair_state.mark_analyzing()
        repair_state.persist(transaction)

        diagnosis = self.repair_engine.analyze_failure(
            instruction=instruction,
            error=test_result.get("stderr", ""),
            test_output=test_result.get("stdout", ""),
        )

        if not isinstance(diagnosis, dict):
            diagnosis = {
                "action": "none",
                "risk": "baixo",
                "path": "",
                "content": "",
                "diagnosis": (
                    "Diagnóstico de reparo inválido."
                ),
                "correction": "",
            }

        if diagnosis.get("risk") == "alto":
            return {
                "status": TransactionStatus.ROLLED_BACK.value,
                "success": False,
                "repair": diagnosis,
            }

        if diagnosis.get("action") == "none":
            return {
                "status": RepairCycleStatus.NO_REPAIR.value,
                "success": False,
                "repair": diagnosis,
            }

        if not repair_state.can_continue():
            return {
                "status": RepairCycleStatus.LIMIT_REACHED.value,
                "success": False,
                "repair": diagnosis,
            }

        repair_state.record(
            action=diagnosis.get(
                "action",
                "unknown",
            ),
            status=TaskHistoryStatus.REPAIRING.value,
        )
        repair_state.persist(transaction)

        self.sync_controller(
            transaction,
            repair_state,
        )

        repair_result = (
            self.repair_executor.execute_repair(
                diagnosis,
                instruction,
                transaction,
            )
        )

        if not isinstance(repair_result, dict):
            repair_result = {
                "success": False,
                "status": RepairExecutorStatus.FAILED.value,
                "error": "Resultado de reparo inválido.",
            }

        repair_result["repair"] = diagnosis
        repair_result["transaction_id"] = (
            transaction.transaction_id
        )
        repair_result["repair_attempts"] = (
            repair_state.attempts
        )

        if (
            repair_result.get("status")
            == RepairExecutorStatus.FAILED.value
        ):
            error = repair_result.get("error", "")

            repair_state.mark_failed(
                error=error,
            )
            repair_state.persist(transaction)

            return repair_result

        test_result = repair_result.get("tests")

        if not isinstance(test_result, dict):
            repair_state.mark_failed(
                error="Resultado de testes inválido.",
            )
            repair_state.persist(transaction)

            repair_result["success"] = False
            repair_result["status"] = (
                RepairExecutorStatus.REPAIR_FAILED.value
            )
            repair_result["tests"] = {
                "success": False,
                "status": (
                    RepairExecutorStatus.INVALID_TEST_RESULT.value
                ),
                "stderr": "Resultado de testes inválido.",
                "stdout": "",
            }

            return repair_result

        if test_result.get("success"):
            repair_state.mark_verified()
            repair_state.persist(transaction)

            repair_result["success"] = True
            repair_result["status"] = (
                RepairExecutorStatus.REPAIR_VERIFIED.value
            )

            return repair_result

        repair_state.mark_repair_failed(
            error=test_result.get("stderr", ""),
        )
        repair_state.persist(transaction)

        repair_result["success"] = False
        repair_result["status"] = (
            RepairExecutorStatus.REPAIR_FAILED.value
        )

        return repair_result

    def run(
        self,
        instruction,
        transaction,
        test_result,
        repair_state,
        attempt_fn=None,
    ):
        attempt = attempt_fn or self.attempt
        """
        Executa o ciclo completo de reparo.

        O método não realiza commit nem rollback físico.
        Ele somente determina o resultado do ciclo.
        """
        if not isinstance(test_result, dict):
            return {
                "success": False,
                "status": TransactionStatus.ROLLED_BACK.value,
                "tests": test_result,
                "repair": None,
                "repair_attempts": repair_state.attempts,
            }

        while not test_result.get("success", False):
            self.sync_controller(
                transaction,
                repair_state,
            )

            if not repair_state.can_continue():
                return {
                    "success": False,
                    "status": (
                        TransactionStatus.ROLLED_BACK.value
                    ),
                    "tests": test_result,
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                    "repair": {
                        "action": "none",
                        "risk": "baixo",
                        "path": "",
                        "content": "",
                        "status": (
                            RepairCycleStatus.LIMIT_REACHED.value
                        ),
                        "diagnosis": (
                            "Limite máximo de tentativas "
                            "de reparo atingido."
                        ),
                        "correction": (
                            "Nenhuma nova correção automática "
                            "será tentada."
                        ),
                    },
                }

            repair_result = attempt(
                instruction=instruction,
                transaction=transaction,
                test_result=test_result,
                repair_state=repair_state,
            )

            status = repair_result.get(
                "status",
                RepairExecutorStatus.REPAIR_FAILED.value,
            )

            if repair_result.get("success"):
                next_tests = repair_result.get(
                    "tests",
                    {},
                )

                if (
                    isinstance(next_tests, dict)
                    and next_tests.get("success")
                ):
                    repair_state.mark_verified()
                    repair_state.persist(transaction)

                    return {
                        "success": True,
                        "status": (
                            RepairCycleStatus.VERIFIED.value
                        ),
                        "tests": next_tests,
                        "repair": repair_result.get(
                            "repair"
                        ),
                        "repair_attempts": (
                            repair_state.attempts
                        ),
                    }

            if status == RepairExecutorStatus.REPAIR_FAILED.value:
                next_tests = repair_result.get("tests")

                if isinstance(next_tests, dict):
                    test_result = next_tests

                    if repair_state.can_continue():
                        continue

                    repair = repair_result.get("repair")

                    if isinstance(repair, dict):
                        repair = dict(repair)
                        repair["status"] = (
                            RepairCycleStatus.LIMIT_REACHED.value
                        )
                    else:
                        repair = None

                    return {
                        "success": False,
                        "status": (
                            TransactionStatus.ROLLED_BACK.value
                        ),
                        "tests": test_result,
                        "repair": repair,
                        "repair_attempts": (
                            repair_state.attempts
                        ),
                    }

                return {
                    "success": False,
                    "status": (
                        TransactionStatus.ROLLED_BACK.value
                    ),
                    "tests": test_result,
                    "repair": repair_result.get(
                        "repair"
                    ),
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                }

            if status == RepairExecutorStatus.FAILED.value:
                return {
                    "success": False,
                    "status": (
                        TransactionStatus.ROLLED_BACK.value
                    ),
                    "tests": test_result,
                    "repair": repair_result.get(
                        "repair"
                    ),
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                    "error": repair_result.get(
                        "error",
                        "",
                    ),
                }

            if status in {
                RepairCycleStatus.NO_REPAIR.value,
                RepairCycleStatus.LIMIT_REACHED.value,
                TransactionStatus.ROLLED_BACK.value,
            }:
                return {
                    "success": False,
                    "status": (
                        TransactionStatus.ROLLED_BACK.value
                    ),
                    "tests": test_result,
                    "repair": repair_result.get(
                        "repair"
                    ),
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                }

            return {
                "success": False,
                "status": (
                    TransactionStatus.ROLLED_BACK.value
                ),
                "tests": test_result,
                "repair": repair_result.get(
                    "repair"
                ),
                "repair_attempts": (
                    repair_state.attempts
                ),
            }

        return {
            "success": True,
            "status": RepairCycleStatus.VERIFIED.value,
            "tests": test_result,
            "repair": None,
            "repair_attempts": repair_state.attempts,
        }
