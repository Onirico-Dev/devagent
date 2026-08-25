import pytest

from core.security import SecurityPolicy


def test_safe_content_is_allowed(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.validate_content(
        "def hello():\n    return 'world'\n"
    ) is True


def test_rm_rf_is_high_risk(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(
        "rm -rf /tmp/test"
    ) == "alto"


def test_subprocess_is_high_risk(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(
        "import subprocess"
    ) == "alto"


def test_os_system_is_high_risk(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(
        "os.system('command')"
    ) == "alto"


def test_high_risk_content_is_rejected(tmp_path):
    policy = SecurityPolicy(tmp_path)

    with pytest.raises(PermissionError, match="alto risco"):
        policy.validate_content(
            "import os\nos.system('danger')"
        )


def test_non_string_content_is_high_risk(tmp_path):
    policy = SecurityPolicy(tmp_path)

    assert policy.assess_content_risk(None) == "alto"


def test_repair_executor_rejects_dangerous_content(tmp_path):
    from core.engine.repair_executor import RepairExecutor
    from core.security import SecurityPolicy
    from core.executor.transaction_manager import TransactionManager
    from core.executor.safe_executor import SafeExecutor
    from core.executor.test_runner import TestRunner

    class DummyExecutor:
        def execute_change(self, change):
            pass

    security = SecurityPolicy(tmp_path)
    transactions = TransactionManager(tmp_path)

    repair_executor = RepairExecutor(
        security=security,
        transaction_manager=transactions,
        executor=DummyExecutor(),
        test_runner=TestRunner(tmp_path),
    )

    repair = {
        "action": "create",
        "path": "danger.py",
        "content": "import subprocess\nsubprocess.run(['rm', '-rf', '/'])",
        "correction": "teste",
        "risk": "baixo",
    }

    from core.schemas.models import Transaction
    transaction = transactions.begin(
        Transaction(
            transaction_id="security-integration-test",
            changes=[],
            metadata={},
        )
    )

    import pytest

    with pytest.raises(PermissionError, match="alto risco"):
        repair_executor.execute_repair(
            repair,
            "teste de segurança",
            transaction,
        )
