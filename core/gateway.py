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


from core.engine.repair_cycle_state import RepairCycleState
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

        self.repair_engine = RepairEngine(agent.ai)

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

    def _update_history_safe(
        self,
        approval_id,
        status=None,
        transaction_id=None,
        extra=None,
    ):
        """
        Atualiza o histórico quando a tarefa existe.

        O Gateway também pode ser exercitado diretamente em testes
        através do Supervisor. Nesse caso, a aprovação pode não ter
        sido registrada no TaskHistory previamente.
        """
        try:
            return self.history.update(
                approval_id,
                status=status,
                transaction_id=transaction_id,
                extra=extra,
            )
        except KeyError as exc:
            if str(exc) != "'Tarefa não encontrada.'":
                raise
            return None

    def create_task(self, instruction):
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("Instrução inválida.")

        result = self.agent.process(instruction)

        if not isinstance(result, dict):
            raise ValueError("Plano inválido retornado pelo agente.")

        changes = result.get("changes")

        if not isinstance(changes, list):
            raise ValueError("Plano não possui lista de alterações.")

        for change in changes:
            if not isinstance(change, dict):
                raise ValueError("Alteração inválida no plano.")

            path = change.get("path")
            if not path:
                raise ValueError("Alteração sem caminho.")

            self.security.validate_path(path)

            content = change.get("content")

            if change.get("change_type") != "delete":
                if not isinstance(content, str):
                    raise ValueError(
                        f"Conteúdo inválido para alteração: {path}"
                    )

                self.security.validate_content(content)

        approval_id = self.supervisor.request_approval(result)

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

    def execute_approved(self, approval_id):
        request = self.supervisor.get(approval_id)

        if request is None:
            raise KeyError("Tarefa não encontrada.")

        if request.get("status") != "approved":
            raise ValueError("Tarefa não está aprovada.")

        return self.approve(approval_id)

    def _evaluate_execution(self, result):
        if not isinstance(result, dict):
            return "rollback"

        if not result.get("success"):
            return "repair"

        verification = result.get("verification")

        if verification is not None and not verification.get("success"):
            return "repair"

        tests = result.get("tests")

        if isinstance(tests, dict) and not tests.get("success", False):
            return "repair"

        return "commit"

    def _attempt_repair(self, instruction, transaction, test_result):
        if not self.repair_controller.can_repair(
            transaction.transaction_id
        ):
            return {
                "status": "limit_reached",
                "success": False,
            }

        diagnosis = self.repair_engine.analyze_failure(
            instruction=instruction,
            error=test_result.get("stderr", ""),
            test_output=test_result.get("stdout", ""),
        )

        if diagnosis.get("risk") == "alto":
            return {
                "status": "high_risk",
                "success": False,
                "repair": diagnosis,
            }

        if diagnosis.get("action") == "none":
            return {
                "status": "no_repair",
                "success": False,
                "repair": diagnosis,
            }

        if not self.repair_controller.register_attempt(
            transaction.transaction_id
        ):
            return {
                "status": "limit_reached",
                "success": False,
            }

        result = self.repair_executor.execute_repair(
            diagnosis,
            instruction,
            transaction,
        )

        result["repair"] = diagnosis
        result["transaction_id"] = transaction.transaction_id
        result["repair_attempts"] = (
            self.repair_controller.get_attempts(
                transaction.transaction_id
            )
        )

        return result

    def _run_repair_cycle(
        self,
        instruction,
        transaction,
        test_result,
    ):
        while (
            not test_result.get("success", False)
            and self.repair_controller.can_repair(
                transaction.transaction_id
            )
        ):
            repair_result = self._attempt_repair(
                instruction,
                transaction,
                test_result,
            )

            if not repair_result.get("success"):
                return {
                    "success": False,
                    "status": repair_result.get(
                        "status",
                        "rollback",
                    ),
                    "tests": test_result,
                    "repair": repair_result.get("repair"),
                    "repair_attempts": repair_result.get(
                        "repair_attempts",
                        self.repair_controller.get_attempts(
                            transaction.transaction_id
                        ),
                    ),
                }

            test_result = repair_result.get(
                "tests",
                test_result,
            )

        repair_state = RepairCycleState(
            transaction.transaction_id,
            status="verified",
            attempts=self.repair_controller.get_attempts(
                transaction.transaction_id
            ),
        )

        transaction.repair_state = repair_state.to_dict()

        transaction.metadata["repair_cycle"] = {
            "status": repair_state.status,
            "attempts": repair_state.attempts,
        }

        return {
            "success": True,
            "status": "verified",
            "tests": test_result,
            "repair_attempts": self.repair_controller.get_attempts(
                transaction.transaction_id
            ),
        }

    def approve(self, approval_id):
        self._update_history_safe(
            approval_id,
            status="approved",
        )

        request = self.supervisor.approve(approval_id)

        instruction = request["plan"]["instruction"]

        transaction = self.agent.build_transaction(instruction)
        transaction = self.transactions.begin(transaction)

        repair_state = RepairCycleState.restore(transaction)

        self.repair_controller.max_attempts = repair_state.max_attempts

        self.repair_controller.restore_state(
            transaction.transaction_id,
            repair_state.attempts,
        )

        repair_state.persist(transaction)

        if not repair_state.can_continue():
            return {
                "success": False,
                "status": repair_state.status,
                "transaction_id": transaction.transaction_id,
                "repair_state": repair_state.to_dict(),
            }

        self.repair_controller.start(transaction.transaction_id)

        self._update_history_safe(
            approval_id,
            status="executing",
            transaction_id=transaction.transaction_id,
        )

        try:
            for change in transaction.changes:
                self.security.validate_path(change.path)

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

            self.executor.execute(transaction)

            repair_state.mark_testing()
            repair_state.persist(transaction)

            while True:
                self._update_history_safe(
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
                    git_result = self.git.commit_transaction(
                        transaction.transaction_id,
                        instruction,
                        paths=[
                            change.path
                            for change in transaction.changes
                        ],
                    )

                    if git_result.get("status") != "committed":
                        raise RuntimeError(
                            "Commit Git não foi concluído: "
                            f"{git_result.get('status', 'desconhecido')}"
                        )

                    from core.schemas.models import TransactionStatus
                    transaction.status = TransactionStatus.COMMITTED

                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    self._update_history_safe(
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

                # =========================================================
                # LIMITE DE REPAROS:
                #
                # A verificação precisa ocorrer ANTES de chamar a IA para
                # uma nova análise. Isso impede uma terceira análise quando
                # as duas tentativas permitidas já foram consumidas.
                # =========================================================
                if not self.repair_controller.can_repair(
                    transaction.transaction_id
                ):
                    self.transactions.rollback(transaction)

                    repair_state.mark_rolled_back()
                    repair_state.persist(transaction)

                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    limit_repair = {
                        "diagnosis": (
                            "Limite máximo de tentativas de reparo "
                            "atingido."
                        ),
                        "correction": (
                            "Nenhuma nova correção automática será "
                            "tentada."
                        ),
                        "risk": "baixo",
                        "action": "none",
                        "path": "",
                        "content": "",
                        "status": "limit_reached",
                    }

                    self._update_history_safe(
                        approval_id,
                        status="rolled_back",
                        extra={
                            "tests": test_result,
                            "repair": limit_repair,
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
                        "repair": limit_repair,
                        "repair_attempts": attempts,
                    }

                # =========================================================
                # A análise só ocorre quando existe uma tentativa
                # disponível.
                # =========================================================
                diagnosis = self.repair_engine.analyze_failure(
                    instruction=instruction,
                    error=test_result.get("stderr", ""),
                    test_output=test_result.get("stdout", ""),
                )

                # Alto risco não consome tentativa e nunca é aplicado.
                if diagnosis.get("risk") == "alto":
                    self.transactions.rollback(transaction)

                    repair_state.mark_rolled_back()
                    repair_state.persist(transaction)

                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    self._update_history_safe(
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

                if diagnosis.get("action") == "none":
                    self.transactions.rollback(transaction)

                    repair_state.mark_rolled_back()
                    repair_state.persist(transaction)

                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    self._update_history_safe(
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

                # Registra a tentativa somente depois que a análise
                # confirmou que existe uma correção aplicável.
                if not self.repair_controller.register_attempt(
                    transaction.transaction_id
                ):
                    self.transactions.rollback(transaction)

                    repair_state.mark_rolled_back()
                    repair_state.persist(transaction)

                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    limit_repair = {
                        **diagnosis,
                        "status": "limit_reached",
                    }

                    self._update_history_safe(
                        approval_id,
                        status="rolled_back",
                        extra={
                            "tests": test_result,
                            "repair": limit_repair,
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
                        "repair": limit_repair,
                        "repair_attempts": attempts,
                    }

                repair_result = self.repair_executor.execute_repair(
                    diagnosis,
                    instruction,
                    transaction,
                )

                if repair_result["success"]:
                    attempts = self.repair_controller.get_attempts(
                        transaction.transaction_id
                    )

                    git_result = self.git.commit_transaction(
                        transaction.transaction_id,
                        instruction,
                        paths=[
                            change.path
                            for change in transaction.changes
                        ],
                    )

                    if git_result.get("status") != "committed":
                        raise RuntimeError(
                            "Commit Git não foi concluído: "
                            f"{git_result.get('status', 'unknown')}"
                            + (
                                f" — {git_result.get('message')}"
                                if git_result.get("message")
                                else ""
                            )
                        )

                    self._update_history_safe(
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
                self.transactions.rollback(transaction)
            except Exception as rollback_exception:
                rollback_error = rollback_exception

            attempts = self.repair_controller.get_attempts(
                transaction.transaction_id
            )

            failure_extra = {
                "error": str(error),
                "repair_attempts": attempts,
            }

            if rollback_error is not None:
                failure_extra["rollback_error"] = str(
                    rollback_error
                )

            self._update_history_safe(
                approval_id,
                status="failed",
                extra=failure_extra,
            )

            self.repair_controller.reset(
                transaction.transaction_id
            )

            raise

    def reject(self, approval_id):
        result = self.supervisor.reject(approval_id)

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
