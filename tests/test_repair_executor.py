from pathlib import Path
from types import SimpleNamespace

import pytest

from core.engine.repair_executor import RepairExecutor
from core.schemas.models import ChangeType, TransactionStatus
from core.security import SecurityPolicy
from core.executor.transaction_manager import TransactionManager


class FakeExecutor:
    def __init__(self, error=None):
        self.error = error
        self.executed = []

    def execute_change(self, change):
        if self.error is not None:
            raise self.error
        self.executed.append(change)


class FakeTestRunner:
    def __init__(self, result):
        self.result = result
        self.received = []

    def run(self, paths):
        self.received.append(paths)
        return self.result


def make_transaction(tmp_path, changes=None):
    backup = tmp_path / "transactions" / "tx-test"
    backup.mkdir(parents=True)

    return SimpleNamespace(
        transaction_id="tx-test",
        changes=list(changes or []),
        status=None,
        metadata={
            "backup": str(backup),
            "created": [],
        },
    )


def make_executor(tmp_path, test_runner=None, executor=None):
    security = SecurityPolicy(tmp_path)
    transaction_manager = TransactionManager(
        root=tmp_path,
        backup_dir="transactions",
    )

    return RepairExecutor(
        security=security,
        transaction_manager=transaction_manager,
        executor=executor or FakeExecutor(),
        test_runner=test_runner,
    )


def test_validate_risk_rejects_invalid_declared_risk(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="risco inválido",
    ):
        repair_executor._validate_risk(
            {
                "risk": "critico",
                "content": "VALUE = 1\n",
            }
        )


def test_validate_risk_rejects_declared_high_risk(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="alto risco não autorizado",
    ):
        repair_executor._validate_risk(
            {
                "risk": "alto",
                "content": "VALUE = 1\n",
            }
        )


def test_validate_risk_rejects_non_string_content(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="Conteúdo do reparo deve ser texto",
    ):
        repair_executor._validate_risk(
            {
                "risk": "baixo",
                "content": None,
            }
        )


def test_validate_risk_rejects_content_assessed_as_high_risk(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="alto risco não autorizado",
    ):
        repair_executor._validate_risk(
            {
                "risk": "baixo",
                "content": "import subprocess\n",
            }
        )


def test_validate_risk_rejects_medium_when_content_is_high_risk(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="alto risco não autorizado",
    ):
        repair_executor._validate_risk(
            {
                "risk": "medio",
                "content": "import subprocess\n",
            }
        )


def test_validate_risk_accepts_low_risk(tmp_path):
    repair_executor = make_executor(tmp_path)

    assert (
        repair_executor._validate_risk(
            {
                "risk": "baixo",
                "content": "VALUE = 1\n",
            }
        )
        == "baixo"
    )


def test_build_change_rejects_empty_repair(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        ValueError,
        match="Proposta de reparo vazia",
    ):
        repair_executor.build_change(None)


def test_build_change_rejects_none_action(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        ValueError,
        match="RepairEngine não propôs",
    ):
        repair_executor.build_change(
            {
                "action": "none",
                "path": "arquivo.py",
                "content": "VALUE = 1\n",
            }
        )


def test_build_change_rejects_invalid_action(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        ValueError,
        match="Ação de reparo inválida",
    ):
        repair_executor.build_change(
            {
                "action": "delete",
                "path": "arquivo.py",
                "content": "",
            }
        )


def test_build_change_rejects_missing_path(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        ValueError,
        match="Reparo não possui caminho",
    ):
        repair_executor.build_change(
            {
                "action": "create",
                "content": "VALUE = 1\n",
            }
        )


def test_build_change_rejects_non_string_content(tmp_path):
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        ValueError,
        match="Conteúdo do reparo deve ser texto",
    ):
        repair_executor.build_change(
            {
                "action": "create",
                "path": "arquivo.py",
                "content": None,
            }
        )


def test_build_change_rejects_directory_target(tmp_path):
    (tmp_path / "pasta").mkdir()
    repair_executor = make_executor(tmp_path)

    with pytest.raises(
        PermissionError,
        match="Caminho não é um arquivo",
    ):
        repair_executor.build_change(
            {
                "action": "modify",
                "path": "pasta",
                "content": "VALUE = 1\n",
            }
        )


def test_build_change_creates_create_change(tmp_path):
    repair_executor = make_executor(tmp_path)

    change = repair_executor.build_change(
        {
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "correction": "Criar arquivo",
        }
    )

    assert change.change_type == ChangeType.CREATE
    assert change.path == "arquivo.py"
    assert change.content == "VALUE = 1\n"
    assert change.reason == "Criar arquivo"


def test_build_change_creates_modify_change(tmp_path):
    (tmp_path / "arquivo.py").write_text(
        "VALUE = 0\n",
        encoding="utf-8",
    )
    repair_executor = make_executor(tmp_path)

    change = repair_executor.build_change(
        {
            "action": "modify",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
        }
    )

    assert change.change_type == ChangeType.MODIFY
    assert change.path == "arquivo.py"


def test_execute_repair_rejects_symlink(tmp_path):
    target = tmp_path / "real.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    symlink = tmp_path / "link.py"
    symlink.symlink_to(target)

    repair_executor = make_executor(tmp_path)
    transaction = make_transaction(tmp_path)

    with pytest.raises(
        PermissionError,
        match="caminho simbólico",
    ):
        repair_executor.execute_repair(
            repair={
                "action": "modify",
                "path": "link.py",
                "content": "VALUE = 2\n",
                "risk": "baixo",
            },
            instruction="reparar",
            transaction=transaction,
        )


def test_execute_repair_rejects_duplicate_create(tmp_path):
    repair_executor = make_executor(tmp_path)

    existing_change = SimpleNamespace(
        path="arquivo.py",
        change_type=ChangeType.CREATE,
    )
    transaction = make_transaction(
        tmp_path,
        changes=[existing_change],
    )

    with pytest.raises(
        PermissionError,
        match="já está registrado",
    ):
        repair_executor.execute_repair(
            repair={
                "action": "create",
                "path": "arquivo.py",
                "content": "VALUE = 1\n",
                "risk": "baixo",
            },
            instruction="reparar",
            transaction=transaction,
        )


def test_execute_repair_registers_create_and_records_metadata(tmp_path):
    fake_executor = FakeExecutor()
    repair_executor = make_executor(
        tmp_path,
        executor=fake_executor,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "novo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
            "diagnosis": "arquivo ausente",
            "correction": "criar arquivo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is True
    assert result["status"] == "repair_applied"
    assert transaction.status == TransactionStatus.TESTING
    assert transaction.metadata["created"] == ["novo.py"]
    assert len(transaction.changes) == 1
    assert len(transaction.metadata["repairs"]) == 1
    assert transaction.metadata["repairs"][0]["path"] == "novo.py"
    assert fake_executor.executed[0].path == "novo.py"


def test_execute_repair_backs_up_existing_file(tmp_path):
    target = tmp_path / "arquivo.py"
    target.write_text(
        "VALUE = 0\n",
        encoding="utf-8",
    )

    fake_executor = FakeExecutor()
    repair_executor = make_executor(
        tmp_path,
        executor=fake_executor,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "modify",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    backup = (
        tmp_path
        / "transactions"
        / "tx-test"
        / "arquivo.py"
    )

    assert result["success"] is True
    assert backup.read_text(encoding="utf-8") == "VALUE = 0\n"
    assert transaction.metadata["created"] == []
    assert transaction.changes[0].change_type == ChangeType.MODIFY


def test_execute_repair_marks_failed_when_executor_raises(tmp_path):
    fake_executor = FakeExecutor(
        error=RuntimeError("falha física"),
    )
    repair_executor = make_executor(
        tmp_path,
        executor=fake_executor,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "falha física"
    assert transaction.status == TransactionStatus.FAILED


def test_execute_repair_marks_failed_when_test_runner_raises(tmp_path):
    class RaisingTestRunner:
        def run(self, paths):
            raise RuntimeError("falha no test runner")

    repair_executor = make_executor(
        tmp_path,
        test_runner=RaisingTestRunner(),
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "falha no test runner"
    assert transaction.status == TransactionStatus.FAILED


def test_execute_repair_rejects_non_boolean_test_success(tmp_path):
    runner = FakeTestRunner(
        {
            "success": "false",
            "status": "failed",
            "stderr": "",
            "stdout": "",
        }
    )
    repair_executor = make_executor(
        tmp_path,
        test_runner=runner,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "repair_failed"
    assert result["tests"]["success"] is False
    assert result["tests"]["status"] == "invalid_test_result"


def test_execute_repair_without_test_runner_returns_applied(tmp_path):
    fake_executor = FakeExecutor()
    repair_executor = make_executor(
        tmp_path,
        executor=fake_executor,
        test_runner=None,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is True
    assert result["status"] == "repair_applied"
    assert result["repair"]["path"] == "arquivo.py"
    assert transaction.status == TransactionStatus.TESTING


def test_execute_repair_normalizes_invalid_test_result(tmp_path):
    runner = FakeTestRunner(None)
    repair_executor = make_executor(
        tmp_path,
        test_runner=runner,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "repair_failed"
    assert result["tests"]["status"] == "invalid_test_result"
    assert result["tests"]["success"] is False
    assert runner.received == [["arquivo.py"]]


def test_execute_repair_returns_failed_tests(tmp_path):
    runner = FakeTestRunner(
        {
            "success": False,
            "status": "failed",
            "stderr": "teste falhou",
            "stdout": "",
        }
    )
    repair_executor = make_executor(
        tmp_path,
        test_runner=runner,
    )
    transaction = make_transaction(tmp_path)

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "repair_failed"
    assert result["tests"]["stderr"] == "teste falhou"


def test_validate_risk_rejects_assessed_high_risk_after_content_validation(
    tmp_path,
    monkeypatch,
):
    repair_executor = make_executor(tmp_path)

    monkeypatch.setattr(
        repair_executor.security,
        "validate_content",
        lambda content: True,
    )
    monkeypatch.setattr(
        repair_executor.security,
        "assess_content_risk",
        lambda content: "alto",
    )

    with pytest.raises(
        PermissionError,
        match="alto risco não autorizado",
    ):
        repair_executor._validate_risk(
            {
                "risk": "baixo",
                "content": "conteudo seguro no teste",
            }
        )


def test_validate_risk_rejects_medium_when_assessed_risk_is_medium(
    tmp_path,
    monkeypatch,
):
    repair_executor = make_executor(tmp_path)

    monkeypatch.setattr(
        repair_executor.security,
        "validate_content",
        lambda content: True,
    )
    monkeypatch.setattr(
        repair_executor.security,
        "assess_content_risk",
        lambda content: "medio",
    )

    with pytest.raises(
        PermissionError,
        match="Reparo não autorizado pela política de risco",
    ):
        repair_executor._validate_risk(
            {
                "risk": "medio",
                "content": "conteudo de risco medio",
            }
        )


def test_execute_repair_marks_failed_when_semantic_test_runner_raises(
    tmp_path,
):
    class RaisingSemanticTestRunner:
        def run(self, paths):
            return {
                "success": True,
                "returncode": 0,
                "stdout": "syntax ok",
                "stderr": "",
            }

        def run_tests(self, test_files):
            raise RuntimeError("falha nos testes semânticos")

    fake_executor = FakeExecutor()
    repair_executor = make_executor(
        tmp_path,
        executor=fake_executor,
        test_runner=RaisingSemanticTestRunner(),
    )
    transaction = make_transaction(tmp_path)
    transaction.metadata["tests"] = [
        "tests/test_version.py",
    ]

    result = repair_executor.execute_repair(
        repair={
            "action": "create",
            "path": "arquivo.py",
            "content": "VALUE = 1\n",
            "risk": "baixo",
        },
        instruction="reparar",
        transaction=transaction,
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "falha nos testes semânticos"
    assert transaction.status == TransactionStatus.FAILED
