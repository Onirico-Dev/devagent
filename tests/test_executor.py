from pathlib import Path

import pytest

from core.executor.safe_executor import SafeExecutor
from core.executor.transaction_manager import TransactionManager
from core.executor.git_manager import GitManager
from core.schemas.models import (
    Change,
    ChangeType,
    Transaction,
    TransactionStatus,
)


def make_transaction(*changes):
    return Transaction(
        transaction_id="test",
        changes=list(changes),
    )


def test_create_file():
    root = Path(".")

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="novo.py",
            content='print("ok")',
        )
    )

    executor = SafeExecutor(root)
    result = executor.execute(transaction)

    assert result.status == TransactionStatus.EXECUTING
    assert Path("novo.py").read_text(encoding="utf-8") == 'print("ok")'

    Path("novo.py").unlink()


def test_create_existing_file_fails():
    target = Path("existente.py")
    target.write_text("original", encoding="utf-8")

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="existente.py",
            content="novo",
        )
    )

    executor = SafeExecutor(".")

    with pytest.raises(FileExistsError):
        executor.execute(transaction)

    assert transaction.status == TransactionStatus.FAILED
    assert target.read_text(encoding="utf-8") == "original"

    target.unlink()


def test_modify_file():
    target = Path("modificar.py")
    target.write_text("antes", encoding="utf-8")

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="modificar.py",
            content="depois",
        )
    )

    executor = SafeExecutor(".")
    result = executor.execute(transaction)

    assert result.status == TransactionStatus.EXECUTING
    assert target.read_text(encoding="utf-8") == "depois"

    target.unlink()


def test_modify_missing_file_fails():
    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="nao_existe.py",
            content="conteudo",
        )
    )

    executor = SafeExecutor(".")

    with pytest.raises(FileNotFoundError):
        executor.execute(transaction)

    assert transaction.status == TransactionStatus.FAILED


def test_delete_file():
    target = Path("deletar.py")
    target.write_text("apagar", encoding="utf-8")

    transaction = make_transaction(
        Change(
            change_type=ChangeType.DELETE,
            path="deletar.py",
        )
    )

    executor = SafeExecutor(".")
    result = executor.execute(transaction)

    assert result.status == TransactionStatus.EXECUTING
    assert not target.exists()


def test_delete_missing_file_fails():
    transaction = make_transaction(
        Change(
            change_type=ChangeType.DELETE,
            path="nao_existe.py",
        )
    )

    executor = SafeExecutor(".")

    with pytest.raises(FileNotFoundError):
        executor.execute(transaction)

    assert transaction.status == TransactionStatus.FAILED


def test_path_outside_project_is_blocked():
    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="../arquivo_bloqueado.py",
            content="nao deve existir",
        )
    )

    executor = SafeExecutor(".")

    with pytest.raises(ValueError):
        executor.execute(transaction)


def test_rollback_created_file():
    manager = TransactionManager(".")
    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="rollback_create.py",
            content="criado",
        )
    )

    manager.begin(transaction)

    target = Path("rollback_create.py")
    target.write_text("criado", encoding="utf-8")

    manager.register_created(
        transaction,
        "rollback_create.py",
    )

    manager.rollback(transaction)

    assert not target.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_modified_file():
    target = Path("rollback_modify.py")
    target.write_text("original", encoding="utf-8")

    manager = TransactionManager(".")
    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="rollback_modify.py",
            content="alterado",
        )
    )

    manager.begin(transaction)
    manager.backup_file(transaction, "rollback_modify.py")

    target.write_text("alterado", encoding="utf-8")

    manager.rollback(transaction)

    assert target.read_text(encoding="utf-8") == "original"
    assert transaction.status == TransactionStatus.ROLLED_BACK

    target.unlink()


def test_transaction_rollback_restores_deleted_file_after_later_failure(
    tmp_path,
):
    target = tmp_path / "important.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.DELETE,
            path="important.py",
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="nao_existe.py",
            content="falha",
        ),
    )

    manager.begin(transaction)

    # O arquivo que será apagado precisa ser salvo
    # antes da execução da transação.
    manager.backup_file(
        transaction,
        "important.py",
    )

    try:
        executor.execute(transaction)
    except FileNotFoundError:
        transaction.status = TransactionStatus.FAILED

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_transaction_rollback_is_atomic_for_multiple_changes(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    third = tmp_path / "third.py"

    first_original = 'print("FIRST ORIGINAL")\n'
    second_original = 'print("SECOND ORIGINAL")\n'

    first.write_text(first_original, encoding="utf-8")
    second.write_text(second_original, encoding="utf-8")

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="first.py",
            content='print("FIRST MODIFIED")\n',
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="second.py",
            content='print("SECOND MODIFIED")\n',
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="third.py",
            content='print("THIRD")\n',
        ),
    )

    manager.begin(transaction)

    manager.backup_file(transaction, "first.py")
    manager.backup_file(transaction, "second.py")
    manager.backup_file(transaction, "third.py")

    try:
        executor.execute(transaction)
    except FileNotFoundError:
        transaction.status = TransactionStatus.FAILED
        manager.rollback(transaction)

    assert first.read_text(encoding="utf-8") == first_original
    assert second.read_text(encoding="utf-8") == second_original
    assert not third.exists()

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_transaction_manager_rejects_path_outside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="../fora.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.backup_file(
            transaction,
            "../fora.py",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou caminho fora do projeto."
        )


def test_create_existing_file_fails_without_overwriting(tmp_path):
    target = tmp_path / "existing.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="existing.py",
            content='print("NEW")\n',
        ),
    )

    manager.begin(transaction)

    try:
        executor.execute(transaction)
    except FileExistsError:
        transaction.status = TransactionStatus.FAILED
        manager.rollback(transaction)
    else:
        raise AssertionError(
            "CREATE sobrescreveu arquivo existente."
        )

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_git_manager_commits_transaction(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "created.py"
    target.write_text(
        'print("COMMITTED")\n',
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-test",
        "Criar created.py",
    )

    assert result["status"] == "committed"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "DevAgent: transação transaction-test" in log.stdout


def test_git_manager_returns_no_changes_without_modifications(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-empty",
        "Nenhuma alteração",
    )

    assert result["status"] == "no_changes"


def test_rollback_restores_modified_file(tmp_path):
    target = tmp_path / "restore.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="restore.py",
            content='print("MODIFIED")\n',
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "restore.py",
    )

    executor.execute(transaction)

    assert target.read_text(
        encoding="utf-8",
    ) == 'print("MODIFIED")\n'

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_restores_deleted_file(tmp_path):
    target = tmp_path / "deleted.py"
    original = 'print("DELETE ME")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.DELETE,
            path="deleted.py",
            content=None,
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "deleted.py",
    )

    executor.execute(transaction)

    assert not target.exists()

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_failed_transaction_does_not_commit(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "broken.py"

    target.write_text(
        "isto não é Python válido\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    status = manager.status()

    assert "broken.py" in status

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert log.returncode != 0


def test_rollback_restores_multiple_changes_atomically(tmp_path):
    existing = tmp_path / "existing.py"
    created = tmp_path / "created.py"

    original = 'print("ORIGINAL")\n'

    existing.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="existing.py",
            content='print("MODIFIED")\n',
        ),
        Change(
            change_type=ChangeType.CREATE,
            path="created.py",
            content='print("CREATED")\n',
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "existing.py",
    )

    manager.register_created(
        transaction,
        "created.py",
    )

    executor.execute(transaction)

    assert existing.read_text(
        encoding="utf-8",
    ) == 'print("MODIFIED")\n'

    assert created.exists()

    manager.rollback(transaction)

    assert existing.exists()

    assert existing.read_text(
        encoding="utf-8",
    ) == original

    assert not created.exists()

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_transaction_manager_rejects_created_path_outside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="../fora.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.register_created(
            transaction,
            "../fora.py",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou arquivo criado fora do projeto."
        )


def test_rollback_rejects_created_path_outside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="seguro.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    transaction.metadata["created"] = ["../fora.py"]

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou caminho criado fora do projeto."
        )


def test_safe_executor_rejects_path_outside_project(tmp_path):
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="../fora.py",
            content="conteudo",
        ),
    )

    try:
        executor.execute(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "SafeExecutor aceitou caminho fora do projeto."
        )


def test_rollback_rejects_backup_path_outside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="seguro.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    backup_root = tmp_path / "transactions" / transaction.transaction_id
    malicious_backup = backup_root / ".." / ".." / "fora.py"

    malicious_backup.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    malicious_backup.write_text(
        "conteudo malicioso",
        encoding="utf-8",
    )

    transaction.metadata["backup"] = str(
        malicious_backup
    )

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou backup fora do projeto."
        )


def test_register_created_rejects_directory(tmp_path):
    manager = TransactionManager(tmp_path)

    directory = tmp_path / "diretorio"
    directory.mkdir()

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="diretorio",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.register_created(
            transaction,
            "diretorio",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager registrou diretório como arquivo criado."
        )


def test_rollback_restores_multiple_files(tmp_path):
    manager = TransactionManager(tmp_path)

    first = tmp_path / "primeiro.py"
    second = tmp_path / "segundo.py"

    first_original = 'print("PRIMEIRO ORIGINAL")\n'
    second_original = 'print("SEGUNDO ORIGINAL")\n'

    first.write_text(
        first_original,
        encoding="utf-8",
    )

    second.write_text(
        second_original,
        encoding="utf-8",
    )

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="primeiro.py",
            content='print("ALTERADO")\n',
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="segundo.py",
            content='print("ALTERADO")\n',
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "primeiro.py",
    )

    manager.backup_file(
        transaction,
        "segundo.py",
    )

    first.write_text(
        'print("ALTERADO")\n',
        encoding="utf-8",
    )

    second.write_text(
        'print("ALTERADO")\n',
        encoding="utf-8",
    )

    manager.rollback(transaction)

    assert first.read_text(
        encoding="utf-8",
    ) == first_original

    assert second.read_text(
        encoding="utf-8",
    ) == second_original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_backup_file_rejects_directory(tmp_path):
    manager = TransactionManager(tmp_path)

    directory = tmp_path / "diretorio"
    directory.mkdir()

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="diretorio",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.backup_file(
            transaction,
            "diretorio",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "backup_file aceitou diretório como arquivo."
        )


def test_backup_file_copies_existing_file(tmp_path):
    manager = TransactionManager(tmp_path)

    target = tmp_path / "original.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="original.py",
            content='print("ALTERADO")\n',
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "original.py",
    )

    backup_root = Path(
        transaction.metadata["backup"]
    )

    backup = backup_root / "original.py"

    assert backup.exists()
    assert backup.read_text(
        encoding="utf-8",
    ) == original


def test_rollback_restores_modified_file_after_real_change(tmp_path):
    manager = TransactionManager(tmp_path)

    target = tmp_path / "app.py"
    original = 'print("ORIGINAL")\n'
    modified = 'print("MODIFICADO")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content=modified,
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "app.py",
    )

    target.write_text(
        modified,
        encoding="utf-8",
    )

    assert target.read_text(
        encoding="utf-8",
    ) == modified

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_rejects_backup_directory(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="seguro.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    backup_root = Path(
        transaction.metadata["backup"]
    )

    directory = backup_root / "diretorio"
    directory.mkdir(parents=True)

    transaction.metadata["backup"] = str(
        directory
    )

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou diretório como backup."
        )


def test_register_created_rejects_absolute_path(tmp_path):
    manager = TransactionManager(tmp_path)

    target = tmp_path / "absoluto.py"

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="absoluto.py",
            content="conteudo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.register_created(
            transaction,
            str(target),
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "register_created aceitou caminho absoluto."
        )


def test_backup_file_rejects_absolute_path(tmp_path):
    manager = TransactionManager(tmp_path)

    target = tmp_path / "absoluto.py"
    target.write_text(
        "conteudo",
        encoding="utf-8",
    )

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="absoluto.py",
            content="novo",
        ),
    )

    manager.begin(transaction)

    try:
        manager.backup_file(
            transaction,
            str(target),
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "backup_file aceitou caminho absoluto."
        )


def test_safe_executor_rejects_absolute_path_inside_project(tmp_path):
    target = tmp_path / "absoluto.py"

    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path=str(target),
            content="conteudo",
        ),
    )

    try:
        executor.execute(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "SafeExecutor aceitou caminho absoluto."
        )


def test_safe_executor_rejects_parent_path(tmp_path):
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="../fora.py",
            content="conteudo",
        ),
    )

    try:
        executor.execute(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "SafeExecutor aceitou caminho fora do projeto."
        )


def test_safe_executor_rejects_symlink_outside_project(tmp_path):
    outside = tmp_path.parent / "outside_target.py"
    outside.write_text(
        "FORA\n",
        encoding="utf-8",
    )

    link = tmp_path / "link.py"
    link.symlink_to(outside)

    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="link.py",
            content="ALTERADO\n",
        ),
    )

    try:
        executor.execute(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "SafeExecutor aceitou symlink apontando para fora."
        )

    assert outside.read_text(
        encoding="utf-8"
    ) == "FORA\n"


def test_safe_executor_rejects_symlink_parent_outside_project(tmp_path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir()

    parent = tmp_path / "safe"
    parent.symlink_to(outside, target_is_directory=True)

    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="safe/arquivo.py",
            content="conteudo\n",
        ),
    )

    try:
        executor.execute(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "SafeExecutor aceitou diretório pai via symlink."
        )

    assert not (outside / "arquivo.py").exists()


def test_transaction_manager_rejects_backup_dir_outside_project(tmp_path):
    try:
        TransactionManager(
            tmp_path,
            backup_dir="../backups",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou backup_dir fora do projeto."
        )


def test_transaction_manager_rejects_absolute_backup_dir_outside_project(tmp_path):
    outside = tmp_path.parent / "absolute_backups"

    try:
        TransactionManager(
            tmp_path,
            backup_dir=str(outside),
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou backup_dir absoluto fora do projeto."
        )


def test_transaction_manager_rejects_absolute_backup_dir(tmp_path):
    outside = tmp_path.parent / "absolute_backups"

    try:
        TransactionManager(
            tmp_path,
            backup_dir=str(outside),
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou backup_dir absoluto."
        )


def test_transaction_manager_rejects_symlink_backup_dir(tmp_path):
    outside = tmp_path.parent / "outside_backups"
    outside.mkdir()

    link = tmp_path / "backup_link"
    link.symlink_to(
        outside,
        target_is_directory=True,
    )

    try:
        TransactionManager(
            tmp_path,
            backup_dir="backup_link",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "TransactionManager aceitou backup_dir via symlink."
        )


def test_full_transaction_create_and_commit(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="app.py",
            content='print("OK")\n',
        ),
    )

    manager.begin(transaction)
    manager.register_created(
        transaction,
        "app.py",
    )

    executor.execute(transaction)

    target = tmp_path / "app.py"

    assert target.exists()
    assert target.read_text(
        encoding="utf-8"
    ) == 'print("OK")\n'

    git = GitManager(tmp_path)
    result = git.commit_transaction(
        transaction.transaction_id,
        "Criar app.py",
    )

    assert result["status"] == "committed"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert transaction.transaction_id in log.stdout


def test_full_transaction_failure_rolls_back_original(tmp_path):
    target = tmp_path / "app.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content='print("ALTERADO")\n',
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "app.py",
    )

    executor.execute(transaction)

    assert target.read_text(
        encoding="utf-8",
    ) == 'print("ALTERADO")\n'

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_full_transaction_create_rollback_removes_created_file(tmp_path):
    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="novo.py",
            content='print("NOVO")\n',
        ),
    )

    manager.begin(transaction)

    manager.register_created(
        transaction,
        "novo.py",
    )

    executor.execute(transaction)

    target = tmp_path / "novo.py"

    assert target.exists()

    manager.rollback(transaction)

    assert not target.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_failed_tests_trigger_rollback(tmp_path):
    target = tmp_path / "app.py"
    original = 'print("ORIGINAL")\n'

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content='print("ALTERADO")\n',
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "app.py",
    )

    executor.execute(transaction)

    assert target.read_text(
        encoding="utf-8",
    ) == 'print("ALTERADO")\n'

    # Simula falha da etapa de testes.
    manager.rollback(transaction)

    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_failed_tests_rollback_multiple_modified_files(tmp_path):
    first = tmp_path / "one.py"
    second = tmp_path / "two.py"

    first_original = "ONE ORIGINAL\n"
    second_original = "TWO ORIGINAL\n"

    first.write_text(
        first_original,
        encoding="utf-8",
    )
    second.write_text(
        second_original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="one.py",
            content="ONE ALTERED\n",
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="two.py",
            content="TWO ALTERED\n",
        ),
    )

    manager.begin(transaction)

    manager.backup_file(transaction, "one.py")
    manager.backup_file(transaction, "two.py")

    executor.execute(transaction)

    assert first.read_text(encoding="utf-8") == "ONE ALTERED\n"
    assert second.read_text(encoding="utf-8") == "TWO ALTERED\n"

    manager.rollback(transaction)

    assert first.read_text(
        encoding="utf-8",
    ) == first_original

    assert second.read_text(
        encoding="utf-8",
    ) == second_original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_failed_create_rollback_leaves_no_created_file(tmp_path):
    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="generated.py",
            content="BROKEN\n",
        ),
    )

    manager.begin(transaction)
    manager.register_created(
        transaction,
        "generated.py",
    )

    executor.execute(transaction)

    target = tmp_path / "generated.py"

    assert target.exists()

    manager.rollback(transaction)

    assert not target.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_transaction_begin_initializes_consistent_metadata(tmp_path):
    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="app.py",
            content="conteudo\n",
        ),
    )

    result = manager.begin(transaction)

    assert result is transaction
    assert transaction.transaction_id
    assert transaction.metadata["created"] == []

    backup = Path(
        transaction.metadata["backup"]
    )

    assert backup.exists()
    assert backup.is_dir()
    assert backup.is_relative_to(tmp_path.resolve())


def test_rollback_is_idempotent(tmp_path):
    target = tmp_path / "app.py"
    original = "ORIGINAL\n"

    target.write_text(
        original,
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "app.py",
    )

    executor.execute(transaction)

    manager.rollback(transaction)

    assert target.read_text(
        encoding="utf-8",
    ) == original

    # Segundo rollback não deve corromper o arquivo.
    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(
        encoding="utf-8",
    ) == original

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rolled_back_transaction_is_not_committed(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    initial_log = subprocess.run(
        ["git", "log", "-1", "--pretty=%H"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    manager = TransactionManager(tmp_path)
    executor = SafeExecutor(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "app.py",
    )

    executor.execute(transaction)
    manager.rollback(transaction)

    assert transaction.status == TransactionStatus.ROLLED_BACK

    assert target.read_text(
        encoding="utf-8",
    ) == "ORIGINAL\n"

    # O rollback não pode deixar alteração de conteúdo
    # preparada ou não preparada para commit.
    diff = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=tmp_path,
    )

    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=tmp_path,
    )

    assert diff.returncode == 0
    assert staged_diff.returncode == 0

    # O rollback também não pode criar um novo commit.
    final_log = subprocess.run(
        ["git", "log", "-1", "--pretty=%H"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert final_log == initial_log


def test_failed_transaction_is_not_committed(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    initial_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "app.py",
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager.rollback(transaction)

    assert transaction.status == TransactionStatus.ROLLED_BACK

    assert target.read_text(
        encoding="utf-8",
    ) == "ORIGINAL\n"

    final_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert final_commit == initial_commit


def test_successful_transaction_can_be_committed(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    manager.begin(transaction)
    manager.backup_file(
        transaction,
        "app.py",
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "DevAgent: transação bem-sucedida"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "DevAgent: transação bem-sucedida" in log.stdout
    assert target.read_text(encoding="utf-8") == "ALTERADO\n"


def test_successful_transaction_commits_multiple_files_atomically(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"

    first.write_text(
        "FIRST_ORIGINAL\n",
        encoding="utf-8",
    )

    second.write_text(
        "SECOND_ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "first.py", "second.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="first.py",
            content="FIRST_NEW\n",
        ),
        Change(
            change_type=ChangeType.MODIFY,
            path="second.py",
            content="SECOND_NEW\n",
        ),
    )

    manager.begin(transaction)

    manager.backup_file(
        transaction,
        "first.py",
    )

    manager.backup_file(
        transaction,
        "second.py",
    )

    first.write_text(
        "FIRST_NEW\n",
        encoding="utf-8",
    )

    second.write_text(
        "SECOND_NEW\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "first.py", "second.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "DevAgent: múltiplos arquivos"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert first.read_text(encoding="utf-8") == "FIRST_NEW\n"
    assert second.read_text(encoding="utf-8") == "SECOND_NEW\n"

    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=tmp_path,
    )

    assert status.returncode == 0


def test_git_manager_does_not_commit_without_changes(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-empty",
        "Nenhuma alteração",
    )

    assert result["status"] != "committed"

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert len(log.stdout.strip().splitlines()) == 1


def test_git_manager_commit_contains_only_project_changes(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-only-project",
        "Alterar app.py",
    )

    assert result["status"] == "committed"

    committed_files = subprocess.run(
        ["git", "show", "--pretty=", "--name-only", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert committed_files.stdout.strip().splitlines() == ["app.py"]


def test_git_manager_commit_message_contains_transaction_id(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    transaction_id = "transaction-85"

    result = manager.commit_transaction(
        transaction_id,
        "Alterar app.py",
    )

    assert result["status"] == "committed"

    message = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert transaction_id in message.stdout


def test_git_manager_reports_commit_hash(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-87",
        "Alterar app.py",
    )

    assert result["status"] == "committed"
    assert result.get("commit") or result.get("commit_hash")


def test_git_manager_commit_hash_matches_head(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-88",
        "Alterar app.py",
    )

    assert result["status"] == "committed"

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    returned_hash = result.get("commit") or result.get("commit_hash")

    assert returned_hash == head


def test_git_manager_no_changes_does_not_create_commit(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-89",
        "Nenhuma alteração",
    )

    assert result["status"] == "no_changes"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert log.stdout.strip() == "initial"


def test_git_manager_commit_hash_is_non_empty(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-90",
        "Alterar app.py",
    )

    assert result["status"] == "committed"
    assert isinstance(result["commit_hash"], str)
    assert result["commit_hash"].strip()


def test_git_manager_commit_hash_is_valid_sha1(tmp_path):
    import re
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-91",
        "Alterar app.py",
    )

    assert re.fullmatch(
        r"[0-9a-f]{40}",
        result["commit_hash"],
    )


def test_git_manager_rejects_empty_instruction(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    try:
        GitManager(tmp_path).commit_transaction(
            "transaction-92",
            "",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou instruction vazia."
        )


def test_git_manager_rejects_empty_transaction_id(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    try:
        GitManager(tmp_path).commit_transaction(
            "",
            "Alterar app.py",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou transaction_id vazio."
        )


def test_git_manager_validates_transaction_before_git_operation(tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    try:
        manager.commit_transaction(
            "",
            "",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager executou operação com transação inválida."
        )

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert status.stdout == ""


def test_git_manager_rejects_whitespace_transaction_id(tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    try:
        manager.commit_transaction(
            "   ",
            "Alterar arquivo",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou transaction_id contendo apenas espaços."
        )


def test_git_manager_rejects_whitespace_instruction(tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    try:
        manager.commit_transaction(
            "transaction-96",
            "   ",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou instruction contendo apenas espaços."
        )


def test_git_manager_preserves_unicode_commit_message(tmp_path):
    import subprocess

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
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=tmp_path,
        check=True,
    )

    target = tmp_path / "app.py"
    target.write_text(
        "ALTERADO\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-97",
        "Alteração automática — correção segura",
    )

    assert result["status"] == "committed"

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        log.stdout.strip()
        == "DevAgent: transação transaction-97 — "
        "Alteração automática — correção segura"
    )


def test_git_manager_rejects_nonexistent_root(tmp_path):
    root = tmp_path / "nao_existe"

    try:
        GitManager(root)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou root inexistente."
        )


def test_git_manager_rejects_file_as_root(tmp_path):
    root = tmp_path / "arquivo"
    root.write_text(
        "nao e diretorio\n",
        encoding="utf-8",
    )

    try:
        GitManager(root)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou arquivo como root."
        )


def test_git_manager_accepts_valid_root(tmp_path):
    manager = GitManager(tmp_path)

    assert manager.root == tmp_path.resolve()
    assert manager.root.is_dir()


def test_git_manager_rejects_non_git_repository(tmp_path):
    manager = GitManager(tmp_path)

    try:
        manager.commit_transaction(
            "transaction-test",
            "teste",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "GitManager aceitou operação em diretório que não é repositório Git."
        )


def test_git_manager_accepts_git_repository(tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    assert manager.root == tmp_path.resolve()
    assert (tmp_path / ".git").exists()


def test_git_manager_status_clean_repository(tmp_path):
    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    manager = GitManager(tmp_path)

    assert manager.status() == ""


def test_transaction_manager_rejects_backup_symlink_during_rollback(tmp_path):
    import os

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    transaction = manager.begin(transaction)
    manager.backup_file(transaction, "app.py")

    backup_root = Path(
        transaction.metadata["backup"]
    )

    backup_file = backup_root / "app.py"

    outside = tmp_path.parent / "fora.py"
    outside.write_text(
        "NAO DEVE SER LIDO\n",
        encoding="utf-8",
    )

    backup_file.unlink()

    os.symlink(
        outside,
        backup_file,
    )

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou backup simbólico."
        )

    assert outside.read_text(
        encoding="utf-8"
    ) == "NAO DEVE SER LIDO\n"




def test_transaction_manager_rollback_rejects_created_symlink_outside_project(tmp_path):
    import os

    outside = tmp_path.parent / "fora.py"
    outside.write_text(
        "NAO TOCAR\n",
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.CREATE,
            path="criado.py",
            content="CRIADO\n",
        ),
    )

    transaction = manager.begin(transaction)

    target = tmp_path / "criado.py"

    os.symlink(
        outside,
        target,
    )

    transaction.metadata["created"].append(
        "criado.py"
    )

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou arquivo criado como symlink."
        )

    assert outside.read_text(
        encoding="utf-8"
    ) == "NAO TOCAR\n"


def test_transaction_manager_rollback_rejects_backup_symlink_during_restore(tmp_path):
    import os

    target = tmp_path / "app.py"
    target.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    manager = TransactionManager(tmp_path)

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content="ALTERADO\n",
        ),
    )

    transaction = manager.begin(transaction)
    manager.backup_file(transaction, "app.py")

    backup_root = Path(
        transaction.metadata["backup"]
    )

    backup_file = backup_root / "app.py"

    outside = tmp_path.parent / "fora_restore.py"
    outside.write_text(
        "NAO TOCAR\n",
        encoding="utf-8",
    )

    backup_file.unlink()

    os.symlink(
        outside,
        backup_file,
    )

    try:
        manager.rollback(transaction)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Rollback aceitou symlink como backup."
        )

    assert outside.read_text(
        encoding="utf-8"
    ) == "NAO TOCAR\n"


def test_git_manager_commit_transaction_does_not_commit_unrelated_changes(
    tmp_path,
):
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
    )

    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )

    tracked = tmp_path / "tracked.py"
    unrelated = tmp_path / "unrelated.py"

    tracked.write_text(
        "print('transaction')\n",
        encoding="utf-8",
    )

    unrelated.write_text(
        "print('unrelated')\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "tracked.py", "unrelated.py"],
        cwd=tmp_path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    tracked.write_text(
        "print('transaction changed')\n",
        encoding="utf-8",
    )

    unrelated.write_text(
        "print('unrelated changed')\n",
        encoding="utf-8",
    )

    manager = GitManager(tmp_path)

    result = manager.commit_transaction(
        "transaction-test",
        "alterar tracked.py",
        paths=["tracked.py"],
    )

    assert result["status"] == "committed"

    committed_files = subprocess.run(
        [
            "git",
            "show",
            "--format=",
            "--name-only",
            "HEAD",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert "tracked.py" in committed_files
    assert "unrelated.py" not in committed_files

    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "unrelated.py" in status

def test_backup_file_is_idempotent_for_same_file(tmp_path):
    manager = TransactionManager(tmp_path)

    target = tmp_path / "app.py"
    original = "ORIGINAL\n"
    altered = "ALTERADO\n"

    target.write_text(original, encoding="utf-8")

    transaction = make_transaction(
        Change(
            change_type=ChangeType.MODIFY,
            path="app.py",
            content=altered,
        ),
    )

    manager.begin(transaction)

    manager.backup_file(transaction, "app.py")

    # Simula uma segunda chamada de backup depois da alteração.
    target.write_text(altered, encoding="utf-8")
    manager.backup_file(transaction, "app.py")

    manager.rollback(transaction)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == original
    assert transaction.status == TransactionStatus.ROLLED_BACK
