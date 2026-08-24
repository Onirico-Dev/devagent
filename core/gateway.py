from pathlib import Path

from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager
from core.engine.repair_executor import RepairExecutor
from core.engine.repair_controller import RepairController


class DevAgentGateway:

    def __init__(self, agent, root="."):

        self.agent = agent
        self.root = Path(root).resolve()

        self.supervisor = Supervisor()

        self.security = SecurityPolicy(
            str(self.root)
        )

        self.executor = SafeExecutor(
            str(self.root)
        )

        self.transaction_manager = (
            TransactionManager(
                str(self.root)
            )
        )

        self.test_runner = TestRunner(
            str(self.root)
        )

        self.git = GitManager(
            str(self.root)
        )

        self.repair_controller = (
            RepairController(
                max_attempts=3
            )
        )

        self.repair_executor = (
            RepairExecutor(
                security=self.security,
                transaction_manager=self.transaction_manager,
                executor=self.executor,
                test_runner=self.test_runner,
            )
        )

        self.events_file = (
            self.root
            / "transactions"
            / "events.log"
        )

        self.events_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

    # ---------------------------------------------------------
    # LOG
    # ---------------------------------------------------------

    def _log(self, event, **data):

        parts = [event]

        for key, value in data.items():

            value = str(value).replace(
                "\n",
                " "
            )

            parts.append(
                f"{key}={value}"
            )

        line = " ".join(parts)

        with self.events_file.open(
            "a",
            encoding="utf-8"
        ) as file:

            from datetime import datetime

            timestamp = (
                datetime.now()
                .isoformat(timespec="seconds")
            )

            file.write(
                f"{timestamp} {line}\n"
            )

    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------

    def create_task(self, instruction):

        result = self.agent.process(
            instruction
        )

        for change in result["changes"]:

            self.security.validate_path(
                change["path"]
            )

        approval_id = (
            self.supervisor.request_approval(
                result
            )
        )

        self._log(
            "task.created",
            approval_id=approval_id,
            instruction=instruction,
        )

        return {
            "approval_id": approval_id,
            "status": "pending",
            "plan": result,
        }

    # ---------------------------------------------------------
    # APPROVAL
    # ---------------------------------------------------------

    def approve(self, approval_id):

        request = self.supervisor.approve(
            approval_id
        )

        plan = request["plan"]

        instruction = plan[
            "instruction"
        ]

        self._log(
            "task.approved",
            approval_id=approval_id,
        )

        transaction = (
            self.agent.build_transaction(
                instruction
            )
        )

        transaction = (
            self.transaction_manager.begin(
                transaction
            )
        )

        transaction_id = (
            transaction.transaction_id
        )

        self.repair_controller.start(
            transaction_id
        )

        self._log(
            "transaction.executing",
            transaction=transaction_id,
        )

        try:

            # -------------------------------------------------
            # PREPARAÇÃO DO BACKUP
            # -------------------------------------------------

            for change in transaction.changes:

                self.security.validate_path(
                    change.path
                )

                if (
                    change.change_type.value
                    == "modify"
                ):

                    self.transaction_manager.backup_file(
                        transaction,
                        change.path,
                    )

                elif (
                    change.change_type.value
                    == "create"
                ):

                    self.transaction_manager.register_created(
                        transaction,
                        change.path,
                    )

            # -------------------------------------------------
            # PRIMEIRA EXECUÇÃO
            # -------------------------------------------------

            transaction = (
                self.executor.execute(
                    transaction
                )
            )

            self._log(
                "transaction.executed",
                transaction=transaction_id,
            )

            # -------------------------------------------------
            # TESTE
            # -------------------------------------------------

            self._log(
                "tests.started",
                transaction=transaction_id,
            )

            test_result = (
                self.test_runner.run(
                    [
                        change.path
                        for change
                        in transaction.changes
                    ]
                )
            )

            if test_result["success"]:

                self._log(
                    "tests.passed",
                    transaction=transaction_id,
                )

                transaction.metadata[
                    "tests"
                ] = test_result

                git_result = (
                    self.git.commit_transaction(
                        transaction_id,
                        instruction,
                    )
                )

                self._log(
                    "transaction.committed",
                    transaction=transaction_id,
                )

                return {
                    "approval_id": approval_id,
                    "status": "committed",
                    "transaction_id": transaction_id,
                    "tests": test_result,
                    "git": git_result,
                }

            # -------------------------------------------------
            # PRIMEIRA FALHA
            # -------------------------------------------------

            self._log(
                "tests.failed",
                transaction=transaction_id,
                returncode=test_result[
                    "returncode"
                ],
            )

            last_error = (
                test_result.get(
                    "stderr",
                    ""
                )
                or test_result.get(
                    "stdout",
                    ""
                )
            )

            repair_results = []

            # -------------------------------------------------
            # CICLO DE REPARO
            # -------------------------------------------------

            while self.repair_controller.can_repair(
                transaction_id
            ):

                allowed = (
                    self.repair_controller.register_attempt(
                        transaction_id
                    )
                )

                if not allowed:
                    break

                attempt = (
                    self.repair_controller.get_attempts(
                        transaction_id
                    )
                )

                self._log(
                    "repair.started",
                    transaction=transaction_id,
                    attempt=attempt,
                )

                diagnosis = (
                    self.agent.analyze_failure(
                        instruction=instruction,
                        error=last_error,
                        test_output=test_result,
                    )
                )

                repair_results.append(
                    {
                        "attempt": attempt,
                        "diagnosis": diagnosis,
                    }
                )

                if diagnosis.get(
                    "action"
                ) == "none":

                    self._log(
                        "repair.unavailable",
                        transaction=transaction_id,
                        attempt=attempt,
                    )

                    break

                repair_result = (
                    self.repair_executor.execute_repair(
                        diagnosis,
                        instruction,
                    )
                )

                repair_results[-1][
                    "result"
                ] = repair_result

                if repair_result[
                    "success"
                ]:

                    self._log(
                        "repair.succeeded",
                        transaction=transaction_id,
                        attempt=attempt,
                    )

                    git_result = (
                        self.git.commit_transaction(
                            transaction_id,
                            instruction,
                        )
                    )

                    self._log(
                        "transaction.committed",
                        transaction=transaction_id,
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "committed",
                        "transaction_id": transaction_id,
                        "tests": repair_result[
                            "tests"
                        ],
                        "repairs": repair_results,
                        "git": git_result,
                    }

                self._log(
                    "repair.failed",
                    transaction=transaction_id,
                    attempt=attempt,
                )

                last_error = (
                    repair_result.get(
                        "error",
                        ""
                    )
                    or str(
                        repair_result.get(
                            "tests",
                            {}
                        )
                    )
                )

                test_result = (
                    repair_result.get(
                        "tests",
                        test_result,
                    )
                )

            # -------------------------------------------------
            # LIMITE ATINGIDO OU REPARO IMPOSSÍVEL
            # -------------------------------------------------

            transaction = (
                self.transaction_manager.rollback(
                    transaction
                )
            )

            self._log(
                "transaction.rolled_back",
                transaction=transaction_id,
            )

            return {
                "approval_id": approval_id,
                "status": "rolled_back",
                "transaction_id": transaction_id,
                "tests": test_result,
                "repairs": repair_results,
                "message": (
                    "A execução falhou e o DevAgent "
                    "não conseguiu corrigir o problema "
                    "dentro do limite permitido."
                ),
            }

        except Exception as error:

            self._log(
                "transaction.failed",
                transaction=transaction_id,
                error=str(error),
            )

            try:

                transaction = (
                    self.transaction_manager.rollback(
                        transaction
                    )
                )

                self._log(
                    "transaction.rolled_back",
                    transaction=transaction_id,
                )

                return {
                    "approval_id": approval_id,
                    "status": "rolled_back",
                    "transaction_id": transaction_id,
                    "error": str(error),
                }

            except Exception as rollback_error:

                self._log(
                    "rollback.failed",
                    transaction=transaction_id,
                    error=str(
                        rollback_error
                    ),
                )

                return {
                    "approval_id": approval_id,
                    "status": "failed",
                    "transaction_id": transaction_id,
                    "error": str(error),
                    "rollback_error": str(
                        rollback_error
                    ),
                }

    # ---------------------------------------------------------
    # REJECT
    # ---------------------------------------------------------

    def reject(self, approval_id):

        result = self.supervisor.reject(
            approval_id
        )

        self._log(
            "task.rejected",
            approval_id=approval_id,
        )

        return {
            "approval_id": approval_id,
            "status": "rejected",
        }
