from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import RepairExecutor
from core.engine.repair_controller import RepairController
from core.memory.task_history import TaskHistory


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

        self.repair_executor = RepairExecutor(
            security=self.security,
            transaction_manager=self.transactions,
            executor=self.executor,
            test_runner=self.tests,
        )

        self.repair_controller = RepairController(
            max_attempts=self.MAX_REPAIR_ATTEMPTS
        )

        self.history = TaskHistory(
            str(
                self.transactions.root
                / "transactions"
                / "tasks.json"
            )
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

        self.history.create(
            approval_id=approval_id,
            instruction=instruction,
            plan=result,
        )

        return {
            "approval_id": approval_id,
            "status": "pending",
            "plan": result,
        }

    def approve(self, approval_id):

        self.history.update(
            approval_id,
            status="approved",
        )

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

        self.repair_controller.start(
            transaction.transaction_id
        )

        self.history.update(
            approval_id,
            status="executing",
            transaction_id=transaction.transaction_id,
        )

        try:

            for change in transaction.changes:

                self.security.validate_path(
                    change.path
                )

                if change.change_type.value == "create":
                    self.transactions.register_created(
                        transaction,
                        change.path
                    )
                else:
                    self.transactions.backup_file(
                        transaction,
                        change.path
                    )

            self.executor.execute(
                transaction
            )

            while True:

                self.history.update(
                    approval_id,
                    status="testing",
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

                    attempts = (
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        )
                    )

                    self.history.update(
                        approval_id,
                        status="committed",
                        transaction_id=transaction.transaction_id,
                        extra={
                            "tests": test_result,
                            "git": git_result,
                            "repair_attempts": attempts,
                        },
                    )

                    self.repair_controller.reset(
                        transaction.transaction_id
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "committed",
                        "transaction_id": transaction.transaction_id,
                        "tests": test_result,
                        "git": git_result,
                        "repair_attempts": attempts,
                    }

                if not self.repair_controller.register_attempt(
                    transaction.transaction_id
                ):

                    self.transactions.rollback(
                        transaction
                    )

                    attempts = (
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        )
                    )

                    self.history.update(
                        approval_id,
                        status="rolled_back",
                        extra={
                            "tests": test_result,
                            "repair_attempts": attempts,
                            "repair": {
                                "status": "limit_reached"
                            },
                        },
                    )

                    self.repair_controller.reset(
                        transaction.transaction_id
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": transaction.transaction_id,
                        "tests": test_result,
                        "repair_attempts": attempts,
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

                if (
                    diagnosis.get("risk")
                    == "alto"
                ):

                    self.transactions.rollback(
                        transaction
                    )

                    attempts = (
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        )
                    )

                    self.history.update(
                        approval_id,
                        status="rolled_back",
                        extra={
                            "tests": test_result,
                            "repair": diagnosis,
                            "repair_attempts": attempts,
                        },
                    )

                    self.repair_controller.reset(
                        transaction.transaction_id
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": transaction.transaction_id,
                        "tests": test_result,
                        "repair": diagnosis,
                        "repair_attempts": attempts,
                    }

                if (
                    diagnosis.get("action")
                    == "none"
                ):

                    self.transactions.rollback(
                        transaction
                    )

                    attempts = (
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        )
                    )

                    self.history.update(
                        approval_id,
                        status="rolled_back",
                        extra={
                            "tests": test_result,
                            "repair": diagnosis,
                            "repair_attempts": attempts,
                        },
                    )

                    self.repair_controller.reset(
                        transaction.transaction_id
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "rolled_back",
                        "transaction_id": transaction.transaction_id,
                        "tests": test_result,
                        "repair": diagnosis,
                        "repair_attempts": attempts,
                    }

                repair_result = (
                    self.repair_executor.execute_repair(
                        diagnosis,
                        instruction,
                    )
                )

                if repair_result["success"]:

                    attempts = (
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        )
                    )

                    git_result = (
                        self.git.commit_transaction(
                            transaction.transaction_id,
                            instruction,
                        )
                    )

                    self.history.update(
                        approval_id,
                        status="committed",
                        transaction_id=transaction.transaction_id,
                        extra={
                            "tests": repair_result["tests"],
                            "git": git_result,
                            "repair": diagnosis,
                            "repair_attempts": attempts,
                        },
                    )

                    self.repair_controller.reset(
                        transaction.transaction_id
                    )

                    return {
                        "approval_id": approval_id,
                        "status": "committed",
                        "transaction_id": transaction.transaction_id,
                        "tests": repair_result["tests"],
                        "git": git_result,
                        "repair": diagnosis,
                        "repair_attempts": attempts,
                    }

        except Exception as error:

            rollback_error = None

            try:
                self.transactions.rollback(
                    transaction
                )
            except Exception as rollback_exception:
                rollback_error = rollback_exception

            attempts = (
                self.repair_controller.get_attempts(
                    transaction.transaction_id
                )
            )

            failure_extra = {
                "error": str(error),
                "repair_attempts": attempts,
            }

            if rollback_error is not None:
                failure_extra["rollback_error"] = str(
                    rollback_error
                )

            self.history.update(
                approval_id,
                status="failed",
                extra=failure_extra,
            )

            self.repair_controller.reset(
                transaction.transaction_id
            )

            raise

    def reject(self, approval_id):

        result = self.supervisor.reject(
            approval_id
        )

        self.history.update(
            approval_id,
            status="rejected",
        )

        return result

    def list_tasks(self):

        return self.history.list_all()

    def get_task(self, task_id):

        return self.history.get(task_id)

    def latest_task(self):

        return self.history.latest()
