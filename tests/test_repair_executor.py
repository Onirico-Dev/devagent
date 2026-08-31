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


def test_repair_executor_rejects_high_risk_content(tmp_path):
    repair_executor, transactions = (
        TestRepairExecutor()._make_executor(tmp_path)
    )

    from core.schemas.models import Transaction

    transaction = Transaction(
        transaction_id="high-risk-repair",
        changes=[],
    )

    repair = {
        "action": "create",
        "path": "danger.py",
        "content": "import os\nos.system('rm -rf /')",
        "correction": "correção perigosa",
    }

    import pytest

    with pytest.raises(PermissionError, match="alto risco"):
        repair_executor.build_change(repair)


def test_repair_executor_rejects_high_declared_risk(tmp_path):
    repair_executor, _ = (
        TestRepairExecutor()._make_executor(tmp_path)
    )

    repair = {
        "action": "create",
        "path": "danger.py",
        "content": "print('safe')",
        "correction": "teste",
        "risk": "alto",
    }

    import pytest

    with pytest.raises(
        PermissionError,
        match="política de risco",
    ):
        repair_executor.build_change(repair)


def test_repair_executor_rejects_invalid_declared_risk(tmp_path):
    repair_executor, _ = (
        TestRepairExecutor()._make_executor(tmp_path)
    )

    repair = {
        "action": "create",
        "path": "danger.py",
        "content": "print('safe')",
        "correction": "teste",
        "risk": "critico",
    }

    import pytest

    with pytest.raises(
        PermissionError,
        match="política de risco",
    ):
        repair_executor.build_change(repair)


def test_repair_executor_accepts_low_risk_repair(tmp_path):
    repair_executor, _ = (
        TestRepairExecutor()._make_executor(tmp_path)
    )

    repair = {
        "action": "create",
        "path": "safe.py",
        "content": "print('safe')",
        "correction": "teste",
        "risk": "baixo",
    }

    change = repair_executor.build_change(repair)

    assert change.path == "safe.py"


def test_repair_executor_uses_security_policy_for_content(
    tmp_path,
):
    from core.engine.repair_executor import RepairExecutor
    from core.security import SecurityPolicy
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    class FakeExecutor:
        def execute_change(self, change):
            raise AssertionError(
                "Conteúdo perigoso não deveria chegar ao executor."
            )

    class FakeTests:
        def run(self, paths):
            return {"success": True}

    security = SecurityPolicy(tmp_path)
    transactions = TransactionManager(tmp_path)

    repair_executor = RepairExecutor(
        security=security,
        transaction_manager=transactions,
        executor=FakeExecutor(),
        test_runner=FakeTests(),
    )

    transaction = Transaction(
        transaction_id="security-policy-integration",
        changes=[],
        metadata={},
    )

    transaction = transactions.begin(transaction)

    repair = {
        "action": "create",
        "path": "danger.py",
        "content": "import subprocess\nsubprocess.run(['danger'])",
        "risk": "baixo",
        "correction": "teste",
    }

    import pytest

    with pytest.raises(
        PermissionError,
        match="alto risco",
    ):
        repair_executor.execute_repair(
            repair,
            "Crie danger.py",
            transaction,
        )


def test_repair_executor_rejects_symlink_path(tmp_path):
    import pytest
    from core.engine.repair_executor import RepairExecutor
    from core.security import SecurityPolicy
    from core.executor.transaction_manager import TransactionManager

    root = tmp_path / "project"
    root.mkdir()

    target = root / "real.py"
    target.write_text("print('real')\n", encoding="utf-8")

    link = root / "link.py"
    link.symlink_to(target)

    class FakeExecutor:
        def execute_change(self, change):
            raise AssertionError("Symlink não deveria ser executado.")

    class FakeTests:
        def run(self, paths):
            return {"success": True}

    transactions = TransactionManager(root)

    executor = RepairExecutor(
        security=SecurityPolicy(root),
        transaction_manager=transactions,
        executor=FakeExecutor(),
        test_runner=FakeTests(),
    )

    transaction = transactions.begin(
        __import__("core.schemas.models", fromlist=["Transaction"]).Transaction(
            transaction_id="symlink-test",
            changes=[],
            metadata={},
        )
    )

    with pytest.raises(PermissionError):
        executor.execute_repair(
            {
                "action": "modify",
                "path": "link.py",
                "content": "print('danger')\n",
                "risk": "baixo",
                "correction": "teste",
            },
            "Corrija link.py",
            transaction,
        )

def test_repair_executor_handles_executor_exception(tmp_path):
    from core.engine.repair_executor import RepairExecutor
    from core.executor.transaction_manager import TransactionManager
    from core.security import SecurityPolicy
    from core.schemas.models import Transaction, TransactionStatus

    class FailingExecutor:
        def execute_change(self, change):
            raise RuntimeError("EXECUTOR_FAILURE_TEST")

    class FakeTests:
        def run(self, paths):
            raise AssertionError(
                "Os testes não deveriam executar após falha do executor."
            )

    root = tmp_path / "project"
    root.mkdir()

    target = root / "app.py"
    target.write_text(
        "print('old')\n",
        encoding="utf-8",
    )

    transactions = TransactionManager(root)

    repair_executor = RepairExecutor(
        security=SecurityPolicy(root),
        transaction_manager=transactions,
        executor=FailingExecutor(),
        test_runner=FakeTests(),
    )

    transaction = Transaction(
        transaction_id="repair-executor-exception",
        changes=[],
        metadata={},
    )

    transaction = transactions.begin(transaction)

    result = repair_executor.execute_repair(
        {
            "action": "modify",
            "path": "app.py",
            "content": "print('new')\n",
            "diagnosis": "Teste de exceção.",
            "correction": "Simular falha do executor.",
            "risk": "baixo",
        },
        "Corrija app.py",
        transaction,
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["transaction_id"] == transaction.transaction_id
    assert result["error"] == "EXECUTOR_FAILURE_TEST"
    assert result["instruction"] == "Corrija app.py"

    assert transaction.status == TransactionStatus.FAILED

    # O RepairExecutor não faz rollback.
    # O Gateway/TransactionManager continua responsável por isso.
    assert target.read_text(encoding="utf-8") == "print('old')\n"
