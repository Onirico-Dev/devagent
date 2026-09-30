from core.memory.task_history import TaskHistoryStatus
import pytest
from core.gateway import DevAgentGateway
from core.schemas.models import Change, ChangeType, Transaction


class FakeRepairEngine:
    def analyze_failure(
        self,
        instruction,
        error,
        test_output,
    ):
        return {
            "action": "none",
            "risk": "baixo",
            "path": "",
            "content": "",
            "diagnosis": "Falha semântica sem reparo aplicável.",
            "correction": "",
        }


class FakeAgent:
    def process(self, instruction):
        return {
            "instruction": instruction,
            "objective": "multi-file semantic failure",
            "changes": [
                {
                    "path": "example.py",
                    "change_type": "modify",
                    "content": (
                        'def hello():\n'
                        '    return "hello from DevAgent"\n'
                    ),
                    "reason": "Atualizar hello",
                },
                {
                    "path": "version.py",
                    "change_type": "modify",
                    "content": (
                        'def version():\n'
                        '    return "invalid"\n'
                    ),
                    "reason": "Alterar versão",
                },
            ],
            "tests": ["test_version.py"],
            "risks": [],
        }

    def build_transaction_from_approved_plan(self, plan):
        changes = []

        for change in plan["changes"]:
            changes.append(
                Change(
                    change_type=ChangeType(change["change_type"]),
                    path=change["path"],
                    content=change["content"],
                    reason=change.get("reason", ""),
                )
            )

        return Transaction(
            transaction_id="",
            changes=changes,
            metadata={
                "instruction": plan["instruction"],
                "objective": plan.get("objective"),
                "tests": plan.get("tests", []),
                "risks": plan.get("risks", []),
            },
        )



def test_gateway_persists_rolled_back_status_after_multi_file_failure(tmp_path):
    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )
    (tmp_path / "version.py").write_text(
        'def version():\n'
        '    return "0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "test_version.py").write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)
    gateway.repair_engine = FakeRepairEngine()

    task = gateway.create_task("alterar example.py e version.py")
    approval_id = task["approval_id"]

    result = gateway.approve(approval_id)

    assert result["status"] == "rolled_back"

    assert (
        (tmp_path / "example.py").read_text(encoding="utf-8")
        == 'def hello():\n'
        '    return "hello"\n'
    )
    assert (
        (tmp_path / "version.py").read_text(encoding="utf-8")
        == 'def version():\n'
        '    return "0.1"\n'
    )

    persisted = gateway.get_task(approval_id)

    assert persisted["status"] == "rolled_back"
    assert persisted["approval_id"] == approval_id

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "example.py", "version.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert status == ""


def test_gateway_recovers_incomplete_transaction_after_restart(tmp_path):
    import subprocess

    target = tmp_path / "example.py"
    target.write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    from core.schemas.models import Change, ChangeType, Transaction

    gateway = DevAgentGateway(None, root=tmp_path)

    transaction = Transaction(
        transaction_id="restart-recovery",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="example.py",
                content=(
                    'def hello():\n'
                    '    return "changed"\n'
                ),
                reason="Teste de recovery após restart",
            )
        ],
    )

    transaction = gateway.transactions.begin(transaction)
    for change in transaction.changes:
        gateway.security.validate_path(change.path)
        gateway.transactions.backup_file(
            transaction,
            change.path,
        )

    gateway.executor.execute(transaction)

    assert transaction.status.value == "executing"
    assert target.read_text(encoding="utf-8") == (
        'def hello():\n'
        '    return "changed"\n'
    )

    restarted_gateway = DevAgentGateway(None, root=tmp_path)

    assert target.read_text(encoding="utf-8") == (
        'def hello():\n'
        '    return "hello"\n'
    )

    recovered = restarted_gateway.transactions.load_manifest(
        "restart-recovery"
    )

    assert recovered.status.value == "rolled_back"
    assert restarted_gateway.transactions.list_recoverable_transactions() == []




def test_gateway_recovers_partial_multi_file_transaction_after_restart(tmp_path):
    import subprocess

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text('value = "first-original"\n', encoding="utf-8")
    second.write_text('value = "second-original"\n', encoding="utf-8")

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    from core.schemas.models import Change, ChangeType, Transaction

    gateway = DevAgentGateway(None, root=tmp_path)
    transaction = Transaction(
        transaction_id="partial-restart-recovery",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="first.py",
                content='value = "first-changed"\n',
                reason="partial recovery first",
            ),
            Change(
                change_type=ChangeType.MODIFY,
                path="second.py",
                content='value = "second-changed"\n',
                reason="partial recovery second",
            ),
        ],
    )

    transaction = gateway.transactions.begin(transaction)

    for change in transaction.changes:
        gateway.security.validate_path(change.path)
        gateway.transactions.backup_file(transaction, change.path)

    gateway.executor.execute_change(transaction.changes[0])

    assert first.read_text(encoding="utf-8") == 'value = "first-changed"\n'
    assert second.read_text(encoding="utf-8") == 'value = "second-original"\n'

    restarted_gateway = DevAgentGateway(None, root=tmp_path)

    assert first.read_text(encoding="utf-8") == 'value = "first-original"\n'
    assert second.read_text(encoding="utf-8") == 'value = "second-original"\n'

    recovered = restarted_gateway.transactions.load_manifest(
        "partial-restart-recovery"
    )

    assert recovered.status.value == "rolled_back"
    assert restarted_gateway.transactions.list_recoverable_transactions() == []

def test_gateway_rolls_back_multi_file_transaction_on_declared_semantic_failure(
    tmp_path,
):
    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    (tmp_path / "version.py").write_text(
        'def version():\n'
        '    return "0.1"\n',
        encoding="utf-8",
    )

    (tmp_path / "test_version.py").write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )
    gateway.repair_engine = FakeRepairEngine()

    task = gateway.create_task(
        "alterar example.py e version.py"
    )

    approval_id = task["approval_id"]

    result = gateway.approve(approval_id)

    assert result["status"] == "rolled_back"

    assert (
        (tmp_path / "example.py").read_text(encoding="utf-8")
        == 'def hello():\n    return "hello"\n'
    )

    assert (
        (tmp_path / "version.py").read_text(encoding="utf-8")
        == 'def version():\n    return "0.1"\n'
    )


def test_gateway_repairs_declared_semantic_failure_and_commits(
    tmp_path,
):
    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    (tmp_path / "version.py").write_text(
        'def version():\n'
        '    return "0.1"\n',
        encoding="utf-8",
    )

    (tmp_path / "test_version.py").write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "test@example.com",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "DevAgent Test",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "test: initial semantic repair fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    class RepairingFakeEngine:
        def analyze_failure(
            self,
            instruction,
            error,
            test_output,
        ):
            return {
                "action": "modify",
                "risk": "baixo",
                "path": "version.py",
                "content": (
                    'def version():\n'
                    '    return "0.2"\n'
                ),
                "diagnosis": (
                    "A versão retornada não corresponde "
                    "ao teste semântico declarado."
                ),
                "correction": (
                    "Atualizar version.py para retornar 0.2."
                ),
            }

    gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )
    gateway.repair_engine = RepairingFakeEngine()

    task = gateway.create_task(
        "plan alterar example.py e version.py"
    )

    approval_id = task["approval_id"]

    result = gateway.approve(approval_id)

    assert result["status"] == "committed"
    assert result["repair_attempts"] == 1

    assert (
        (tmp_path / "example.py").read_text(
            encoding="utf-8",
        )
        == (
            'def hello():\n'
            '    return "hello from DevAgent"\n'
        )
    )

    assert (
        (tmp_path / "version.py").read_text(
            encoding="utf-8",
        )
        == (
            'def version():\n'
            '    return "0.2"\n'
        )
    )

    commit_result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        commit_result.stdout.strip()
        != "test: initial semantic repair fixture"
    )


def test_gateway_rolls_back_after_persistent_declared_semantic_failure(
    tmp_path,
):
    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    (tmp_path / "version.py").write_text(
        'def version():\n'
        '    return "0.1"\n',
        encoding="utf-8",
    )

    (tmp_path / "test_version.py").write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "test@example.com",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "DevAgent Test",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "test: persistent semantic failure fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    class PersistentlyWrongRepairEngine:
        def analyze_failure(
            self,
            instruction,
            error,
            test_output,
        ):
            return {
                "action": "modify",
                "risk": "baixo",
                "path": "version.py",
                "content": (
                    'def version():\n'
                    '    return "0.3"\n'
                ),
                "diagnosis": (
                    "O reparo continua produzindo uma versão "
                    "incorreta."
                ),
                "correction": (
                    "Alterar version.py para retornar 0.3."
                ),
            }

    gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )
    gateway.repair_engine = PersistentlyWrongRepairEngine()

    task = gateway.create_task(
        "plan alterar example.py e version.py"
    )

    approval_id = task["approval_id"]
    result = gateway.approve(approval_id)

    assert result["status"] == "rolled_back"
    assert result["repair_attempts"] == 2

    assert (
        (tmp_path / "example.py").read_text(
            encoding="utf-8",
        )
        == (
            'def hello():\n'
            '    return "hello"\n'
        )
    )

    assert (
        (tmp_path / "version.py").read_text(
            encoding="utf-8",
        )
        == (
            'def version():\n'
            '    return "0.1"\n'
        )
    )

    semantic_check = subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "test_version.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert semantic_check.returncode != 0

    commit_result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        commit_result.stdout.strip()
        == "test: persistent semantic failure fixture"
    )


def test_gateway_rolls_back_real_executor_failure_on_second_change(tmp_path):
    from agent import DevAgent
    import subprocess

    from core.gateway import DevAgentGateway

    example = tmp_path / "example.py"
    version = tmp_path / "version.py"

    example.write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )
    version.write_text(
        'def version():\n'
        '    return "0.1"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial executor failure fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    gateway = DevAgentGateway(DevAgent(tmp_path), root=tmp_path)
    task = gateway.create_task("alterar example.py e version.py")
    approval_id = task["approval_id"]

    original_execute_change = gateway.executor.execute_change
    calls = []

    def fail_on_second_change(change):
        calls.append(change.path)
        if len(calls) == 2:
            raise RuntimeError("SECOND_CHANGE_FAILURE")
        return original_execute_change(change)

    gateway.executor.execute_change = fail_on_second_change

    result = gateway.approve(approval_id)

    assert result["status"] == "rolled_back"
    assert len(calls) == 2

    assert example.read_text(encoding="utf-8") == (
        'def hello():\n'
        '    return "hello"\n'
    )
    assert version.read_text(encoding="utf-8") == (
        'def version():\n'
        '    return "0.1"\n'
    )

    persisted = gateway.get_task(approval_id)
    assert persisted["status"] == "rolled_back"
    assert persisted["approval_id"] == approval_id

    transaction = gateway.transactions.load_manifest(
        persisted["transaction_id"]
    )
    execution = transaction.metadata["execution"]
    assert execution["phase"] == "executing"
    assert execution["changes_applied"] == 1

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "example.py", "version.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""



def test_gateway_recovers_after_crash_after_first_change(tmp_path):
    import subprocess

    from agent import DevAgent
    from core.gateway import DevAgentGateway
    from core.memory.task_history import TaskHistoryStatus

    example = tmp_path / "example.py"
    version = tmp_path / "version.py"

    original_example = (
        'def hello():\n'
        '    return "hello"\n'
    )
    original_version = (
        'def version():\n'
        '    return "0.1"\n'
    )

    example.write_text(original_example, encoding="utf-8")
    version.write_text(original_version, encoding="utf-8")

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: crash after first change"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    gateway = DevAgentGateway(
        DevAgent(tmp_path),
        root=tmp_path,
    )

    task = gateway.create_task(
        "alterar example.py e version.py"
    )
    approval_id = task["approval_id"]

    original_execute_change = gateway.executor.execute_change
    calls = []

    def crash_before_second_change(change):
        calls.append(change.path)

        if len(calls) == 2:
            raise SystemExit("CRASH_BEFORE_SECOND_CHANGE")

        return original_execute_change(change)

    gateway.executor.execute_change = crash_before_second_change

    with pytest.raises(
        SystemExit,
        match="CRASH_BEFORE_SECOND_CHANGE",
    ):
        gateway.approve(approval_id)

    assert len(calls) == 2

    assert example.read_text(encoding="utf-8") != original_example

    persisted_before_restart = gateway.transactions.load_manifest(
        gateway.history.get(approval_id)["transaction_id"]
    )
    execution_before_restart = (
        persisted_before_restart.metadata["execution"]
    )

    assert execution_before_restart["phase"] == "executing"
    assert execution_before_restart["changes_applied"] == 1

    restarted = DevAgentGateway(
        DevAgent(tmp_path),
        root=tmp_path,
    )

    assert example.read_text(encoding="utf-8") == original_example
    assert version.read_text(encoding="utf-8") == original_version

    persisted = restarted.history.get(approval_id)

    assert persisted is not None
    assert persisted["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert persisted["transaction_id"] is not None
    assert restarted.transactions.list_recoverable_transactions() == []

def test_gateway_recovers_after_crash_during_repair_execution(tmp_path):
    import subprocess

    from agent import DevAgent
    from core.gateway import DevAgentGateway

    example = tmp_path / "example.py"
    version = tmp_path / "version.py"
    test_version = tmp_path / "test_version.py"

    original_example = (
        'def hello():\n'
        '    return "hello"\n'
    )
    original_version = (
        'def version():\n'
        '    return "0.1"\n'
    )

    example.write_text(original_example, encoding="utf-8")
    version.write_text(original_version, encoding="utf-8")
    test_version.write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: repair crash fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    class RepairingFakeEngine:
        def analyze_failure(
            self,
            instruction,
            error,
            test_output,
        ):
            return {
                "action": "modify",
                "risk": "baixo",
                "path": "version.py",
                "content": (
                    'def version():\n'
                    '    return "0.2"\n'
                ),
                "diagnosis": "A versão falhou no teste semântico.",
                "correction": "Atualizar version.py para retornar 0.2.",
            }

    gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )
    gateway.repair_engine = RepairingFakeEngine()

    original_execute_change = gateway.executor.execute_change
    calls = []

    def crash_after_repair(change):
        calls.append(change.path)
        original_execute_change(change)
        if len(calls) == 3:
            raise SystemExit("CRASH_DURING_REPAIR")

    gateway.executor.execute_change = crash_after_repair

    task = gateway.create_task(
        "plan alterar example.py e version.py"
    )
    approval_id = task["approval_id"]

    try:
        gateway.approve(approval_id)
    except SystemExit as exc:
        assert str(exc) == "CRASH_DURING_REPAIR"
    else:
        raise AssertionError("O crash durante o reparo deveria interromper o processo.")

    assert version.read_text(encoding="utf-8") == (
        'def version():\n'
        '    return "0.2"\n'
    )

    restarted_gateway = DevAgentGateway(
        DevAgent(tmp_path),
        root=tmp_path,
    )

    assert example.read_text(encoding="utf-8") == original_example
    assert version.read_text(encoding="utf-8") == original_version

    persisted = restarted_gateway.get_task(approval_id)
    assert persisted["status"] == "rolled_back"
    assert persisted["approval_id"] == approval_id

    assert restarted_gateway.transactions.list_recoverable_transactions() == []


def test_gateway_recovers_after_crash_persisting_repair_state(tmp_path, monkeypatch):
    import subprocess
    from agent import DevAgent
    from core.gateway import DevAgentGateway

    example = tmp_path / "example.py"
    version = tmp_path / "version.py"
    test_version = tmp_path / "test_version.py"

    original_example = 'def hello():\n    return "hello"\n'
    original_version = 'def version():\n    return "0.1"\n'

    example.write_text(original_example, encoding="utf-8")
    version.write_text(original_version, encoding="utf-8")
    test_version.write_text(
        'from version import version\n\n'
        'def test_version():\n'
        '    assert version() == "0.2"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: repair state crash fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    class RepairingFakeEngine:
        def analyze_failure(self, instruction, error, test_output):
            return {
                "action": "modify",
                "risk": "baixo",
                "path": "version.py",
                "content": (
                    'def version():\n'
                    '    return "0.2"\n'
                ),
                "diagnosis": "A versão falhou no teste semântico.",
                "correction": "Atualizar version.py para retornar 0.2.",
            }

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)
    gateway.repair_engine = RepairingFakeEngine()

    from core.engine.repair_cycle_state import RepairCycleState

    original_persist = RepairCycleState.persist
    calls = []

    def crash_on_repair_state_persist(state, transaction):
        calls.append(state.status)
        original_persist(state, transaction)
        if len(calls) == 3:
            raise SystemExit("CRASH_DURING_REPAIR_STATE_PERSIST")

    monkeypatch.setattr(
        RepairCycleState,
        "persist",
        crash_on_repair_state_persist,
    )

    task = gateway.create_task(
        "plan alterar example.py e version.py"
    )
    approval_id = task["approval_id"]

    try:
        gateway.approve(approval_id)
    except SystemExit as exc:
        assert str(exc) == "CRASH_DURING_REPAIR_STATE_PERSIST"
    else:
        raise AssertionError(
            "O crash durante a persistência do estado do reparo deveria interromper o processo."
        )

    restarted_gateway = DevAgentGateway(
        DevAgent(tmp_path),
        root=tmp_path,
    )

    assert example.read_text(encoding="utf-8") == original_example
    assert version.read_text(encoding="utf-8") == original_version

    persisted = restarted_gateway.get_task(approval_id)
    assert persisted["status"] == "rolled_back"
    assert persisted["approval_id"] == approval_id
    assert restarted_gateway.transactions.list_recoverable_transactions() == []


def test_gateway_serializes_concurrent_approve_for_same_task(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import subprocess

    from agent import DevAgent
    from core.gateway import DevAgentGateway

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "devagent@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    gateway = DevAgentGateway(
        DevAgent(tmp_path),
        tmp_path,
    )

    task = gateway.create_task(
        "crie concurrent_test.py contendo "
        "def test_concurrent(): assert 2 + 2 == 4"
    )

    approval_id = task["approval_id"]

    def approve():
        try:
            return ("ok", gateway.approve(approval_id))
        except Exception as exc:
            return ("error", type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: approve(), range(2)))

    successful = [
        result for result in results
        if result[0] == "ok"
    ]
    failed = [
        result for result in results
        if result[0] == "error"
    ]

    assert len(successful) == 1
    assert len(failed) == 1
    assert failed[0][1] in {
        "ValueError",
        "RuntimeError",
    }

    assert (tmp_path / "concurrent_test.py").read_text() == (
        "def test_concurrent(): assert 2 + 2 == 4"
    )

    final_task = gateway.get_task(approval_id)
    assert final_task["status"] == "committed"

def test_gateway_recovers_commit_failure_after_restart(tmp_path, monkeypatch):
    import pytest
    import subprocess

    target = tmp_path / "commit-restart.py"
    target.write_text(
        'VALUE = "original"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    from core.engine.repair_cycle_state import RepairCycleState
    from core.gateway import DevAgentGateway
    from core.schemas.models import Change, ChangeType, Transaction
    from core.gateway import CommitTransactionError

    gateway = DevAgentGateway(None, root=tmp_path)

    transaction = Transaction(
        transaction_id="commit-restart-recovery",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="commit-restart.py",
                content='VALUE = "changed"\n',
                reason="Teste de recovery após falha de commit",
            )
        ],
    )

    transaction = gateway.transactions.begin(transaction)

    for change in transaction.changes:
        gateway.security.validate_path(change.path)
        gateway.transactions.backup_file(transaction, change.path)

    gateway.executor.execute(transaction)

    assert target.read_text(encoding="utf-8") == 'VALUE = "changed"\n'
    assert transaction.status.value == "executing"

    repair_state = RepairCycleState(
        transaction_id=transaction.transaction_id,
    )

    def failing_commit(*args, **kwargs):
        raise CommitTransactionError(
            "COMMIT_FAILURE_RESTART_TEST",
            result={
                "status": "failed",
                "message": "COMMIT_FAILURE_RESTART_TEST",
            },
        )

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        failing_commit,
    )

    with pytest.raises(CommitTransactionError, match="COMMIT_FAILURE_RESTART_TEST"):
        gateway.transaction_flow.commit_transaction(
            approval_id="commit-restart-approval",
            instruction="alterar commit-restart.py",
            transaction=transaction,
            test_result={"success": True},
            repair_state=repair_state,
        )

    assert transaction.status.value == "executing"
    assert target.read_text(encoding="utf-8") == 'VALUE = "changed"\n'

    restarted_gateway = DevAgentGateway(None, root=tmp_path)

    assert target.read_text(encoding="utf-8") == 'VALUE = "original"\n'

    recovered = restarted_gateway.transactions.load_manifest(
        "commit-restart-recovery",
    )
    assert recovered.status.value == "rolled_back"
    assert restarted_gateway.transactions.list_recoverable_transactions() == []


def test_gateway_recovers_testing_transaction_after_restart(tmp_path):
    import subprocess

    target = tmp_path / "testing-restart.py"
    target.write_text(
        'VALUE = "original"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    from core.engine.repair_cycle_state import RepairCycleState
    from core.gateway import DevAgentGateway
    from core.memory.task_history import TaskHistoryStatus
    from core.schemas.models import Change, ChangeType, Transaction, TransactionStatus

    gateway = DevAgentGateway(None, root=tmp_path)

    transaction = Transaction(
        transaction_id="testing-restart-recovery",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="testing-restart.py",
                content='VALUE = "changed"\n',
                reason="Teste de recovery em TESTING após restart",
            )
        ],
    )

    transaction = gateway.transactions.begin(transaction)

    for change in transaction.changes:
        gateway.security.validate_path(change.path)
        gateway.transactions.backup_file(transaction, change.path)

    gateway.executor.execute(transaction)

    repair_state = RepairCycleState(
        transaction_id=transaction.transaction_id,
    )
    repair_state.mark_testing()
    gateway.transactions.transition(
        transaction,
        TransactionStatus.TESTING,
    )
    repair_state.persist(transaction)

    approval_id = "testing-restart-approval"
    gateway.history.create(
        approval_id=approval_id,
        instruction="Teste de recovery em TESTING",
        plan={"instruction": "Teste de recovery em TESTING"},
    )
    gateway.history.update(
        approval_id,
        status=TaskHistoryStatus.TESTING.value,
        transaction_id=transaction.transaction_id,
    )

    assert transaction.status == TransactionStatus.TESTING
    assert target.read_text(encoding="utf-8") == 'VALUE = "changed"\n'
    assert gateway.history.get(approval_id)["status"] == (
        TaskHistoryStatus.TESTING.value
    )
    assert gateway.history.get(approval_id)["transaction_id"] == (
        transaction.transaction_id
    )

    restarted_gateway = DevAgentGateway(None, root=tmp_path)

    assert target.read_text(encoding="utf-8") == 'VALUE = "original"\n'

    recovered = restarted_gateway.transactions.load_manifest(
        "testing-restart-recovery",
    )
    assert recovered.status == TransactionStatus.ROLLED_BACK
    assert restarted_gateway.transactions.list_recoverable_transactions() == []

    history_task = restarted_gateway.history.get(approval_id)
    assert history_task["status"] == TaskHistoryStatus.ROLLED_BACK.value
    assert history_task["transaction_id"] == transaction.transaction_id

def test_gateway_recovers_transaction_started_before_supervisor_approval_after_restart(tmp_path, monkeypatch):
    import subprocess

    target = tmp_path / "example.py"
    target.write_text("old\\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)

    task = gateway.create_task("alterar example.py")
    approval_id = task["approval_id"]

    original_approve = gateway.supervisor.approve

    def crash_before_approval(*args, **kwargs):
        raise RuntimeError("CRASH_BEFORE_APPROVAL")

    monkeypatch.setattr(
        gateway.supervisor,
        "approve",
        crash_before_approval,
    )

    with pytest.raises(RuntimeError, match="CRASH_BEFORE_APPROVAL"):
        gateway.approve(approval_id)

    assert target.read_text(encoding="utf-8") == "old\\n"

    recoverable = gateway.transactions.list_recoverable_transactions()
    assert len(recoverable) == 1

    restarted = DevAgentGateway(FakeAgent(), root=tmp_path)

    assert target.read_text(encoding="utf-8") == "old\\n"
    assert restarted.transactions.list_recoverable_transactions() == []

    approval_after_restart = restarted.supervisor.get(approval_id)
    assert approval_after_restart is not None
    assert approval_after_restart["status"] != "approved"


def test_gateway_recovers_after_history_update_crash_after_supervisor_approval(
    tmp_path,
    monkeypatch,
):
    import subprocess

    target = tmp_path / "example.py"
    target.write_text("old\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)
    task = gateway.create_task("alterar example.py")
    approval_id = task["approval_id"]

    original_history_update = gateway.transaction_flow._history_update

    def crash_on_executing(approval_id_arg, status, transaction_id=None, **kwargs):
        if status == TaskHistoryStatus.EXECUTING.value:
            raise RuntimeError("CRASH_AFTER_APPROVAL")
        return original_history_update(
            approval_id_arg,
            status=status,
            transaction_id=transaction_id,
            **kwargs,
        )

    monkeypatch.setattr(
        gateway.transaction_flow,
        "_history_update",
        crash_on_executing,
    )

    with pytest.raises(RuntimeError, match="CRASH_AFTER_APPROVAL"):
        gateway.approve(approval_id)

    approval = gateway.supervisor.get(approval_id)
    assert approval["status"] == "approved"

    recoverable = gateway.transactions.list_recoverable_transactions()
    assert len(recoverable) == 1

    restarted = DevAgentGateway(FakeAgent(), root=tmp_path)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert restarted.transactions.list_recoverable_transactions() == []

    recovered_approval = restarted.supervisor.get(approval_id)
    assert recovered_approval is not None
    assert recovered_approval["status"] == "approved"

    history_task = restarted.history.get(approval_id)
    assert history_task is not None
    assert history_task["status"] == TaskHistoryStatus.ROLLED_BACK.value

def test_gateway_recovers_after_crash_after_history_executing_before_execution(
    tmp_path,
    monkeypatch,
):
    import subprocess

    target = tmp_path / "example.py"
    target.write_text("old\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)
    task = gateway.create_task("alterar example.py")
    approval_id = task["approval_id"]

    def crash_before_execution(transaction, on_change_applied=None):
        raise SystemExit("CRASH_BEFORE_EXECUTION")

    monkeypatch.setattr(
        gateway.executor,
        "execute",
        crash_before_execution,
    )

    with pytest.raises(SystemExit, match="CRASH_BEFORE_EXECUTION"):
        gateway.approve(approval_id)

    history_task = gateway.history.get(approval_id)
    assert history_task is not None
    assert history_task["status"] == TaskHistoryStatus.EXECUTING.value
    assert history_task["transaction_id"] is not None

    assert len(gateway.transactions.list_recoverable_transactions()) == 1

    restarted = DevAgentGateway(FakeAgent(), root=tmp_path)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert restarted.transactions.list_recoverable_transactions() == []

    recovered_history = restarted.history.get(approval_id)
    assert recovered_history is not None
    assert recovered_history["status"] == TaskHistoryStatus.ROLLED_BACK.value



def test_gateway_handles_crash_after_git_commit_before_final_persistence(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from core.gateway import DevAgentGateway
    from core.memory.task_history import TaskHistoryStatus

    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    target = tmp_path / "version.py"
    target.write_text(
        "old\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)
    monkeypatch.setattr(
        gateway.tests,
        "run_tests",
        lambda tests: {
            "success": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
    )

    task = gateway.create_task("alterar version.py")
    approval_id = task["approval_id"]

    original_commit = gateway.git.commit_transaction

    def commit_then_crash(*args, **kwargs):
        result = original_commit(*args, **kwargs)
        raise SystemExit("CRASH_AFTER_GIT_COMMIT")

    monkeypatch.setattr(
        gateway.git,
        "commit_transaction",
        commit_then_crash,
    )

    with pytest.raises(
        SystemExit,
        match="CRASH_AFTER_GIT_COMMIT",
    ):
        gateway.approve(approval_id)

    assert (
        target.read_text(encoding="utf-8")
        != "old\n"
    )

    assert (
        gateway.history.get(approval_id)["status"]
        == TaskHistoryStatus.TESTING.value
    )

    restarted_gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )

    assert (
        target.read_text(encoding="utf-8")
        != "old\n"
    )

    import subprocess

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    print(f"POST_RECOVERY_HEAD={head}")
    print(f"POST_RECOVERY_LOG={log}")
    print(f"POST_RECOVERY_STATUS={status!r}")

    recovered_history = (
        restarted_gateway.history.get(approval_id)
    )
    assert recovered_history is not None
    assert (
        recovered_history["status"]
        == TaskHistoryStatus.COMMITTED.value
    )

def test_gateway_recovers_testing_transaction_after_tests_run_crash(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from core.gateway import DevAgentGateway
    from core.memory.task_history import TaskHistoryStatus

    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    target = tmp_path / "version.py"
    target.write_text(
        "old\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)

    task = gateway.create_task("alterar version.py")
    approval_id = task["approval_id"]

    def crash_during_tests(paths):
        raise SystemExit("CRASH_DURING_TESTS")

    monkeypatch.setattr(
        gateway.tests,
        "run",
        crash_during_tests,
    )

    with pytest.raises(
        SystemExit,
        match="CRASH_DURING_TESTS",
    ):
        gateway.approve(approval_id)

    history = gateway.history.get(approval_id)
    assert history["status"] == TaskHistoryStatus.TESTING.value
    assert history["transaction_id"]

    recoverable = (
        gateway.transactions.list_recoverable_transactions()
    )
    assert len(recoverable) == 1

    restarted_gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )

    assert (
        (tmp_path / "version.py").read_text(
            encoding="utf-8",
        )
        == "old\n"
    )

    assert (
        restarted_gateway.transactions
        .list_recoverable_transactions()
        == []
    )

    recovered_history = (
        restarted_gateway.history.get(approval_id)
    )
    assert (
        recovered_history["status"]
        == TaskHistoryStatus.ROLLED_BACK.value
    )

def test_gateway_recovers_after_testing_persist_before_history_update_crash(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from core.gateway import DevAgentGateway
    from core.schemas.models import TransactionStatus
    from core.memory.task_history import TaskHistoryStatus

    (tmp_path / "example.py").write_text(
        'def hello():\n'
        '    return "hello"\n',
        encoding="utf-8",
    )

    target = tmp_path / "version.py"
    target.write_text(
        "old\\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)

    task = gateway.create_task(
        "alterar version.py"
    )
    approval_id = task["approval_id"]

    original_history_update = (
        gateway.transaction_flow._history_update
    )

    def crash_on_testing(
        approval,
        *,
        status,
        transaction_id,
        **kwargs,
    ):
        if status == TaskHistoryStatus.TESTING.value:
            raise SystemExit("CRASH_AFTER_TESTING_PERSIST")
        return original_history_update(
            approval,
            status=status,
            transaction_id=transaction_id,
            **kwargs,
        )


    monkeypatch.setattr(
        gateway.transaction_flow,
        "_history_update",
        crash_on_testing,
    )

    with pytest.raises(
        SystemExit,
        match="CRASH_AFTER_TESTING_PERSIST",
    ):
        gateway.approve(approval_id)

    task = gateway.history.get(approval_id)
    assert task is not None
    assert task["status"] == TaskHistoryStatus.EXECUTING.value
    assert task["transaction_id"]

    recoverable = (
        gateway.transactions.list_recoverable_transactions()
    )
    assert len(recoverable) == 1
    assert recoverable[0].status == TransactionStatus.TESTING

    restarted_gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )

    assert target.read_text(
        encoding="utf-8"
    ) == "old\\n"

    assert (
        restarted_gateway.transactions.list_recoverable_transactions()
        == []
    )

    recovered_task = restarted_gateway.history.get(
        approval_id
    )
    assert recovered_task is not None
    assert (
        recovered_task["status"]
        == TaskHistoryStatus.ROLLED_BACK.value
    )

def test_gateway_reconciles_terminal_manifest_after_commit_history_crash(
    tmp_path,
    monkeypatch,
):
    import subprocess

    from core.gateway import DevAgentGateway
    from core.memory.task_history import TaskHistoryStatus

    target = tmp_path / "version.py"
    target.write_text("old\n", encoding="utf-8")

    test_version = tmp_path / "test_version.py"
    test_version.write_text(
        "from version import version\n\n"
        "def test_version():\n"
        "    assert version() == \"invalid\"\n",
        encoding="utf-8",
    )

    example = tmp_path / "example.py"
    example.write_text(
        'def hello():\n    return "hello"\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test: initial fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    gateway = DevAgentGateway(FakeAgent(), root=tmp_path)

    monkeypatch.setattr(
        gateway.tests,
        "run",
        lambda tests: {
            "success": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
    )

    task = gateway.create_task("alterar version.py")
    approval_id = task["approval_id"]

    original_history_update = gateway._history_update

    def crash_after_terminal_persist(
        approval,
        *,
        status,
        transaction_id,
        **kwargs,
    ):
        if status == TaskHistoryStatus.COMMITTED.value:
            raise SystemExit("CRASH_AFTER_COMMIT_BEFORE_HISTORY")
        return original_history_update(
            approval,
            status=status,
            transaction_id=transaction_id,
            **kwargs,
        )

    monkeypatch.setattr(
        gateway,
        "_history_update",
        crash_after_terminal_persist,
    )
    gateway.transaction_flow._history_update = (
        crash_after_terminal_persist
    )

    with pytest.raises(
        SystemExit,
        match="CRASH_AFTER_COMMIT_BEFORE_HISTORY",
    ):
        gateway.approve(approval_id)

    history_before_restart = gateway.history.get(approval_id)
    assert history_before_restart is not None
    assert (
        history_before_restart["status"]
        == TaskHistoryStatus.TESTING.value
    )

    manifest = gateway.transactions.load_manifest(
        history_before_restart["transaction_id"]
    )
    assert manifest.status.value == "committed"

    restarted_gateway = DevAgentGateway(
        FakeAgent(),
        root=tmp_path,
    )

    recovered_history = restarted_gateway.history.get(approval_id)

    assert recovered_history is not None
    assert (
        recovered_history["status"]
        == TaskHistoryStatus.COMMITTED.value
    )
    assert (
        recovered_history["transaction_id"]
        == history_before_restart["transaction_id"]
    )
    assert target.read_text(encoding="utf-8") != "old\n"
