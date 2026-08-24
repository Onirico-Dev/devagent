from core.schemas.models import (
    Change,
    ChangeType,
    Transaction,
    TransactionStatus,
)


class RepairExecutor:

    def __init__(
        self,
        security,
        transaction_manager,
        executor,
        test_runner,
    ):
        self.security = security
        self.transaction_manager = transaction_manager
        self.executor = executor
        self.test_runner = test_runner

    def build_change(self, repair):

        if not repair:
            raise ValueError(
                "Proposta de reparo vazia."
            )

        action = repair.get("action")

        if action == "none":
            raise ValueError(
                "RepairEngine não propôs uma correção."
            )

        if action not in {
            "create",
            "modify",
        }:
            raise ValueError(
                f"Ação de reparo inválida: {action}"
            )

        path = repair.get("path", "").strip()

        if not path:
            raise ValueError(
                "Reparo não possui caminho."
            )

        content = repair.get(
            "content",
            "",
        )

        if not isinstance(content, str):
            raise ValueError(
                "Conteúdo do reparo deve ser texto."
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

    def execute_repair(
        self,
        repair,
        instruction,
    ):

        change = self.build_change(
            repair
        )

        transaction = Transaction(
            transaction_id="repair",
            changes=[change],
            metadata={
                "repair": True,
                "diagnosis": repair.get(
                    "diagnosis",
                    "",
                ),
                "risk": repair.get(
                    "risk",
                    "alto",
                ),
            },
        )

        transaction = (
            self.transaction_manager.begin(
                transaction
            )
        )

        try:

            if (
                change.change_type
                == ChangeType.MODIFY
            ):

                self.transaction_manager.backup_file(
                    transaction,
                    change.path,
                )

            elif (
                change.change_type
                == ChangeType.CREATE
            ):

                self.transaction_manager.register_created(
                    transaction,
                    change.path,
                )

            transaction.status = (
                TransactionStatus.EXECUTING
            )

            transaction = (
                self.executor.execute(
                    transaction
                )
            )

            transaction.status = (
                TransactionStatus.TESTING
            )

            test_result = (
                self.test_runner.run(
                    [change.path]
                )
            )

            if not test_result["success"]:

                transaction = (
                    self.transaction_manager.rollback(
                        transaction
                    )
                )

                return {
                    "success": False,
                    "status": (
                        transaction.status.value
                    ),
                    "transaction_id": (
                        transaction.transaction_id
                    ),
                    "tests": test_result,
                    "instruction": instruction,
                }

            transaction.status = (
                TransactionStatus.COMMITTED
            )

            return {
                "success": True,
                "status": (
                    transaction.status.value
                ),
                "transaction_id": (
                    transaction.transaction_id
                ),
                "tests": test_result,
                "instruction": instruction,
            }

        except Exception as exc:

            try:

                transaction = (
                    self.transaction_manager.rollback(
                        transaction
                    )
                )

            except Exception as rollback_error:

                transaction.status = (
                    TransactionStatus.FAILED
                )

                return {
                    "success": False,
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
                "success": False,
                "status": (
                    transaction.status.value
                ),
                "transaction_id": (
                    transaction.transaction_id
                ),
                "error": str(exc),
            }
