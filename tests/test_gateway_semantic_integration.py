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
