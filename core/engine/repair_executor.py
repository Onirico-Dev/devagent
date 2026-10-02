from enum import Enum
from core.schemas.models import (
    Change,
    ChangeType,
    TestResult,
)


class RepairExecutorStatus(str, Enum):
    FAILED = "failed"
    REPAIR_APPLIED = "repair_applied"
    REPAIR_VERIFIED = "repair_verified"
    REPAIR_FAILED = "repair_failed"
    INVALID_TEST_RESULT = "invalid_test_result"


class RepairExecutor:
    def __init__(
        self,
        security,
        transaction_manager,
        executor,
        test_runner=None,
        post_execution_verifier=None,
    ):
        self.security = security
        self.transaction_manager = transaction_manager
        self.executor = executor
        self.test_runner = test_runner
        self.post_execution_verifier = post_execution_verifier

    def _validate_risk(self, repair):
        declared_risk = repair.get("risk", "baixo")

        if declared_risk not in {"baixo", "medio", "alto"}:
            raise PermissionError(
                "Reparo não autorizado pela política de risco: "
                f"risco inválido ({declared_risk})."
            )

        if declared_risk == "alto":
            raise PermissionError(
                "Reparo de alto risco não autorizado "
                "pela política de risco."
            )

        content = repair.get("content", "")

        if not isinstance(content, str):
            raise PermissionError(
                "Conteúdo do reparo deve ser texto."
            )

        self.security.validate_content(content)

        assessed_risk = self.security.assess_content_risk(content)

        if assessed_risk == "alto":
            raise PermissionError(
                "Reparo de alto risco não autorizado "
                "pela política de risco."
            )

        if declared_risk == "medio" and assessed_risk != "baixo":
            raise PermissionError(
                "Reparo não autorizado pela política de risco."
            )

        return declared_risk

    def build_change(self, repair):
        if not repair:
            raise ValueError("Proposta de reparo vazia.")

        action = repair.get("action")

        if action == "none":
            raise ValueError(
                "RepairEngine não propôs uma correção."
            )

        if action not in {"create", "modify"}:
            raise ValueError(
                f"Ação de reparo inválida: {action}"
            )

        path = repair.get("path", "").strip()

        if not path:
            raise ValueError(
                "Reparo não possui caminho."
            )

        content = repair.get("content", "")

        if not isinstance(content, str):
            raise ValueError(
                "Conteúdo do reparo deve ser texto."
            )

        self._validate_risk(repair)

        target = self.security.root / path

        if target.exists() and not target.is_file():
            raise PermissionError(
                f"Caminho não é um arquivo: {path}"
            )

        self.security.validate_path(path)

        change_type = (
            ChangeType.CREATE
            if action == "create"
            else ChangeType.MODIFY
        )

        return Change(
            change_type=change_type,
            path=path,
            content=content,
            reason=repair.get(
                "correction",
                "Correção automática",
            ),
        )

    def _prepare_repair_change(
        self,
        repair,
        instruction,
        transaction,
    ):
        change = self.build_change(repair)
        self.security.validate_path(change.path)

        target = self.security.root / change.path

        if target.exists() and target.is_symlink():
            raise PermissionError(
                "Reparo recusado em caminho simbólico: "
                f"{change.path}"
            )

        existing_paths = {
            existing.path
            for existing in transaction.changes
        }

        if (
            change.path in existing_paths
            and change.change_type == ChangeType.CREATE
        ):
            raise PermissionError(
                "Arquivo já está registrado na transação: "
                f"{change.path}"
            )

        if change.path not in existing_paths:
            if change.change_type == ChangeType.MODIFY:
                self.transaction_manager.backup_file(
                    transaction,
                    change.path,
                )
            elif change.change_type == ChangeType.CREATE:
                self.transaction_manager.register_created(
                    transaction,
                    change.path,
                )

        transaction.changes.append(change)

        transaction.metadata.setdefault(
            "repairs",
            [],
        ).append(
            {
                "path": change.path,
                "action": change.change_type.value,
                "instruction": instruction,
                "diagnosis": repair.get("diagnosis", ""),
                "correction": repair.get("correction", ""),
                "risk": repair.get("risk", "baixo"),
            }
        )

        self.transaction_manager.persist_manifest(transaction)

        return change

    def _build_no_test_runner_result(self, transaction):
        return {
            "success": True,
            "status": RepairExecutorStatus.REPAIR_APPLIED.value,
            "transaction_id": transaction.transaction_id,
            "instruction": "",
            "repair": None,
        }

    def _combine_repair_test_results(
        self,
        test_result,
        semantic_result,
    ):
        return TestResult.combine(
            test_result,
            semantic_result,
        )

    def _run_declared_repair_tests(
        self,
        test_result,
        transaction,
    ):
        if not (
            isinstance(test_result, dict)
            and test_result.get("success")
        ):
            return test_result

        declared_tests = transaction.metadata.get(
            "tests",
            [],
        )

        if not declared_tests:
            return test_result

        semantic_result = self.test_runner.run_tests(
            declared_tests,
        )

        return self._combine_repair_test_results(
            test_result,
            semantic_result,
        )

    def _normalize_repair_test_result(self, test_result):
        try:
            return TestResult.from_dict(
                test_result,
            ).to_dict()
        except (TypeError, ValueError):
            return {
                "success": False,
                "status": RepairExecutorStatus.INVALID_TEST_RESULT.value,
                "stderr": "Resultado de testes inválido.",
                "stdout": "",
            }

    def _run_repair_tests(
        self,
        change,
        transaction,
    ):

        if self.test_runner is None:
            return self._build_no_test_runner_result(
                transaction,
            )

        test_result = self.test_runner.run(
            [change.path]
        )

        test_result = self._run_declared_repair_tests(
            test_result,
            transaction,
        )

        return self._normalize_repair_test_result(
            test_result,
        )

    def execute_repair(
        self,
        repair,
        instruction,
        transaction,
    ):
        change = self._prepare_repair_change(
            repair,
            instruction,
            transaction,
        )

        try:
            created = transaction.metadata.get("created", [])
            created_paths = {str(path) for path in created}
            is_created_path = str(change.path) in created_paths

            if (
                change.change_type.value == "modify"
                and is_created_path
            ):
                self.transaction_manager.validate_created_identity(
                    transaction,
                    change.path,
                )

            self.executor.execute_change(change)

            if (
                change.change_type.value == "create"
                or (
                    change.change_type.value == "modify"
                    and is_created_path
                )
            ):
                self.transaction_manager.record_created_identity(
                    transaction,
                    change.path,
                )

        except Exception as exc:
            return {
                "success": False,
                "status": RepairExecutorStatus.FAILED.value,
                "transaction_id": transaction.transaction_id,
                "error": str(exc),
                "instruction": instruction,
                "repair": repair,
            }

        verification = None
        if self.post_execution_verifier is not None:
            verification = self.post_execution_verifier.verify_change(change)
            if not verification.get("success"):
                return {
                    "success": False,
                    "status": RepairExecutorStatus.REPAIR_FAILED.value,
                    "transaction_id": transaction.transaction_id,
                    "instruction": instruction,
                    "repair": repair,
                    "verification": verification,
                }

        try:
            test_result = self._run_repair_tests(
                change,
                transaction,
            )
        except Exception as exc:
            return {
                "success": False,
                "status": RepairExecutorStatus.FAILED.value,
                "transaction_id": transaction.transaction_id,
                "error": str(exc),
                "instruction": instruction,
                "repair": repair,
            }

        if self.test_runner is None:
            return {
                "success": True,
                "status": RepairExecutorStatus.REPAIR_APPLIED.value,
                "transaction_id": transaction.transaction_id,
                "instruction": instruction,
                "repair": repair,
            }

        test_success = test_result.get(
            "success",
            False,
        )

        return {
            "success": test_success,
            "status": (
                RepairExecutorStatus.REPAIR_VERIFIED.value
                if test_success
                else RepairExecutorStatus.REPAIR_FAILED.value
            ),
            "transaction_id": transaction.transaction_id,
            "instruction": instruction,
            "repair": repair,
            "tests": test_result,
            "verification": verification,
        }
