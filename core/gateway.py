from pathlib import Path
from threading import RLock
from core.security import SecurityPolicy
from core.supervisor import ApprovalStatus, Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager, GitStatus
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import RepairExecutor, RepairExecutorStatus
from core.engine.repair_controller import RepairController
from core.engine.repair_cycle_state import RepairCycleState, RepairCycleStatus
from core.engine.repair_flow import RepairFlow
from core.engine.transaction_flow import TransactionFlow
from core.memory.task_history import TaskHistory, TaskHistoryStatus
from core.schemas.models import TransactionStatus


class CommitTransactionError(RuntimeError):
    """Falha esperada durante o commit Git de uma transação."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result or {}


class DevAgentGateway:
    _approval_locks = {}
    _approval_locks_guard = RLock()

    @classmethod
    def _approval_lock_for(cls, approval_id):
        key = str(approval_id)

        with cls._approval_locks_guard:
            lock = cls._approval_locks.get(key)

            if lock is None:
                lock = RLock()
                cls._approval_locks[key] = lock

            return lock

    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self, agent, root="."):
        self.agent = agent
        self.root = root

        self.supervisor = Supervisor(
            storage_path=(
                Path(root).resolve()
                / "transactions"
                / "approvals.json"
            )
        )
        self.security = SecurityPolicy(root)
        self.executor = SafeExecutor(root)
        self.transactions = TransactionManager(root)
        self.transactions.recover_incomplete_transactions()
        self.tests = TestRunner(root)
        self.git = GitManager(root)

        self.repair_engine = RepairEngine(
            agent.ai if agent is not None and hasattr(agent, "ai") else None
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

        self.repair_flow = RepairFlow(
            repair_engine=self.repair_engine,
            repair_executor=self.repair_executor,
            repair_controller=self.repair_controller,
            max_attempts=self.MAX_REPAIR_ATTEMPTS,
        )

        self.transaction_flow = TransactionFlow(
            agent=self.agent,
            supervisor=self.supervisor,
            security=self.security,
            executor=self.executor,
            transactions=self.transactions,
            tests=self.tests,
            git=self.git,
            repair_controller=self.repair_controller,
            repair_flow=self.repair_flow,
            history=self.history,
            history_update_fn=self._update_history_safe,
            restore_repair_state_fn=lambda transaction: (
                self._restore_repair_state(transaction)
            ),
            repair_cycle_fn=lambda **kwargs: (
                self._run_repair_cycle(**kwargs)
            ),
            commit_error_type=CommitTransactionError,
        )

    # ------------------------------------------------------------------
    # HISTORY
    # ------------------------------------------------------------------

    def _history_update(
        self,
        approval_id,
        status=None,
        transaction_id=None,
        extra=None,
    ):
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

    def _update_history_safe(
        self,
        approval_id,
        status=None,
        transaction_id=None,
        extra=None,
    ):
        return self._history_update(
            approval_id,
            status=status,
            transaction_id=transaction_id,
            extra=extra,
        )

    # ------------------------------------------------------------------
    # TASK CREATION
    # ------------------------------------------------------------------

    def create_task(self, instruction):
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("Instrução inválida.")

        result = self.agent.process(instruction)

        if not isinstance(result, dict):
            raise ValueError(
                "Plano inválido retornado pelo agente."
            )

        changes = result.get("changes")

        if not isinstance(changes, list):
            raise ValueError(
                "Plano não possui lista de alterações."
            )

        for change in changes:
            if not isinstance(change, dict):
                raise ValueError(
                    "Alteração inválida no plano."
                )

            path = change.get("path")

            if not path:
                raise ValueError(
                    "Alteração sem caminho."
                )

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
            "status": ApprovalStatus.PENDING.value,
            "plan": result,
        }

    # ------------------------------------------------------------------
    # EXECUTION DECISION
    # ------------------------------------------------------------------

    def execute_approved(self, approval_id):
        request = self.supervisor.get(approval_id)

        if request is None:
            raise KeyError("Tarefa não encontrada.")

        if request.get("status") != ApprovalStatus.APPROVED.value:
            raise ValueError(
                "Tarefa não está aprovada."
            )

        return self.approve(approval_id)

    def _evaluate_execution(self, result):
        return self.transaction_flow.evaluate_execution(result)

    # ------------------------------------------------------------------
    # REPAIR STATE
    # ------------------------------------------------------------------

    def _restore_repair_state(self, transaction):
        return self.repair_flow.restore_state(transaction)

    def _sync_repair_controller(self, transaction, state):
        return self.repair_flow.sync_controller(
            transaction,
            state,
        )

    # ------------------------------------------------------------------
    # SINGLE REPAIR ATTEMPT
    # ------------------------------------------------------------------

    def _attempt_repair(
        self,
        instruction,
        transaction,
        test_result,
        repair_state,
    ):
        return self.repair_flow.attempt(
            instruction=instruction,
            transaction=transaction,
            test_result=test_result,
            repair_state=repair_state,
        )

    def _run_repair_cycle(
        self,
        instruction,
        transaction,
        test_result,
        repair_state,
    ):
        return self.repair_flow.run(
            instruction=instruction,
            transaction=transaction,
            test_result=test_result,
            repair_state=repair_state,
            attempt_fn=self._attempt_repair,
        )

    def _commit_transaction(
        self,
        approval_id,
        instruction,
        transaction,
        test_result,
        repair_state,
        repair=None,
    ):
        return self.transaction_flow.commit_transaction(
            approval_id=approval_id,
            instruction=instruction,
            transaction=transaction,
            test_result=test_result,
            repair_state=repair_state,
            repair=repair,
        )

    def _rollback_transaction(
        self,
        approval_id,
        transaction,
        repair_state,
        test_result=None,
        repair=None,
        status=TaskHistoryStatus.ROLLED_BACK.value,
        error=None,
    ):
        return self.transaction_flow.rollback_transaction(
            approval_id=approval_id,
            transaction=transaction,
            repair_state=repair_state,
            test_result=test_result,
            repair=repair,
            status=status,
            error=error,
        )

    # ------------------------------------------------------------------
    # APPROVAL / MAIN TRANSACTION FLOW
    # ------------------------------------------------------------------

    def approve(self, approval_id):
        # A primeira preparação permanece fora do lock para permitir
        # concorrência entre chamadas e preservar a semântica de
        # prepare_approval().
        self.supervisor.prepare_approval(approval_id)

        with self._approval_lock_for(approval_id):
            # Revalida a solicitação dentro da seção crítica.
            # A primeira thread poderá consumi-la; qualquer thread
            # concorrente que chegar depois receberá o erro correto:
            # "Solicitação não está pendente."
            return self._approve_locked(approval_id)

    def _approve_locked(self, approval_id):
        self.transaction_flow.tests = self.tests

        self.repair_flow.repair_engine = self.repair_engine
        self.repair_flow.repair_executor = self.repair_executor

        self.repair_executor.test_runner = self.tests

        return self.transaction_flow.approve_locked(
            approval_id=approval_id,
            commit_fn=self._commit_transaction,
            rollback_fn=self._rollback_transaction,
        )

    def reject(self, approval_id):
        result = self.supervisor.reject(
            approval_id
        )

        self._update_history_safe(
            approval_id,
            status=TaskHistoryStatus.REJECTED.value,
        )

        return result

    # ------------------------------------------------------------------
    # HISTORY API
    # ------------------------------------------------------------------

    def list_tasks(self):
        return self.history.list_all()

    def get_task(self, task_id):
        return self.history.get(task_id)

    def latest_task(self):
        return self.history.latest()
