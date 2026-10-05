import fcntl
import inspect
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from core.security import SecurityPolicy
from core.supervisor import ApprovalStatus, Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager, GitStatus
from core.engine.post_execution import PostExecutionVerifier
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import RepairExecutor, RepairExecutorStatus
from core.engine.repair_controller import RepairController
from core.engine.repair_cycle_state import RepairCycleState, RepairCycleStatus
from core.engine.repair_flow import RepairFlow
from core.engine.transaction_flow import TransactionFlow
from core.memory.task_history import TaskHistory, TaskHistoryStatus
from core.memory.recovery_reconciler import RecoveryReconciler
from core.approval.approval_coordinator import ApprovalCoordinator
from core.schemas.models import TransactionStatus
from core.task.task_creator import TaskCreator


class CommitTransactionError(RuntimeError):
    """Falha esperada durante o commit Git de uma transação."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result or {}


class DevAgentGateway:
    _task_creation_guard = RLock()

    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self, agent, root="."):
        self.agent = agent
        self.root = root
        self.approval_coordinator = ApprovalCoordinator(root)
        self._task_creation_lock_path = (
            Path(root).resolve()
            / "transactions"
            / "task_creation.lock"
        )

        self.supervisor = Supervisor(
            storage_path=(
                Path(root).resolve()
                / "transactions"
                / "approvals.json"
            )
        )
        self.security = SecurityPolicy(root)
        self.executor = SafeExecutor(root)
        self.post_execution_verifier = PostExecutionVerifier(root)
        self.transactions = TransactionManager(root)
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
            post_execution_verifier=self.post_execution_verifier,
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
        self.task_creator = TaskCreator(
            self.security,
            self.history,
            self.supervisor,
        )
        self.recovery_reconciler = RecoveryReconciler(self.history)

        recovery = self.transactions.recover_incomplete_transactions

        if "recovery_guard" in inspect.signature(
            recovery
        ).parameters:
            recovered_transactions = recovery(
                commit_detector=self.git.find_transaction_commit,
                recovery_guard=self._recovery_guard,
            )
        else:
            recovered_transactions = recovery(
                commit_detector=self.git.find_transaction_commit,
            )

        terminal_transactions = self.transactions.list_terminal_transactions()

        self.recovery_reconciler.reconcile(
            recovered_transactions + terminal_transactions
        )

        self.repair_flow = RepairFlow(
            repair_engine=self.repair_engine,
            repair_executor=self.repair_executor,
            repair_controller=self.repair_controller,
            max_attempts=self.MAX_REPAIR_ATTEMPTS,
            root=self.root,
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
            history_update_fn=self._history_update,
            restore_repair_state_fn=lambda transaction: self._restore_repair_state(transaction),
            repair_cycle_fn=lambda **kwargs: self._run_repair_cycle(**kwargs),
            commit_error_type=CommitTransactionError,
            post_execution_verifier=self.post_execution_verifier,
        )

    @contextmanager
    def _recovery_guard(self, transaction):
        approval_id = transaction.metadata.get("approval_id")

        if not approval_id:
            yield
            return

        thread_lock, process_lock = self.approval_coordinator.acquire(
            approval_id
        )
        try:
            yield
        finally:
            self.approval_coordinator.release(
                thread_lock,
                process_lock,
            )

    def _reconcile_recovered_transactions(self, transactions):
        return self.recovery_reconciler.reconcile(transactions)

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

    def list_pending(self):
        return self.history.list_pending()

    # ------------------------------------------------------------------
    # TASK CREATION
    # ------------------------------------------------------------------

    def create_task(self, instruction, context=None):
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("Instrução inválida.")

        if context is None:
            context = {}

        if not isinstance(context, dict):
            raise ValueError("Contexto da tarefa inválido.")

        if context:
            result = self.agent.process(
                instruction,
                feedback_context=context,
            )
        else:
            result = self.agent.process(instruction)
        self.task_creator.validate_plan(result)

        with self._task_creation_guard:
            with self._task_creation_lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    return self.task_creator.create_or_reuse(
                        instruction,
                        result,
                    )
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

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

        thread_lock, process_lock = self.approval_coordinator.acquire(
            approval_id
        )
        try:
            # Revalida a solicitação dentro da seção crítica.
            # A primeira chamada poderá consumi-la; qualquer chamada
            # concorrente que chegar depois receberá o erro correto:
            # "Solicitação não está pendente."
            return self._approve_locked(approval_id)
        finally:
            self.approval_coordinator.release(thread_lock, process_lock)

    def _sync_flow_dependencies(self):
        self.transaction_flow.tests = self.tests
        self.repair_flow.repair_engine = self.repair_engine
        self.repair_flow.repair_executor = self.repair_executor
        self.repair_executor.test_runner = self.tests

    def _approve_locked(self, approval_id):
        self._sync_flow_dependencies()
        return self.transaction_flow.approve_locked(
            approval_id=approval_id,
            commit_fn=self._commit_transaction,
            rollback_fn=self._rollback_transaction,
        )

    def reject(self, approval_id):
        thread_lock, process_lock = self.approval_coordinator.acquire(
            approval_id
        )
        try:
            result = self.supervisor.reject(
                approval_id
            )

            self._history_update(
                approval_id,
                status=TaskHistoryStatus.REJECTED.value,
            )

            return result
        finally:
            self.approval_coordinator.release(thread_lock, process_lock)

    # ------------------------------------------------------------------
    # HISTORY API
    # ------------------------------------------------------------------

    def list_tasks(self):
        return self.history.list_all()

    def get_task(self, task_id):
        return self.history.get(task_id)

    def latest_task(self):
        return self.history.latest()
