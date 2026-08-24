from datetime import datetime
from pathlib import Path

from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager
from core.schemas.models import TransactionStatus


class DevAgentGateway:

    def __init__(self, agent, root="."):

        self.agent = agent
        self.root = Path(root).resolve()

        self.supervisor = Supervisor()
        self.security = SecurityPolicy(str(self.root))

        self.executor = SafeExecutor(str(self.root))
        self.transactions = TransactionManager(str(self.root))
        self.test_runner = TestRunner(str(self.root))
        self.git = GitManager(str(self.root))

        self.log_file = (
            self.root
            / "transactions"
            / "events.log"
        )

        self.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _log(self, event, transaction_id=None, **data):

        timestamp = datetime.now().isoformat(
            timespec="seconds"
        )

        parts = [
            timestamp,
            event,
        ]

        if transaction_id:
            parts.append(
                f"transaction={transaction_id}"
            )

        for key, value in data.items():
            parts.append(
                f"{key}={value}"
            )

        with self.log_file.open(
            "a",
            encoding="utf-8",
        ) as file:

            file.write(
                " ".join(parts) + "\n"
            )

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

    def approve(self, approval_id):

        request = self.supervisor.approve(
            approval_id
        )

        instruction = request["plan"]["instruction"]

        transaction = self.agent.build_transaction(
            instruction
        )

        transaction = self.transactions.begin(
            transaction
        )

        transaction.status = (
            TransactionStatus.APPROVED
        )

        self._log(
            "task.approved",
            transaction.transaction_id,
            approval_id=approval_id,
        )

        for change in transaction.changes:

            if change.change_type.value in {
                "modify",
                "delete",
            }:

                self.transactions.backup_file(
                    transaction,
                    change.path,
                )

        for change in transaction.changes:

            if change.change_type.value == "create":

                self.transactions.register_created(
                    transaction,
                    change.path,
                )

        try:

            self._log(
                "transaction.executing",
                transaction.transaction_id,
            )

            transaction = self.executor.execute(
                transaction
            )

            self._log(
                "transaction.executed",
                transaction.transaction_id,
            )

            transaction.status = (
                TransactionStatus.TESTING
            )

            self._log(
                "tests.started",
                transaction.transaction_id,
            )

            test_result = self.test_runner.run(
                [
                    change.path
                    for change in transaction.changes
                    if change.change_type.value
                    in {"create", "modify"}
                ]
            )

            if not test_result["success"]:

                self._log(
                    "tests.failed",
                    transaction.transaction_id,
                    returncode=test_result[
                        "returncode"
                    ],
                )

                transaction = (
                    self.transactions.rollback(
                        transaction
                    )
                )

                self._log(
                    "transaction.rolled_back",
                    transaction.transaction_id,
                )

                return {
                    "approval_id": approval_id,
                    "status": "rolled_back",
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "tests": test_result,
                }

            self._log(
                "tests.passed",
                transaction.transaction_id,
            )

            git_result = (
                self.git.commit_transaction(
                    transaction.transaction_id,
                    instruction,
                )
            )

            transaction.status = (
                TransactionStatus.COMMITTED
            )

            self._log(
                "transaction.committed",
                transaction.transaction_id,
            )

            return {
                "approval_id": approval_id,
                "status": "committed",
                "transaction_id": (
                    transaction.transaction_id
                ),
                "tests": test_result,
                "git": git_result,
            }

        except Exception as exc:

            self._log(
                "transaction.error",
                transaction.transaction_id,
                error=repr(exc),
            )

            try:

                transaction = (
                    self.transactions.rollback(
                        transaction
                    )
                )

                self._log(
                    "transaction.rolled_back",
                    transaction.transaction_id,
                    reason="exception",
                )

            except Exception as rollback_error:

                transaction.status = (
                    TransactionStatus.FAILED
                )

                self._log(
                    "rollback.failed",
                    transaction.transaction_id,
                    error=repr(
                        rollback_error
                    ),
                )

                return {
                    "approval_id": approval_id,
                    "status": "failed",
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "error": str(exc),
                    "rollback_error": str(
                        rollback_error
                    ),
                }

            return {
                "approval_id": approval_id,
                "status": "rolled_back",
                "transaction_id": (
                    transaction.transaction_id
                ),
                "error": str(exc),
            }

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
            "result": result,
        }
