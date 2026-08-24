from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager


class DevAgentGateway:

    def __init__(self, agent, root="."):

        self.agent = agent
        self.root = root

        self.supervisor = Supervisor()
        self.security = SecurityPolicy(root)

        self.executor = SafeExecutor(root)
        self.transactions = TransactionManager(root)
        self.test_runner = TestRunner(root)
        self.git = GitManager(root)

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

        # Backup dos arquivos existentes.
        for change in transaction.changes:

            if change.change_type.value in {
                "modify",
                "delete",
            }:

                self.transactions.backup_file(
                    transaction,
                    change.path,
                )

        # Registrar arquivos novos.
        for change in transaction.changes:

            if change.change_type.value == "create":

                self.transactions.register_created(
                    transaction,
                    change.path,
                )

        try:

            # 1. Executar
            transaction = self.executor.execute(
                transaction
            )

            # 2. Testar
            test_result = self.test_runner.run(
                [
                    change.path
                    for change in transaction.changes
                ]
            )

            # 3. Falha → rollback
            if not test_result["success"]:

                transaction = self.transactions.rollback(
                    transaction
                )

                return {
                    "approval_id": approval_id,
                    "status": "rolled_back",
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "tests": {
                        "success": False,
                        "returncode": (
                            test_result["returncode"]
                        ),
                        "stdout": (
                            test_result["stdout"]
                        ),
                        "stderr": (
                            test_result["stderr"]
                        ),
                    },
                }

            # 4. Testes passaram → commit Git
            git_result = self.git.commit_transaction(
                transaction.transaction_id,
                instruction,
            )

            return {
                "approval_id": approval_id,
                "status": "committed",
                "transaction_id": (
                    transaction.transaction_id
                ),
                "tests": {
                    "success": True,
                    "returncode": (
                        test_result["returncode"]
                    ),
                    "stdout": (
                        test_result["stdout"]
                    ),
                    "stderr": (
                        test_result["stderr"]
                    ),
                },
                "git": git_result,
            }

        except Exception as exc:

            try:

                transaction = self.transactions.rollback(
                    transaction
                )

            except Exception as rollback_error:

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

        return {
            "approval_id": approval_id,
            "status": "rejected",
            "result": result,
        }
