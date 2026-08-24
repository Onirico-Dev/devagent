from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager
from core.engine.repair_engine import RepairEngine


class DevAgentGateway:

    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self, agent, root="."):
        self.agent = agent
        self.root = root

        self.supervisor = Supervisor()
        self.security = SecurityPolicy(root)

        self.executor = SafeExecutor(root)
        self.transactions = TransactionManager(root)
        self.tests = TestRunner(root)
        self.git = GitManager(root)

        self.repair_engine = RepairEngine(
            agent.ai
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

        return {
            "approval_id": approval_id,
            "status": "pending",
            "plan": result,
        }

    def approve(self, approval_id):

        request = self.supervisor.approve(
            approval_id
        )

        instruction = request["plan"][
            "instruction"
        ]

        transaction = self.agent.build_transaction(
            instruction
        )

        transaction = self.transactions.begin(
            transaction
        )

        repair_attempts = 0

        try:

            while True:

                transaction.status = (
                    transaction.status
                )

                for change in transaction.changes:

                    self.security.validate_path(
                        change.path
                    )

                    if (
                        change.change_type.value
                        != "create"
                    ):
                        self.transactions.backup_file(
                            transaction,
                            change.path
                        )

                self.executor.execute(
                    transaction
                )

                for change in transaction.changes:

                    if (
                        change.change_type.value
                        == "create"
                    ):
                        self.transactions.register_created(
                            transaction,
                            change.path
                        )

                test_result = self.tests.run(
                    [
                        change.path
                        for change in transaction.changes
                    ]
                )

                if test_result["success"]:

                    git_result = (
                        self.git.commit_transaction(
                            transaction.transaction_id,
                            instruction,
                        )
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "committed",
                        "transaction_id": (
                            transaction.transaction_id
                        ),
                        "tests": test_result,
                        "git": git_result,
                        "repair_attempts": (
                            repair_attempts
                        ),
                    }

                repair_attempts += 1

                if (
                    repair_attempts
                    > self.MAX_REPAIR_ATTEMPTS
                ):
                    self.transactions.rollback(
                        transaction
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": (
                            transaction.transaction_id
                        ),
                        "tests": test_result,
                        "repair_attempts": (
                            repair_attempts
                        ),
                        "repair": {
                            "status": "limit_reached"
                        },
                    }

                diagnosis = (
                    self.repair_engine.analyze_failure(
                        instruction=instruction,
                        error=test_result.get(
                            "stderr",
                            ""
                        ),
                        test_output=test_result.get(
                            "stdout",
                            ""
                        ),
                    )
                )

                if not diagnosis.get(
                    "correction"
                ):
                    self.transactions.rollback(
                        transaction
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": (
                            transaction.transaction_id
                        ),
                        "tests": test_result,
                        "repair_attempts": (
                            repair_attempts
                        ),
                        "repair": diagnosis,
                    }

                if diagnosis.get("risk") == "alto":

                    self.transactions.rollback(
                        transaction
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": (
                            transaction.transaction_id
                        ),
                        "tests": test_result,
                        "repair_attempts": (
                            repair_attempts
                        ),
                        "repair": {
                            **diagnosis,
                            "status": (
                                "high_risk_blocked"
                            ),
                        },
                    }

                self.transactions.rollback(
                    transaction
                )

                return {
                    "approval_id": approval_id,
                    "status": "rolled_back",
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "tests": test_result,
                    "repair_attempts": (
                        repair_attempts
                    ),
                    "repair": {
                        **diagnosis,
                        "status": (
                            "proposal_requires_next_step"
                        ),
                    },
                }

        except Exception:

            try:
                self.transactions.rollback(
                    transaction
                )
            except Exception:
                pass

            raise

    def reject(self, approval_id):

        return self.supervisor.reject(
            approval_id
        )
