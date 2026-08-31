from pathlib import Path
from core.security import SecurityPolicy
from core.supervisor import Supervisor
from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.test_runner import TestRunner
from core.executor.git_manager import GitManager
from core.engine.repair_engine import RepairEngine
from core.engine.repair_executor import RepairExecutor
from core.engine.repair_controller import RepairController
from core.engine.repair_cycle_state import RepairCycleState
from core.memory.task_history import TaskHistory
from core.schemas.models import TransactionStatus


class CommitTransactionError(RuntimeError):
    """Falha esperada durante o commit Git de uma transação."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result or {}


class DevAgentGateway:
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

    # ------------------------------------------------------------------
    # HISTORY
    # ------------------------------------------------------------------

    def _update_history_safe(
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
            "status": "pending",
            "plan": result,
        }

    # ------------------------------------------------------------------
    # EXECUTION DECISION
    # ------------------------------------------------------------------

    def execute_approved(self, approval_id):
        request = self.supervisor.get(approval_id)

        if request is None:
            raise KeyError("Tarefa não encontrada.")

        if request.get("status") != "approved":
            raise ValueError(
                "Tarefa não está aprovada."
            )

        return self.approve(approval_id)

    def _evaluate_execution(self, result):
        if not isinstance(result, dict):
            return "rollback"

        if not result.get("success"):
            return "repair"

        verification = result.get("verification")

        if (
            verification is not None
            and not verification.get("success")
        ):
            return "repair"

        tests = result.get("tests")

        if (
            isinstance(tests, dict)
            and not tests.get("success", False)
        ):
            return "repair"

        return "commit"

    # ------------------------------------------------------------------
    # REPAIR STATE
    # ------------------------------------------------------------------

    def _restore_repair_state(self, transaction):
        state = RepairCycleState.restore(transaction)

        state.max_attempts = self.MAX_REPAIR_ATTEMPTS

        self.repair_controller.max_attempts = (
            state.max_attempts
        )

        self.repair_controller.restore_state(
            transaction.transaction_id,
            state.attempts,
        )

        return state

    def _sync_repair_controller(
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
        """
        Executa exatamente uma tentativa de reparo.

        Importante:
        - a análise ocorre antes do consumo da tentativa;
        - somente uma correção aplicável consome uma tentativa;
        - repair_failed com resultado de testes NÃO é uma falha
          definitiva da transação: significa que a correção foi aplicada,
          mas os testes continuam falhando;
        - o Gateway decide posteriormente se deve tentar novamente
          ou fazer rollback.
        """

        self._sync_repair_controller(
            transaction,
            repair_state,
        )

        if not repair_state.can_continue():
            return {
                "status": "limit_reached",
                "success": False,
                "repair": {
                    "status": "limit_reached",
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

        # A análise não consome tentativa.
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
                "status": "rolled_back",
                "success": False,
                "repair": diagnosis,
            }

        if diagnosis.get("action") == "none":
            return {
                "status": "no_repair",
                "success": False,
                "repair": diagnosis,
            }

        if not repair_state.can_continue():
            return {
                "status": "limit_reached",
                "success": False,
                "repair": diagnosis,
            }

        # A correção é aplicável.
        # Uma tentativa é consumida exatamente uma vez,
        # antes da execução física da correção.
        repair_state.record(
            action=diagnosis.get(
                "action",
                "unknown",
            ),
            status="repairing",
        )
        repair_state.persist(transaction)

        # O RepairCycleState é a fonte autoritativa.
        # O controller recebe apenas uma cópia compatível.
        self._sync_repair_controller(
            transaction,
            repair_state,
        )

        repair_result = self.repair_executor.execute_repair(
            diagnosis,
            instruction,
            transaction,
        )

        if not isinstance(repair_result, dict):
            repair_result = {
                "success": False,
                "status": "failed",
                "error": (
                    "Resultado de reparo inválido."
                ),
            }

        repair_result["repair"] = diagnosis
        repair_result["transaction_id"] = (
            transaction.transaction_id
        )
        repair_result["repair_attempts"] = (
            repair_state.attempts
        )

        # Falha física ao aplicar a correção.
        # Não existe novo teste confiável para alimentar o ciclo.
        if repair_result.get("status") == "failed":
            error = repair_result.get(
                "error",
                "",
            )

            repair_state.mark_failed(
                error=error,
            )

            repair_state.persist(transaction)

            return repair_result

        # A correção foi aplicada e o RepairExecutor executou
        # os testes. O resultado desses testes alimentará a
        # próxima iteração do ciclo.
        test_result = repair_result.get("tests")

        if not isinstance(test_result, dict):
            repair_state.mark_failed(
                error="Resultado de testes inválido.",
            )

            repair_state.persist(transaction)

            repair_result["success"] = False
            repair_result["status"] = "repair_failed"
            repair_result["tests"] = {
                "success": False,
                "status": "invalid_test_result",
                "stderr": (
                    "Resultado de testes inválido."
                ),
                "stdout": "",
            }

            return repair_result

        if test_result.get("success"):
            repair_state.mark_verified()
            repair_state.persist(transaction)

            repair_result["success"] = True
            repair_result["status"] = "repair_verified"

            return repair_result

        # A correção foi aplicada, mas ainda falhou.
        # Isso NÃO encerra o ciclo.
        repair_state.mark_repair_failed(
            error=test_result.get(
                "stderr",
                "",
            ),
        )

        repair_state.persist(transaction)

        repair_result["success"] = False
        repair_result["status"] = "repair_failed"

        return repair_result

    # ------------------------------------------------------------------
    # COMPLETE REPAIR CYCLE
    # ------------------------------------------------------------------

    def _run_repair_cycle(
        self,
        instruction,
        transaction,
        test_result,
        repair_state,
    ):
        """
        Executa o ciclo completo:

            teste inicial
                ↓
            análise
                ↓
            reparo #1
                ↓
            teste
                ↓
            reparo #2
                ↓
            teste
                ↓
            sucesso / rollback

        O método NÃO faz commit nem rollback físico.
        Ele apenas determina o resultado do ciclo.
        """

        while not test_result.get("success", False):

            self._sync_repair_controller(
                transaction,
                repair_state,
            )

            # O limite é verificado ANTES de uma nova análise.
            if not repair_state.can_continue():
                return {
                    "success": False,
                    "status": "rolled_back",
                    "tests": test_result,
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                    "repair": {
                        "action": "none",
                        "risk": "baixo",
                        "path": "",
                        "content": "",
                        "status": "limit_reached",
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

            repair_result = self._attempt_repair(
                instruction=instruction,
                transaction=transaction,
                test_result=test_result,
                repair_state=repair_state,
            )

            status = repair_result.get(
                "status",
                "repair_failed",
            )

            # ----------------------------------------------------------
            # REPARO APLICADO E TESTES PASSARAM
            # ----------------------------------------------------------

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
                        "status": "verified",
                        "tests": next_tests,
                        "repair": repair_result.get(
                            "repair"
                        ),
                        "repair_attempts": (
                            repair_state.attempts
                        ),
                    }

            # ----------------------------------------------------------
            # REPARO APLICADO, MAS TESTES CONTINUAM FALHANDO
            # ----------------------------------------------------------

            if status == "repair_failed":
                next_tests = repair_result.get(
                    "tests"
                )

                if isinstance(next_tests, dict):
                    test_result = next_tests

                    # Ainda existem tentativas?
                    # Então volta ao topo para uma NOVA análise.
                    if repair_state.can_continue():
                        continue

                    # Limite atingido após a última tentativa.
                    repair = repair_result.get("repair")

                    if isinstance(repair, dict):
                        repair = dict(repair)
                        repair["status"] = "limit_reached"

                    return {
                        "success": False,
                        "status": "rolled_back",
                        "tests": test_result,
                        "repair": repair,
                        "repair_attempts": (
                            repair_state.attempts
                        ),
                    }

                # repair_failed sem testes confiáveis:
                # não há base para outra tentativa.
                return {
                    "success": False,
                    "status": "rolled_back",
                    "tests": test_result,
                    "repair": repair_result.get(
                        "repair"
                    ),
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                }

            # ----------------------------------------------------------
            # FALHA FÍSICA AO APLICAR REPARO
            # ----------------------------------------------------------

            if status == "failed":
                return {
                    "success": False,
                    "status": "rolled_back",
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

            # ----------------------------------------------------------
            # SEM REPARO / ALTO RISCO / LIMITE
            # ----------------------------------------------------------

            if status in {
                "no_repair",
                "limit_reached",
                "rolled_back",
            }:
                return {
                    "success": False,
                    "status": "rolled_back",
                    "tests": test_result,
                    "repair": repair_result.get(
                        "repair"
                    ),
                    "repair_attempts": (
                        repair_state.attempts
                    ),
                }

            # ----------------------------------------------------------
            # ESTADO DESCONHECIDO
            # ----------------------------------------------------------

            return {
                "success": False,
                "status": "rolled_back",
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
            "status": "verified",
            "tests": test_result,
            "repair": None,
            "repair_attempts": repair_state.attempts,
        }

    # ------------------------------------------------------------------
    # COMMIT
    # ------------------------------------------------------------------

    def _commit_transaction(
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

        if git_result.get("status") != "committed":
            raise CommitTransactionError(
                "Commit Git não foi concluído: "
                f"{git_result.get('status', 'desconhecido')}"
                + (
                    f" — {git_result.get('message')}"
                    if git_result.get("message")
                    else ""
                ),
                result=git_result,
            )

        transaction.status = (
            TransactionStatus.COMMITTED
        )

        repair_state.mark_committed()
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

        self._update_history_safe(
            approval_id,
            status="committed",
            transaction_id=transaction.transaction_id,
            extra=extra,
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
            **(
                {"repair": repair}
                if repair is not None
                else {}
            ),
        }

    # ------------------------------------------------------------------
    # ROLLBACK
    # ------------------------------------------------------------------

    def _rollback_transaction(
        self,
        approval_id,
        transaction,
        repair_state,
        test_result=None,
        repair=None,
        status="rolled_back",
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
            "failed"
            if rollback_error is not None
            else status
        )

        self._update_history_safe(
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

    # ------------------------------------------------------------------
    # APPROVAL / MAIN TRANSACTION FLOW
    # ------------------------------------------------------------------

    def approve(self, approval_id):
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

        transaction = self.agent.build_transaction_from_approved_plan(
            request["plan"]
        )

        transaction = self.transactions.begin(
            transaction
        )

        self.supervisor.approve(
            approval_id
        )

        repair_state = self._restore_repair_state(
            transaction
        )

        repair_state.persist(transaction)

        self.repair_controller.start(
            transaction.transaction_id
        )

        self._update_history_safe(
            approval_id,
            status="executing",
            transaction_id=transaction.transaction_id,
        )

        try:
            # ----------------------------------------------------------
            # PREPARAÇÃO TRANSACIONAL
            # ----------------------------------------------------------

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

            # ----------------------------------------------------------
            # EXECUÇÃO INICIAL
            # ----------------------------------------------------------

            self.executor.execute(
                transaction
            )

            repair_state.mark_testing()
            repair_state.persist(transaction)

            # ----------------------------------------------------------
            # TESTE INICIAL
            # ----------------------------------------------------------

            self._update_history_safe(
                approval_id,
                status="testing",
                transaction_id=transaction.transaction_id,
            )

            test_result = self.tests.run(
                [
                    change.path
                    for change in transaction.changes
                ]
            )

            # ----------------------------------------------------------
            # SUCESSO INICIAL
            # ----------------------------------------------------------

            if test_result.get("success"):
                return self._commit_transaction(
                    approval_id=approval_id,
                    instruction=instruction,
                    transaction=transaction,
                    test_result=test_result,
                    repair_state=repair_state,
                )

            # ----------------------------------------------------------
            # REPARO
            # ----------------------------------------------------------

            repair_cycle = self._run_repair_cycle(
                instruction=instruction,
                transaction=transaction,
                test_result=test_result,
                repair_state=repair_state,
            )

            # ----------------------------------------------------------
            # REPARO CONSEGUIU VALIDAR
            # ----------------------------------------------------------

            if repair_cycle.get("success"):
                return self._commit_transaction(
                    approval_id=approval_id,
                    instruction=instruction,
                    transaction=transaction,
                    test_result=repair_cycle["tests"],
                    repair_state=repair_state,
                    repair=repair_cycle.get("repair"),
                )

            # ----------------------------------------------------------
            # FALHA DEFINITIVA → ROLLBACK
            # ----------------------------------------------------------

            return self._rollback_transaction(
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
                status="rolled_back",
                error=repair_cycle.get(
                    "error"
                ),
            )

        except CommitTransactionError as error:
            # ----------------------------------------------------------
            # FALHA DE COMMIT → ROLLBACK CONTROLADO
            # ----------------------------------------------------------

            rollback_result = self._rollback_transaction(
                approval_id=approval_id,
                transaction=transaction,
                repair_state=repair_state,
                error=str(error),
                status="rolled_back",
            )

            # Se o rollback também falhou, a falha de rollback deve
            # prevalecer como erro operacional não recuperado.
            if rollback_result.get("rollback_error"):
                raise RuntimeError(
                    rollback_result["rollback_error"]
                ) from error

            # Preserva o contrato do Gateway: falha de commit continua
            # sendo uma exceção para chamadas diretas.
            # A camada HTTP decide como serializá-la.
            error.result = {
                **(
                    error.result
                    if isinstance(error.result, dict)
                    else {}
                ),
                "rollback": rollback_result,
            }

            raise

        except Exception as error:
            # ----------------------------------------------------------
            # EXCEÇÃO NÃO TRATADA → ROLLBACK
            # ----------------------------------------------------------

            result = self._rollback_transaction(
                approval_id=approval_id,
                transaction=transaction,
                repair_state=repair_state,
                error=error,
                status="failed",
            )

            # Se o rollback também falhou, não retornar como sucesso HTTP.
            # A falha operacional de rollback deve ser propagada para a
            # camada HTTP, preservando a exceção original como causa.
            if result.get("rollback_error"):
                raise RuntimeError(
                    result["rollback_error"]
                ) from error

            return result

    # ------------------------------------------------------------------
    # REJECT
    # ------------------------------------------------------------------

    def reject(self, approval_id):
        result = self.supervisor.reject(
            approval_id
        )

        self.history.update(
            approval_id,
            status="rejected",
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
