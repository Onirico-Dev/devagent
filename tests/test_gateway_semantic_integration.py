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
    import subprocess

    from agent import DevAgent
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

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "example.py", "version.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


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
