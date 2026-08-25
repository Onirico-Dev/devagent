from core.engine.repair_executor import RepairExecutor
from core.executor.safe_executor import SafeExecutor
from core.executor.test_runner import TestRunner as ProjectTestRunner
from core.executor.transaction_manager import TransactionManager
from core.security import SecurityPolicy
from core.schemas.models import Transaction


class TestRepairExecutor:
    def _make_executor(self, root):
        security = SecurityPolicy(root)
        transactions = TransactionManager(root)
        executor = SafeExecutor(root)
        tests = ProjectTestRunner(root)

        return (
            RepairExecutor(
                security=security,
                transaction_manager=transactions,
                executor=executor,
                test_runner=tests,
            ),
            transactions,
        )

    def test_repair_modifies_existing_file_inside_transaction(
        self,
        tmp_path,
    ):
        root = tmp_path / "project"
        root.mkdir()

        target = root / "app.py"
        target.write_text(
            "print('old')\n",
            encoding="utf-8",
        )

        repair_executor, transactions = self._make_executor(root)

        transaction = Transaction(
            transaction_id="repair-test",
            changes=[],
            metadata={},
        )

        transaction = transactions.begin(transaction)

        result = repair_executor.execute_repair(
            {
                "action": "modify",
                "path": "app.py",
                "content": "print('new')\n",
                "diagnosis": "Conteúdo incorreto.",
                "correction": "Substituir conteúdo.",
            },
            "Corrija app.py",
            transaction,
        )

        assert result["success"] is True
        assert target.read_text(encoding="utf-8") == "print('new')\n"

        assert transaction.metadata["created"] == []
        assert len(transaction.metadata["repairs"]) == 1
        assert transaction.metadata["repairs"][0]["path"] == "app.py"

    def test_failed_repair_does_not_rollback_transaction(
        self,
        tmp_path,
    ):
        root = tmp_path / "project"
        root.mkdir()

        target = root / "broken.py"
        target.write_text(
            "print('old')\n",
            encoding="utf-8",
        )

        repair_executor, transactions = self._make_executor(root)

        transaction = Transaction(
            transaction_id="repair-failure-test",
            changes=[],
            metadata={},
        )

        transaction = transactions.begin(transaction)

        result = repair_executor.execute_repair(
            {
                "action": "modify",
                "path": "broken.py",
                "content": "def broken(:\n",
                "diagnosis": "Erro de sintaxe.",
                "correction": "Tentativa de correção.",
            },
            "Corrija broken.py",
            transaction,
        )

        assert result["success"] is False

        # O RepairExecutor não é responsável pelo rollback.
        # A alteração continua presente até o Gateway/TransactionManager
        # decidir fazer rollback.
        assert target.read_text(encoding="utf-8") == "def broken(:\n"

        assert len(transaction.metadata["repairs"]) == 1
        assert transaction.status.value == "testing"

    def test_repair_create_adds_new_change_to_transaction(
        self,
        tmp_path,
    ):
        root = tmp_path / "project"
        root.mkdir()

        repair_executor, transactions = self._make_executor(root)

        transaction = Transaction(
            transaction_id="repair-create-test",
            changes=[],
            metadata={},
        )

        transaction = transactions.begin(transaction)

        result = repair_executor.execute_repair(
            {
                "action": "create",
                "path": "new_file.py",
                "content": "print('created')\n",
                "diagnosis": "Arquivo ausente.",
                "correction": "Criar arquivo.",
            },
            "Crie new_file.py",
            transaction,
        )

        target = root / "new_file.py"

        assert result["success"] is True
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "print('created')\n"

        assert "new_file.py" in transaction.metadata["created"]
        assert len(transaction.changes) == 1
        assert transaction.changes[0].path == "new_file.py"
