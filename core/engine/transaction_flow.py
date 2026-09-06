from core.engine.repair_cycle_state import RepairCycleState
from core.memory.task_history import TaskHistoryStatus
from core.schemas.models import TransactionStatus
from core.supervisor import ApprovalStatus
from core.executor.git_manager import GitStatus


class TransactionFlow:
    """Orquestra aprovação, execução, verificação e finalização de transações."""

    def __init__(
        self,
        agent,
        supervisor,
        security,
        executor,
        transactions,
        tests,
        git,
        repair_controller,
        repair_flow,
        history,
        history_update_fn,
        restore_repair_state_fn,
        repair_cycle_fn,
        commit_error_type=RuntimeError,
    ):
        self.agent = agent
        self.supervisor = supervisor
        self.security = security
        self.executor = executor
        self.transactions = transactions
        self.tests = tests
        self.git = git
        self.repair_controller = repair_controller
        self.repair_flow = repair_flow
        self.history = history

        self._history_update = history_update_fn
        self._restore_repair_state = restore_repair_state_fn
        self._repair_cycle = repair_cycle_fn
        self.commit_error_type = commit_error_type

    def evaluate_execution(self, result):
        if not isinstance(result, dict):
            return "rollback"

        if not result.get("success"):
            return "repair"

        verification = result.get("verification")
        if (
            verification is not None
            and (
                not isinstance(verification, dict)
                or not verification.get("success")
            )
        ):
            return "repair"

        tests = result.get("tests")
        if (
            tests is not None
            and (
                not isinstance(tests, dict)
                or not tests.get("success", False)
            )
        ):
            return "repair"

        return "commit"

    def approve_locked(
        self,
        approval_id,
        commit_fn,
        rollback_fn,
    ):
        request = self.supervisor.prepare_approval(
            approval_id
        )

        instruction = request["plan"]["instruction"]

        if self.history.get(approval_id) is None:
            self.history.create(
                approval_id=approval_id,
                instruction=instruction,
                plan=request["plan"],
            )

        transaction = self._build_transaction(
            request["plan"]
        )

        transaction = self.transactions.begin(
            transaction
        )

        repair_state = self._restore_repair_state(
            transaction
        )

        repair_state.persist(transaction)

        self.repair_controller.start(
            transaction.transaction_id
        )

        self.supervisor.approve(
            approval_id
        )

        self._history_update(
            approval_id,
            status=TaskHistoryStatus.EXECUTING.value,
            transaction_id=transaction.transaction_id,
        )

        try:
            test_result = self._execute_and_test_transaction(
                transaction,
                repair_state,
                approval_id,
            )

            return self._finalize_execution_result(
                approval_id=approval_id,
                instruction=instruction,
                transaction=transaction,
                repair_state=repair_state,
                test_result=test_result,
                commit_fn=commit_fn,
                rollback_fn=rollback_fn,
            )

        except Exception as error:
            return self._handle_transaction_exception(
                error=error,
                approval_id=approval_id,
                transaction=transaction,
                repair_state=repair_state,
                rollback_fn=rollback_fn,
            )

    def _execute_and_test_transaction(
        self,
        transaction,
        repair_state,
        approval_id,
    ):
        self._prepare_transaction(transaction)

        self.executor.execute(
            transaction
        )

        repair_state.mark_testing()
        repair_state.persist(transaction)

        self._history_update(
            approval_id,
            status=TaskHistoryStatus.TESTING.value,
            transaction_id=transaction.transaction_id,
        )

        test_result = self.tests.run(
            [
                change.path
                for change in transaction.changes
            ]
        )

        return self._run_declared_tests(
            transaction,
            test_result,
        )

    def _finalize_execution_result(
        self,
        approval_id,
        instruction,
        transaction,
        repair_state,
        test_result,
        commit_fn,
        rollback_fn,
    ):
        if test_result.get("success"):
            return commit_fn(
                approval_id=approval_id,
                instruction=instruction,
                transaction=transaction,
                test_result=test_result,
                repair_state=repair_state,
            )

        repair_cycle = self._repair_cycle(
            instruction=instruction,
            transaction=transaction,
            test_result=test_result,
            repair_state=repair_state,
        )

        if repair_cycle.get("success"):
            return commit_fn(
                approval_id=approval_id,
                instruction=instruction,
                transaction=transaction,
                test_result=repair_cycle["tests"],
                repair_state=repair_state,
                repair=repair_cycle.get("repair"),
            )

        return rollback_fn(
            approval_id=approval_id,
            transaction=transaction,
            repair_state=repair_state,
            test_result=repair_cycle.get(
                "tests",
                test_result,
            ),
            repair=repair_cycle.get(
                "repair"
            ),
            status=TaskHistoryStatus.ROLLED_BACK.value,
            error=repair_cycle.get(
                "error"
            ),
        )

    def commit_transaction(
        self,
        approval_id,
        instruction,
        transaction,
        test_result,
        repair_state,
        repair=None,
    ):
        git_result = self.git.commit_transaction(
            transaction.transaction_id,
            instruction,
            paths=[
                change.path
                for change in transaction.changes
            ],
        )

        if not isinstance(git_result, dict):
            error = self.commit_error_type(
                "Resultado de commit Git inválido."
            )
            error.result = git_result
            raise error

        if git_result.get("status") != GitStatus.COMMITTED.value:
            error = self.commit_error_type(
                "Commit Git não foi concluído: "
                f"{git_result.get('status', 'desconhecido')}"
                + (
                    f" — {git_result.get('message')}"
                    if git_result.get("message")
                    else ""
                )
            )
            error.result = git_result
            raise error

        transaction.status = TransactionStatus.COMMITTED
        repair_state.mark_committed()
        self.transactions.persist_manifest(transaction)
        repair_state.persist(transaction)

        attempts = repair_state.attempts

        extra = {
            "tests": test_result,
            "git": git_result,
            "repair_attempts": attempts,
            "metadata": dict(transaction.metadata),
            "repair_state": dict(transaction.repair_state),
        }

        if repair is not None:
            extra["repair"] = repair

        self._history_update(
            approval_id,
            status=TaskHistoryStatus.COMMITTED.value,
            transaction_id=transaction.transaction_id,
            extra=extra,
        )

        self.repair_controller.reset(
            transaction.transaction_id
        )

        return {
            "approval_id": approval_id,
            "status": TransactionStatus.COMMITTED.value,
            "transaction_id": transaction.transaction_id,
            "tests": test_result,
            "git": git_result,
            "repair_attempts": attempts,
            **(
                {"repair": repair}
                if repair is not None
                else {}
            ),
        }

    def rollback_transaction(
        self,
        approval_id,
        transaction,
        repair_state,
        test_result=None,
        repair=None,
        status=TaskHistoryStatus.ROLLED_BACK.value,
        error=None,
    ):
        rollback_error = None

        try:
            self.transactions.rollback(
                transaction
            )
        except Exception as exc:
            rollback_error = exc

        if rollback_error is not None:
            transaction.status = TransactionStatus.FAILED
            repair_state.mark_failed(
                str(rollback_error)
            )
        else:
            repair_state.mark_rolled_back(
                error or ""
            )

        self.transactions.persist_manifest(transaction)
        repair_state.persist(transaction)

        attempts = repair_state.attempts

        extra = {
            "repair_attempts": attempts,
            "metadata": dict(transaction.metadata),
            "repair_state": dict(transaction.repair_state),
        }

        if test_result is not None:
            extra["tests"] = test_result

        if repair is not None:
            extra["repair"] = repair

        if error is not None:
            extra["error"] = str(error)

        if rollback_error is not None:
            extra["rollback_error"] = str(
                rollback_error
            )

        final_status = (
            TaskHistoryStatus.FAILED.value
            if rollback_error is not None
            else status
        )

        self._history_update(
            approval_id,
            status=final_status,
            transaction_id=transaction.transaction_id,
            extra=extra,
        )

        self.repair_controller.reset(
            transaction.transaction_id
        )

        return {
            "approval_id": approval_id,
            "status": final_status,
            "success": False,
            "transaction_id": transaction.transaction_id,
            "tests": test_result,
            "repair": repair,
            "repair_attempts": attempts,
            **(
                {"error": str(error)}
                if error is not None
                else {}
            ),
            **(
                {
                    "rollback_error": str(
                        rollback_error
                    )
                }
                if rollback_error is not None
                else {}
            ),
        }

    def _build_transaction(self, plan):
        return self.agent.build_transaction_from_approved_plan(
            plan
        )

    def _prepare_transaction(self, transaction):
        for change in transaction.changes:
            self.security.validate_path(
                change.path
            )

            if change.change_type.value == "create":
                self.transactions.register_created(
                    transaction,
                    change.path,
                )
            else:
                self.transactions.backup_file(
                    transaction,
                    change.path,
                )

    def _run_declared_tests(self, transaction, test_result):
        declared_tests = transaction.metadata.get(
            "tests",
            [],
        )

        if test_result.get("success") and declared_tests:
            semantic_result = self.tests.run_tests(
                declared_tests,
            )

            return {
                "success": (
                    test_result.get("success", False)
                    and semantic_result.get(
                        "success",
                        False,
                    )
                ),
                "returncode": (
                    semantic_result.get(
                        "returncode",
                        test_result.get(
                            "returncode",
                            1,
                        ),
                    )
                    if not semantic_result.get(
                        "success",
                        False,
                    )
                    else test_result.get(
                        "returncode",
                        0,
                    )
                ),
                "stdout": "\n".join(
                    part
                    for part in (
                        test_result.get(
                            "stdout",
                            "",
                        ),
                        semantic_result.get(
                            "stdout",
                            "",
                        ),
                    )
                    if part
                ),
                "stderr": "\n".join(
                    part
                    for part in (
                        test_result.get(
                            "stderr",
                            "",
                        ),
                        semantic_result.get(
                            "stderr",
                            "",
                        ),
                    )
                    if part
                ),
            }

        return test_result

    def _handle_transaction_exception(
        self,
        error,
        approval_id,
        transaction,
        repair_state,
        rollback_fn,
    ):

        if isinstance(error, self.commit_error_type):
            rollback_result = rollback_fn(
                approval_id=approval_id,
                transaction=transaction,
                repair_state=repair_state,
                error=str(error),
                status=TaskHistoryStatus.ROLLED_BACK.value,
            )

            if rollback_result.get("rollback_error"):
                raise RuntimeError(
                    rollback_result["rollback_error"]
                ) from error

            error.result = {
                **(
                    error.result
                    if isinstance(error.result, dict)
                    else {}
                ),
                "rollback": rollback_result,
            }

            raise

        result = rollback_fn(
            approval_id=approval_id,
            transaction=transaction,
            repair_state=repair_state,
            error=error,
            status=TaskHistoryStatus.FAILED.value,
        )

        if result.get("rollback_error"):
            raise RuntimeError(
                result["rollback_error"]
            ) from error

        return result
