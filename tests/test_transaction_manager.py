import os
from core.schemas.models import Change, ChangeType
import stat
import errno
from pathlib import Path
from types import SimpleNamespace



def test_transaction_manager_copy_file_fsyncs_destination_and_parent(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"
    source.write_text("BACKUP\n", encoding="utf-8")

    manager = TransactionManager(root=str(tmp_path))

    calls = []

    original_fsync = __import__("os").fsync

    def tracking_fsync(fd):
        calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.fsync",
        tracking_fsync,
    )

    manager._copy_file_no_follow(
        tmp_path,
        Path("source.py"),
        tmp_path,
        Path("destination.py"),
    )

    assert destination.read_text(encoding="utf-8") == "BACKUP\n"
    assert len(calls) >= 2


def test_transaction_manager_copy_overwrite_is_atomic_on_fsync_failure(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"

    source.write_text("NEW\n", encoding="utf-8")
    destination.write_text("OLD\n", encoding="utf-8")

    manager = TransactionManager(root=str(tmp_path))

    original_fsync = __import__("os").fsync
    fsync_calls = {"count": 0}

    def failing_fsync(fd):
        fsync_calls["count"] += 1
        if fsync_calls["count"] == 1:
            raise OSError("simulated destination fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.fsync",
        failing_fsync,
    )

    try:
        manager._copy_file_no_follow(
            tmp_path,
            Path("source.py"),
            tmp_path,
            Path("destination.py"),
            overwrite=True,
        )
    except OSError as error:
        assert "simulated destination fsync failure" in str(error)
    else:
        raise AssertionError(
            "A falha de fsync deveria abortar a restauração."
        )

    assert destination.read_text(encoding="utf-8") == "OLD\n"


def test_transaction_manager_copy_overwrite_fsyncs_parent_after_replace(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"

    source.write_text("NEW\n", encoding="utf-8")
    destination.write_text("OLD\n", encoding="utf-8")

    manager = TransactionManager(root=str(tmp_path))

    fsync_calls = []

    original_fsync = __import__("os").fsync

    def tracking_fsync(fd):
        fsync_calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.fsync",
        tracking_fsync,
    )

    manager._copy_file_no_follow(
        tmp_path,
        Path("source.py"),
        tmp_path,
        Path("destination.py"),
        overwrite=True,
    )

    assert destination.read_text(encoding="utf-8") == "NEW\n"
    assert len(fsync_calls) >= 2


def test_transaction_manager_copy_preserves_source_mode(
    tmp_path,
):
    import os
    import stat

    from core.executor.transaction_manager import TransactionManager

    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"

    source.write_text("DATA\n", encoding="utf-8")
    os.chmod(source, 0o640)

    manager = TransactionManager(root=str(tmp_path))

    manager._copy_file_no_follow(
        tmp_path,
        Path("source.py"),
        tmp_path,
        Path("destination.py"),
    )

    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
import pytest

from core.executor.transaction_manager import TransactionManager
from core.schemas.models import TransactionStatus


def make_transaction(tmp_path):
    return SimpleNamespace(
        transaction_id=None,
        status=None,
        metadata={
            "backup": "",
            "created": [],
        },
    )


def make_started_transaction(tmp_path):
    manager = TransactionManager(
        root=tmp_path,
        backup_dir="transactions",
    )
    transaction = make_transaction(tmp_path)
    manager.begin(transaction)
    return manager, transaction


def test_init_resolves_root_and_backup(tmp_path):
    manager = TransactionManager(tmp_path, "transactions")

    assert manager.root == tmp_path.resolve()
    assert manager.backup_dir == (tmp_path / "transactions").resolve()


def test_init_rejects_backup_directory_outside_project(tmp_path):
    with pytest.raises(
        ValueError,
        match="Diretório de backup fora do projeto",
    ):
        TransactionManager(tmp_path, "../outside")


def test_safe_path_accepts_path_inside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    result = manager._safe_path("arquivo.py")

    assert result == (tmp_path / "arquivo.py").resolve()


def test_safe_path_rejects_path_outside_project(tmp_path):
    manager = TransactionManager(tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        manager._safe_path("../outside.py")


def test_begin_creates_transaction_backup_directory(tmp_path):
    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    result = manager.begin(transaction)

    assert result is transaction
    assert transaction.transaction_id
    backup = Path(transaction.metadata["backup"])
    assert backup.is_dir()
    assert backup.parent == manager.backup_dir
    assert transaction.metadata["created"] == []


def test_backup_file_returns_for_missing_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    manager.backup_file(transaction, "missing.py")

    backup = Path(transaction.metadata["backup"])
    assert list(backup.rglob("*")) == []


def test_backup_file_copies_existing_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    manager.backup_file(transaction, "arquivo.py")

    backup = (
        Path(transaction.metadata["backup"])
        / "arquivo.py"
    )
    assert backup.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_backup_file_preserves_nested_path(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "pkg" / "module.py"
    source.parent.mkdir()
    source.write_text("VALUE = 2\n", encoding="utf-8")

    manager.backup_file(transaction, "pkg/module.py")

    backup = (
        Path(transaction.metadata["backup"])
        / "pkg"
        / "module.py"
    )
    assert backup.read_text(encoding="utf-8") == "VALUE = 2\n"


def test_backup_file_rejects_absolute_path(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    absolute = tmp_path / "arquivo.py"

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        manager.backup_file(transaction, str(absolute))


def test_backup_file_rejects_path_escape(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        manager.backup_file(transaction, "../outside.py")


def test_backup_file_rejects_directory(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    (tmp_path / "pasta").mkdir()

    with pytest.raises(
        ValueError,
        match="Caminho não é um arquivo",
    ):
        manager.backup_file(transaction, "pasta")


def test_backup_file_rejects_backup_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    transaction.metadata["backup"] = str(
        tmp_path.parent / "outside"
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup fora do projeto",
    ):
        manager.backup_file(transaction, "arquivo.py")


def test_backup_file_rejects_source_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        manager.backup_file(transaction, "../arquivo.py")


def test_backup_file_does_not_overwrite_existing_backup(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\n", encoding="utf-8")

    manager.backup_file(transaction, "arquivo.py")

    source.write_text("ALTERADO\n", encoding="utf-8")
    manager.backup_file(transaction, "arquivo.py")

    backup = (
        Path(transaction.metadata["backup"])
        / "arquivo.py"
    )
    assert backup.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_register_created_records_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    manager.register_created(transaction, "novo.py")

    assert transaction.metadata["created"] == ["novo.py"]


def test_register_created_accepts_nested_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    manager.register_created(transaction, "pkg/novo.py")

    assert transaction.metadata["created"] == ["pkg/novo.py"]


def test_register_created_rejects_absolute_path(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        manager.register_created(
            transaction,
            str(tmp_path / "novo.py"),
        )


def test_register_created_rejects_path_escape(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        manager.register_created(
            transaction,
            "../outside.py",
        )


def test_register_created_rejects_directory(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    (tmp_path / "pasta").mkdir()

    with pytest.raises(
        ValueError,
        match="Caminho aponta para um diretório",
    ):
        manager.register_created(transaction, "pasta")


def test_rollback_rejects_invalid_backup_directory(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["backup"] = str(
        tmp_path / "other-backup"
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_missing_backup_directory(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup = Path(transaction.metadata["backup"])
    backup.rmdir()

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_backup_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup = Path(transaction.metadata["backup"])
    outside = tmp_path.parent / (
        f"outside-backup-{tmp_path.name}"
    )
    outside.mkdir()
    backup.rmdir()

    transaction.metadata["backup"] = str(outside)

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_rollback_removes_created_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    created = tmp_path / "novo.py"
    created.write_text("NOVO\n", encoding="utf-8")
    transaction.metadata["created"] = ["novo.py"]

    manager.rollback(transaction)

    assert not created.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_ignores_missing_created_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["created"] = ["missing.py"]

    manager.rollback(transaction)

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_rejects_absolute_created_path(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["created"] = [
        str(tmp_path / "novo.py")
    ]

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_created_path_escape(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["created"] = ["../outside.py"]

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_created_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    target = tmp_path / "real.py"
    target.write_text("REAL\n", encoding="utf-8")

    link = tmp_path / "link.py"
    link.symlink_to(target)

    transaction.metadata["created"] = ["link.py"]

    with pytest.raises(
        ValueError,
        match="Caminho criado é um symlink",
    ):
        manager.rollback(transaction)


def test_rollback_restores_backed_up_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\n", encoding="utf-8")

    manager.backup_file(transaction, "arquivo.py")

    source.write_text("ALTERADO\n", encoding="utf-8")

    manager.rollback(transaction)

    assert source.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_restores_nested_backed_up_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "pkg" / "module.py"
    source.parent.mkdir()
    source.write_text("ORIGINAL\n", encoding="utf-8")

    manager.backup_file(transaction, "pkg/module.py")

    source.write_text("ALTERADO\n", encoding="utf-8")

    manager.rollback(transaction)

    assert source.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_rollback_rejects_backup_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup = Path(transaction.metadata["backup"])
    target = tmp_path / "real.py"
    target.write_text("REAL\n", encoding="utf-8")

    link = backup / "link.py"
    link.symlink_to(target)

    with pytest.raises(
        ValueError,
        match="Backup contém symlink",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_backup_directory_entry(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    (Path(transaction.metadata["backup"]) / "nested").mkdir()

    manager.rollback(transaction)

    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_rejects_destination_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup = Path(transaction.metadata["backup"])
    backup_file = backup / "arquivo.py"
    backup_file.write_text("ORIGINAL\n", encoding="utf-8")

    real = tmp_path / "real.py"
    real.write_text("REAL\n", encoding="utf-8")

    link = tmp_path / "arquivo.py"
    link.symlink_to(real)

    with pytest.raises(
        ValueError,
        match="Destino de rollback é um symlink",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_backup_directory_escape(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup = Path(transaction.metadata["backup"])
    backup_file = backup / "arquivo.py"
    backup_file.write_text("ORIGINAL\n", encoding="utf-8")

    transaction.metadata["backup"] = str(
        tmp_path / "transactions" / ".." / "outside"
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_backup_metadata_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    expected = (
        manager.backup_dir / transaction.transaction_id
    )
    expected.mkdir(parents=True, exist_ok=True)

    transaction.metadata["backup"] = str(
        tmp_path.parent / "outside"
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_backup_file_rejects_non_file_source(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    directory = tmp_path / "diretorio"
    directory.mkdir()

    with pytest.raises(
        ValueError,
        match="Caminho não é um arquivo",
    ):
        manager.backup_file(transaction, "diretorio")


def test_rollback_rejects_invalid_backup_directory(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["backup"] = str(
        tmp_path / "transactions" / "missing"
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_backup_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    outside = tmp_path.parent / "outside-backup"
    outside.mkdir()

    transaction.metadata["backup"] = str(outside)

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.rollback(transaction)


def test_backup_file_rejects_backup_destination_symlink_escape(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    backup_root = tmp_path / "transactions" / transaction.transaction_id
    outside = tmp_path / "outside"
    outside.mkdir()

    destination_link = backup_root / "arquivo.py"
    destination_link.symlink_to(outside / "arquivo.py")

    with pytest.raises(
        ValueError,
        match="Caminho de backup inválido",
    ):
        manager.backup_file(transaction, "arquivo.py")


def test_rollback_rejects_created_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    target = tmp_path / "criado.py"
    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE\n", encoding="utf-8")

    target.symlink_to(outside)
    transaction.metadata["created"] = ["criado.py"]

    with pytest.raises(
        ValueError,
        match="Caminho criado é um symlink",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_symlink_destination(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\n", encoding="utf-8")

    manager.backup_file(transaction, "arquivo.py")

    source.unlink()

    outside = tmp_path / "outside.py"
    outside.write_text("OUTSIDE\n", encoding="utf-8")

    source.symlink_to(outside)

    with pytest.raises(
        ValueError,
        match="Destino de rollback é um symlink",
    ):
        manager.rollback(transaction)


def test_backup_blocks_parent_directory_symlink_swap(tmp_path):
    import core.executor.transaction_manager as module
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    (root / "safe.py").write_text("SAFE", encoding="utf-8")

    manager = TransactionManager(root=root)
    transaction = Transaction(transaction_id="test")
    manager.begin(transaction)

    backup_dir = root / "transactions" / transaction.transaction_id
    backup_dir_real = root / "transactions" / (
        transaction.transaction_id + "_real"
    )

    original_open = module.os.open
    swapped = False

    def hooked_open(path, flags, *args, **kwargs):
        nonlocal swapped

        candidate = Path(path)

        if (
            not swapped
            and candidate.name == "safe.py"
            and kwargs.get("dir_fd") is not None
        ):
            swapped = True
            backup_dir.rename(backup_dir_real)
            backup_dir.symlink_to(
                outside,
                target_is_directory=True,
            )

        return original_open(path, flags, *args, **kwargs)

    module.os.open = hooked_open

    try:
        manager.backup_file(transaction, "safe.py")
    finally:
        module.os.open = original_open

    assert swapped
    assert not (outside / "safe.py").exists()

    legitimate = backup_dir_real / "safe.py"
    assert legitimate.exists()
    assert legitimate.read_text(encoding="utf-8") == "SAFE"


def test_backup_blocks_ancestor_directory_symlink_swap(tmp_path):
    import core.executor.transaction_manager as module
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    (root / "safe.py").write_text("SAFE", encoding="utf-8")

    manager = TransactionManager(root=root)
    transaction = Transaction(transaction_id="test")
    manager.begin(transaction)

    transactions = root / "transactions"
    transactions_real = root / "transactions_real"

    original_open = module.os.open
    swapped = False

    def hooked_open(path, flags, *args, **kwargs):
        nonlocal swapped

        candidate = Path(path)

        if (
            not swapped
            and candidate.name == "safe.py"
            and kwargs.get("dir_fd") is not None
        ):
            swapped = True
            transactions.rename(transactions_real)
            transactions.symlink_to(
                outside,
                target_is_directory=True,
            )

        return original_open(path, flags, *args, **kwargs)

    module.os.open = hooked_open

    try:
        manager.backup_file(transaction, "safe.py")
    except Exception:
        pass
    finally:
        module.os.open = original_open

    assert swapped
    assert not (
        outside
        / transaction.transaction_id
        / "safe.py"
    ).exists()

    legitimate = (
        transactions_real
        / transaction.transaction_id
        / "safe.py"
    )
    assert legitimate.exists()
    assert legitimate.read_text(encoding="utf-8") == "SAFE"


def test_rollback_removes_identity_tracked_created_file(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)

    race_dir = tmp_path / "race"
    race_dir.mkdir()

    created = race_dir / "created.py"
    replacement = race_dir / "replacement.py"

    created.write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )
    replacement.write_text(
        "MUST_SURVIVE\n",
        encoding="utf-8",
    )

    manager.register_created(
        transaction,
        "race/created.py",
    )

    real_unlink = os.unlink
    unlink_calls = []

    def tracked_unlink(path, *args, **kwargs):
        unlink_calls.append(
            (
                path,
                kwargs.get("dir_fd"),
            )
        )
        return real_unlink(
            path,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        os,
        "unlink",
        tracked_unlink,
    )

    manager.rollback(transaction)

    assert not created.exists()
    assert replacement.read_text(
        encoding="utf-8",
    ) == "MUST_SURVIVE\n"
    assert unlink_calls
    assert unlink_calls[-1][1] is not None


def test_begin_rejects_preexisting_backup_symlink(
    tmp_path,
    monkeypatch,
):
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)

    transaction_id = "fixed-transaction-id"

    monkeypatch.setattr(
        "core.executor.transaction_manager.uuid.uuid4",
        lambda: transaction_id,
    )

    outside = tmp_path / "outside-backup-target"
    outside.mkdir()

    backup_parent = tmp_path / "transactions"
    backup_parent.mkdir()

    malicious_backup = backup_parent / transaction_id
    malicious_backup.symlink_to(
        outside,
        target_is_directory=True,
    )

    transaction = Transaction(
        transaction_id="unused",
        changes=[],
    )

    with pytest.raises(
        (ValueError, RuntimeError, OSError),
    ):
        manager.begin(transaction)

    assert outside.exists()
    assert outside.is_dir()
    assert malicious_backup.is_symlink()


def test_transaction_manifest_persists_and_restores_transaction(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(
        transaction_id="tx-manifest",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="example.txt",
                content="updated",
                reason="test",
            )
        ],
    )

    manager.begin(transaction)
    manager.backup_file(transaction, "example.txt")

    restored = manager.load_manifest(transaction.transaction_id)

    assert restored.transaction_id == transaction.transaction_id
    assert restored.status == transaction.status
    assert len(restored.changes) == 1
    assert restored.changes[0].change_type == ChangeType.MODIFY
    assert restored.changes[0].path == "example.txt"
    assert restored.metadata["backup"] == transaction.metadata["backup"]


def test_transaction_manifest_restores_created_identity(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    target = tmp_path / "created.txt"
    target.write_text("preexisting", encoding="utf-8")

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(
        transaction_id="tx-created",
        changes=[
            Change(
                change_type=ChangeType.CREATE,
                path="created.txt",
                content="new",
            )
        ],
    )

    manager.begin(transaction)
    manager.register_created(transaction, "created.txt")

    restored = manager.load_manifest(transaction.transaction_id)

    assert restored.metadata["created"] == ["created.txt"]
    assert "created.txt" in restored.metadata["created_identity"]
    assert restored.metadata["created_identity"]["created.txt"]["st_ino"] > 0


def test_transaction_manifest_lists_recoverable_transactions(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)

    first = Transaction(transaction_id="tx-one")
    second = Transaction(transaction_id="tx-two")

    manager.begin(first)
    manager.begin(second)

    recovered = manager.list_recoverable_transactions()

    assert {item.transaction_id for item in recovered} == {
        "tx-one",
        "tx-two",
    }


def test_recover_incomplete_transactions_is_idempotent(tmp_path, monkeypatch):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-idempotent")
    manager.begin(transaction)

    calls = []
    original = manager.rollback

    def track_rollback(item):
        calls.append(item.transaction_id)
        return original(item)

    monkeypatch.setattr(manager, "rollback", track_rollback)

    first = manager.recover_incomplete_transactions()
    second = manager.recover_incomplete_transactions()

    assert len(first) == 1
    assert first[0].status == TransactionStatus.ROLLED_BACK
    assert second == []
    assert calls == ["tx-idempotent"]
    assert manager.load_manifest("tx-idempotent").status == TransactionStatus.ROLLED_BACK
def test_load_manifest_rejects_corrupt_json(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-corrupt")
    manager.begin(transaction)

    manifest = manager._manifest_path(transaction.transaction_id)
    manifest.write_text("{invalid-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Manifesto de transação inválido"):
        manager.load_manifest(transaction.transaction_id)


def test_load_manifest_rejects_inconsistent_transaction_id(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-inconsistent")
    manager.begin(transaction)

    manifest = manager._manifest_path(transaction.transaction_id)
    manifest.write_text(
        '{"transaction_id": "tx-other", "status": "EXECUTING", "changes": [], "metadata": {}, "repair_state": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="transaction_id inconsistente"):
        manager.load_manifest(transaction.transaction_id)


def test_load_manifest_rejects_read_oserror(tmp_path, monkeypatch):
    from pathlib import Path
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-read-error")
    manager.begin(transaction)

    manifest = manager._manifest_path(transaction.transaction_id)
    original_read_text = Path.read_text

    def fail_read_text(self, *args, **kwargs):
        if self == manifest:
            raise OSError("simulated read failure")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(ValueError, match="Manifesto de transação inválido"):
        manager.load_manifest(transaction.transaction_id)


def test_recover_incomplete_transactions_marks_failed_when_rollback_fails(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-recovery-failure")
    manager.begin(transaction)

    def fail_rollback(item):
        raise RuntimeError("simulated rollback failure")

    monkeypatch.setattr(manager, "rollback", fail_rollback)

    recovered = manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].transaction_id == "tx-recovery-failure"
    assert recovered[0].status == TransactionStatus.FAILED
    assert recovered[0].metadata["recovery_error"] == "simulated rollback failure"

    persisted = manager.load_manifest("tx-recovery-failure")
    assert persisted.status == TransactionStatus.FAILED
    assert persisted.metadata["recovery_error"] == "simulated rollback failure"

def test_manifest_path_rejects_invalid_transaction_id(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)

    invalid_ids = [
        None,
        "",
        "   ",
        ".",
        "..",
        "tx/escape",
        "tx\\escape",
    ]

    for transaction_id in invalid_ids:
        with pytest.raises(ValueError, match="transaction_id inválido"):
            manager._manifest_path(transaction_id)


def test_deserialize_change_rejects_non_dict():
    from core.executor.transaction_manager import TransactionManager

    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        TransactionManager._deserialize_change(["invalid"])


def test_list_recoverable_transactions_returns_empty_without_backup_dir(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)

    assert manager.list_recoverable_transactions() == []


def test_list_recoverable_transactions_ignores_manifest_symlink(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    target = tmp_path / "outside.json"
    target.write_text(
        '{"transaction_id": "tx-symlink", "status": "EXECUTING", "changes": [], "metadata": {}, "repair_state": {}}',
        encoding="utf-8",
    )

    symlink = manager.backup_dir / "tx-symlink.json"

    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("symlink não suportado neste ambiente")

    assert manager.list_recoverable_transactions() == []


def test_open_parent_directory_rejects_absolute_path(tmp_path):
    from pathlib import Path
    from core.executor.transaction_manager import TransactionManager

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        TransactionManager._open_parent_directory(
            Path(tmp_path),
            Path("/absolute/file.txt"),
        )


def test_open_parent_directory_rejects_invalid_path(tmp_path):
    from pathlib import Path
    from core.executor.transaction_manager import TransactionManager

    for relative_path in (
        Path(""),
        Path("."),
        Path(".."),
        Path("dir/.."),
    ):
        with pytest.raises(ValueError, match="Caminho inválido"):
            TransactionManager._open_parent_directory(
                Path(tmp_path),
                relative_path,
            )

def test_persist_manifest_uses_pending_when_transaction_has_no_status(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import TransactionStatus

    manager = TransactionManager(root=tmp_path)

    transaction = SimpleNamespace(
        transaction_id="tx-no-status",
        changes=[],
        metadata={},
        repair_state={},
    )

    manager.persist_manifest(transaction)

    restored = manager.load_manifest("tx-no-status")

    assert restored.status == TransactionStatus.PENDING


def test_list_recoverable_transactions_ignores_empty_manifest_name(
    tmp_path,
):
    manager = TransactionManager(root=tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)
    (manager.backup_dir / ".json").write_text(
        "{}",
        encoding="utf-8",
    )

    assert manager.list_recoverable_transactions() == []


def test_list_recoverable_transactions_ignores_invalid_manifest(
    tmp_path,
):
    manager = TransactionManager(root=tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)
    (manager.backup_dir / "invalid.json").write_text(
        "{invalid",
        encoding="utf-8",
    )

    assert manager.list_recoverable_transactions() == []


def test_begin_rejects_invalid_backup_directory_on_mkdir(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)

    original_mkdir = os.mkdir

    def fail_backup_mkdir(path, *args, **kwargs):
        if path == "transactions":
            error = OSError()
            error.errno = errno.ELOOP
            raise error
        return original_mkdir(path, *args, **kwargs)

    import core.executor.transaction_manager as module

    monkeypatch.setattr(
        module.os,
        "mkdir",
        fail_backup_mkdir,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.begin(transaction)


def test_begin_rejects_backup_directory_open_error(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    original_open = os.open

    def fail_backup_open(path, flags, *args, **kwargs):
        if path == "transactions":
            raise OSError("simulated backup open failure")
        return original_open(path, flags, *args, **kwargs)

    import core.executor.transaction_manager as module

    monkeypatch.setattr(
        module.os,
        "open",
        fail_backup_open,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.begin(transaction)


def test_begin_rejects_backup_parent_that_is_not_directory(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    import core.executor.transaction_manager as module

    monkeypatch.setattr(
        module.os,
        "fstat",
        lambda fd: SimpleNamespace(st_mode=0),
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.begin(transaction)


def test_begin_rejects_existing_transaction_directory_for_unused_id(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)

    transaction = make_transaction(tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    import core.executor.transaction_manager as module

    monkeypatch.setattr(
        module.uuid,
        "uuid4",
        lambda: "unused",
    )

    original_mkdir = module.os.mkdir

    def fail_transaction_mkdir(path, *args, **kwargs):
        if path == "unused":
            raise FileExistsError("simulated existing transaction")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(
        module.os,
        "mkdir",
        fail_transaction_mkdir,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup já existe ou não é seguro",
    ):
        manager.begin(transaction)


def test_begin_rejects_transaction_directory_race(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)

    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    import core.executor.transaction_manager as module

    original_mkdir = module.os.mkdir

    def fail_transaction_mkdir(path, *args, **kwargs):
        if path == transaction.transaction_id:
            error = OSError()
            error.errno = errno.ELOOP
            raise error

        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(
        module.os,
        "mkdir",
        fail_transaction_mkdir,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup já existe ou não é seguro",
    ):
        manager.begin(transaction)


def test_open_directory_chain_rejects_invalid_component(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    with pytest.raises(
        ValueError,
        match="Caminho inválido",
    ):
        TransactionManager._open_directory_chain(
            tmp_path,
            ("..",),
        )


def test_copy_file_rejects_source_symlink(monkeypatch, tmp_path):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    source = source_root / "source.txt"
    source.write_text("content", encoding="utf-8")

    original_open = os.open

    def reject_source(*args, **kwargs):
        filename = args[0] if args else None
        if filename == "source.txt" and kwargs.get("dir_fd") is not None:
            error = OSError()
            error.errno = errno.ELOOP
            raise error
        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        reject_source,
    )

    with pytest.raises(ValueError, match="Caminho não é um arquivo regular"):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )


def test_copy_file_rejects_non_regular_source(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").mkdir()

    with pytest.raises(ValueError, match="Caminho não é um arquivo regular"):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )


def test_copy_file_overwrite_rejects_destination_directory(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").mkdir()

    with pytest.raises(ValueError, match="Caminho de destino"):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_overwrite_rejects_destination_symlink(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )

    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    (destination_root / "copy.txt").symlink_to(target)

    with pytest.raises(ValueError, match="Caminho de destino não é seguro"):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_without_overwrite_rejects_existing_destination(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "existing",
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )


def test_copy_file_without_overwrite_rejects_destination_symlink(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )

    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    (destination_root / "copy.txt").symlink_to(target)

    with pytest.raises(FileExistsError):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )


def test_copy_file_rejects_zero_byte_write(monkeypatch, tmp_path):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.write",
        lambda fd, data: 0,
    )

    with pytest.raises(
        OSError,
        match="Falha ao escrever arquivo de destino",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )


def test_copy_file_overwrite_detects_destination_removed(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "replacement",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "original",
        encoding="utf-8",
    )

    original_open = os.open
    destination_opens = 0

    def remove_destination_on_second_open(*args, **kwargs):
        nonlocal destination_opens

        filename = args[0] if args else None

        if filename == "copy.txt" and kwargs.get("dir_fd") is not None:
            destination_opens += 1
            if destination_opens == 2:
                raise FileNotFoundError("destination disappeared")

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        remove_destination_on_second_open,
    )

    with pytest.raises(
        RuntimeError,
        match="Destino foi removido durante a restauração",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_overwrite_detects_destination_symlink_race(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "replacement",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "original",
        encoding="utf-8",
    )

    original_open = os.open
    destination_opens = 0

    def symlink_race(*args, **kwargs):
        nonlocal destination_opens

        filename = args[0] if args else None

        if filename == "copy.txt" and kwargs.get("dir_fd") is not None:
            destination_opens += 1
            if destination_opens == 2:
                error = OSError()
                error.errno = errno.ELOOP
                raise error

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        symlink_race,
    )

    with pytest.raises(
        RuntimeError,
        match="Destino foi alterado para um caminho inseguro",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_overwrite_detects_destination_becoming_non_regular(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "replacement",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "original",
        encoding="utf-8",
    )

    original_open = os.open
    destination_opens = 0

    def directory_race(*args, **kwargs):
        nonlocal destination_opens

        filename = args[0] if args else None

        if filename == "copy.txt" and kwargs.get("dir_fd") is not None:
            destination_opens += 1
            if destination_opens == 2:
                return original_open(
                    destination_root,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        directory_race,
    )

    with pytest.raises(
        RuntimeError,
        match="Destino deixou de ser um arquivo regular",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_overwrite_detects_destination_identity_change(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "replacement",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "original",
        encoding="utf-8",
    )
    alternate = destination_root / "alternate.txt"
    alternate.write_text(
        "alternate",
        encoding="utf-8",
    )

    original_open = os.open
    destination_opens = 0

    def identity_race(*args, **kwargs):
        nonlocal destination_opens

        filename = args[0] if args else None

        if filename == "copy.txt" and kwargs.get("dir_fd") is not None:
            destination_opens += 1
            if destination_opens == 2:
                return original_open(
                    alternate,
                    os.O_RDONLY | os.O_NOFOLLOW,
                )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        identity_race,
    )

    with pytest.raises(
        RuntimeError,
        match="Destino foi alterado durante a restauração",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )


def test_copy_file_suppresses_missing_temporary_during_cleanup(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "replacement",
        encoding="utf-8",
    )
    (destination_root / "copy.txt").write_text(
        "original",
        encoding="utf-8",
    )

    def fail_replace(*args, **kwargs):
        raise RuntimeError("simulated replace failure")

    original_unlink = os.unlink
    unlink_calls = 0

    def missing_temporary(*args, **kwargs):
        nonlocal unlink_calls

        filename = args[0] if args else None

        if isinstance(filename, str) and ".devagent-" in filename:
            unlink_calls += 1
            raise FileNotFoundError("temporary already gone")

        return original_unlink(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.replace",
        fail_replace,
    )
    monkeypatch.setattr(
        "core.executor.transaction_manager.os.unlink",
        missing_temporary,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated replace failure",
    ):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )

    assert unlink_calls == 1

def test_persist_manifest_suppresses_temporary_cleanup_error(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)
    transaction.transaction_id = "cleanup-error"

    original_replace = os.replace
    original_unlink = Path.unlink

    def keep_temporary(*args, **kwargs):
        # Impede que o manifesto seja efetivamente substituído,
        # mantendo o arquivo temporário existente para o finally.
        return None

    def fail_unlink(self, *args, **kwargs):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.replace",
        keep_temporary,
    )
    monkeypatch.setattr(
        Path,
        "unlink",
        fail_unlink,
    )

    manager.persist_manifest(transaction)

    # Mantém as referências utilizadas para deixar explícito
    # que o monkeypatch não depende delas.
    assert original_replace is not None
    assert original_unlink is not None


def test_begin_reraises_unexpected_transaction_directory_mkdir_error(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    original_mkdir = os.mkdir

    def fail_transaction_directory(*args, **kwargs):
        name = args[0] if args else None

        if isinstance(name, str) and len(name) == 36 and name.count("-") == 4:
            raise OSError("simulated transaction mkdir failure")

        return original_mkdir(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.mkdir",
        fail_transaction_directory,
    )

    with pytest.raises(OSError, match="simulated transaction mkdir failure"):
        manager.begin(transaction)


def test_begin_reraises_unexpected_backup_transaction_directory_error(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    transaction_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        transaction_manager_module.uuid,
        "uuid4",
        lambda: transaction_id,
    )

    original_mkdir = os.mkdir
    transaction_mkdir_attempts = 0

    def fail_transaction_mkdir(*args, **kwargs):
        nonlocal transaction_mkdir_attempts

        name = args[0] if args else None

        if name == transaction_id:
            transaction_mkdir_attempts += 1

            if transaction_mkdir_attempts == 1:
                raise FileExistsError(
                    "simulated existing transaction directory"
                )

            raise OSError(
                "simulated second transaction mkdir failure"
            )

        return original_mkdir(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.mkdir",
        fail_transaction_mkdir,
    )

    with pytest.raises(
        OSError,
        match="simulated second transaction mkdir failure",
    ):
        manager.begin(transaction)

    assert transaction_mkdir_attempts == 2


def test_open_directory_chain_without_create_reraises_missing_component(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(FileNotFoundError):
        TransactionManager._open_directory_chain(
            root,
            ("missing",),
            create=False,
        )


def test_copy_file_reraises_unexpected_source_open_error(
    monkeypatch,
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text(
        "content",
        encoding="utf-8",
    )

    original_open = os.open

    def fail_source_open(*args, **kwargs):
        filename = args[0] if args else None

        if filename == "source.txt":
            error = OSError("simulated source open failure")
            error.errno = errno.EACCES
            raise error

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.open",
        fail_source_open,
    )

    with pytest.raises(OSError, match="simulated source open failure"):
        TransactionManager._copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
        )



def test_begin_rejects_transaction_backup_path_that_is_not_directory(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    transaction.transaction_id = "11111111-1111-4111-8111-111111111111"

    original_fstat = os.fstat

    def fake_fstat(fd):
        result = original_fstat(fd)

        if stat.S_ISDIR(result.st_mode):
            return SimpleNamespace(
                st_mode=stat.S_IFREG,
                st_dev=result.st_dev,
                st_ino=result.st_ino,
            )

        return result

    monkeypatch.setattr(
        transaction_manager_module.os,
        "fstat",
        fake_fstat,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.begin(transaction)


def test_copy_file_overwrite_treats_missing_destination_as_new(
    tmp_path,
):
    manager = TransactionManager(tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")

    destination = tmp_path / "destination.txt"

    manager._copy_file_no_follow(
        tmp_path,
        Path("source.txt"),
        tmp_path,
        Path("destination.txt"),
        overwrite=True,
    )

    assert destination.read_text(encoding="utf-8") == "content"


def test_copy_file_overwrite_reraises_unexpected_destination_open_error(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")

    destination = tmp_path / "destination.txt"
    destination.write_text("old", encoding="utf-8")

    original_open = os.open

    def fail_destination_open(*args, **kwargs):
        name = args[0] if args else None

        if name == "destination.txt":
            raise OSError(
                errno.EACCES,
                "simulated destination open failure",
            )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.os,
        "open",
        fail_destination_open,
    )

    with pytest.raises(
        OSError,
        match="simulated destination open failure",
    ):
        manager._copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            tmp_path,
            Path("destination.txt"),
            overwrite=True,
        )


def test_copy_file_overwrite_fails_after_temporary_name_collisions(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")

    destination = tmp_path / "destination.txt"
    destination.write_text("old", encoding="utf-8")

    original_open = os.open
    attempts = 0

    def collide_temporary_files(*args, **kwargs):
        nonlocal attempts

        name = args[0] if args else None

        if isinstance(name, str) and ".devagent-" in name:
            attempts += 1
            raise FileExistsError("simulated temporary collision")

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.os,
        "open",
        collide_temporary_files,
    )

    with pytest.raises(
        FileExistsError,
        match="Não foi possível criar arquivo temporário",
    ):
        manager._copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            tmp_path,
            Path("destination.txt"),
            overwrite=True,
        )

    assert attempts == 32


def test_copy_file_without_overwrite_rejects_destination_symlink_with_eloop(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")

    destination = tmp_path / "destination.txt"
    destination_target = tmp_path / "target.txt"
    destination_target.write_text("target", encoding="utf-8")
    destination.symlink_to(destination_target)

    original_open = os.open

    def fail_with_eloop(*args, **kwargs):
        name = args[0] if args else None

        if name == "destination.txt":
            raise OSError(
                errno.ELOOP,
                "simulated symlink",
            )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.os,
        "open",
        fail_with_eloop,
    )

    with pytest.raises(
        ValueError,
        match="Caminho de destino não é seguro",
    ):
        manager._copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            tmp_path,
            Path("destination.txt"),
            overwrite=False,
        )

def test_begin_rejects_transaction_backup_path_that_is_not_directory(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    transaction.transaction_id = "11111111-1111-4111-8111-111111111111"

    original_fstat = os.fstat
    fstat_calls = 0

    def fake_fstat(fd):
        nonlocal fstat_calls

        result = original_fstat(fd)
        fstat_calls += 1

        # O primeiro fstat valida o diretório transactions.
        # O segundo valida o diretório da transação.
        if fstat_calls == 2:
            return SimpleNamespace(
                st_mode=stat.S_IFREG,
                st_dev=result.st_dev,
                st_ino=result.st_ino,
            )

        return result

    monkeypatch.setattr(
        transaction_manager_module.os,
        "fstat",
        fake_fstat,
    )

    with pytest.raises(
        ValueError,
        match="Diretório de backup inválido",
    ):
        manager.begin(transaction)


def test_copy_file_overwrite_reraises_unexpected_current_destination_error(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager = TransactionManager(tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")

    destination = tmp_path / "destination.txt"
    destination.write_text("old", encoding="utf-8")

    original_open = os.open
    destination_opens = 0

    def fail_current_destination_open(*args, **kwargs):
        nonlocal destination_opens

        name = args[0] if args else None

        if name == "destination.txt":
            destination_opens += 1

            # Primeira abertura: captura a identidade existente.
            if destination_opens == 1:
                return original_open(*args, **kwargs)

            # Segunda abertura: valida o destino antes do replace.
            raise OSError(
                errno.EACCES,
                "simulated current destination open failure",
            )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.os,
        "open",
        fail_current_destination_open,
    )

    with pytest.raises(
        OSError,
        match="simulated current destination open failure",
    ):
        manager._copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            tmp_path,
            Path("destination.txt"),
            overwrite=True,
        )


def test_backup_file_rejects_missing_backup_metadata(
    tmp_path,
):
    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    transaction.metadata.pop("backup")

    with pytest.raises(
        ValueError,
        match="Diretório de backup não configurado",
    ):
        manager.backup_file(
            transaction,
            "file.txt",
        )


def test_backup_file_rejects_backup_path_mismatch(
    tmp_path,
):
    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    transaction.transaction_id = "11111111-1111-4111-8111-111111111111"
    transaction.metadata["backup"] = str(
        tmp_path / "transactions" / "different"
    )

    source = tmp_path / "file.txt"
    source.write_text("content", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="Caminho de backup inválido",
    ):
        manager.backup_file(
            transaction,
            "file.txt",
        )


def test_backup_file_rejects_destination_symlink(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "file.txt"
    source.write_text("content", encoding="utf-8")

    backup_dir = Path(transaction.metadata["backup"])
    destination = backup_dir / "file.txt"

    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    destination.symlink_to(target)

    original_resolve = transaction_manager_module.Path.resolve

    def preserve_destination_symlink(self, *args, **kwargs):
        if self == destination:
            return self
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.Path,
        "resolve",
        preserve_destination_symlink,
    )

    with pytest.raises(
        ValueError,
        match="Caminho de backup inválido",
    ):
        manager.backup_file(
            transaction,
            "file.txt",
        )


def test_rollback_reraises_unexpected_created_file_open_error(
    monkeypatch,
    tmp_path,
):
    import core.executor.transaction_manager as transaction_manager_module

    manager, transaction = make_started_transaction(tmp_path)

    created = tmp_path / "created.txt"
    created.write_text("created", encoding="utf-8")

    manager.register_created(transaction, "created.txt")

    original_open = os.open

    def fail_created_open(*args, **kwargs):
        name = args[0] if args else None

        if name == "created.txt":
            raise OSError(
                errno.EACCES,
                "simulated created file open failure",
            )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        transaction_manager_module.os,
        "open",
        fail_created_open,
    )

    with pytest.raises(
        OSError,
        match="simulated created file open failure",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_created_path_that_is_not_regular_file(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)

    created_dir = tmp_path / "created"
    created_dir.mkdir()

    stat_result = created_dir.stat()

    transaction.metadata["created"] = ["created"]
    transaction.metadata["created_identity"] = {
        "created": {
            "st_dev": stat_result.st_dev,
            "st_ino": stat_result.st_ino,
        }
    }

    with pytest.raises(
        ValueError,
        match="Caminho criado não é um arquivo regular",
    ):
        manager.rollback(transaction)


def test_rollback_rejects_created_file_identity_change(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)

    created = tmp_path / "created.txt"
    created.write_text("created", encoding="utf-8")

    stat_result = created.stat()

    transaction.metadata["created"] = ["created.txt"]
    transaction.metadata["created_identity"] = {
        "created.txt": {
            "st_dev": stat_result.st_dev,
            "st_ino": stat_result.st_ino + 1,
        }
    }

    with pytest.raises(
        RuntimeError,
        match="Arquivo criado foi alterado durante a transação",
    ):
        manager.rollback(transaction)

def test_list_recoverable_transactions_ignores_manifest_with_non_dict_root(
    tmp_path,
):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-root.json").write_text(
        '[{"invalid": "manifest"}]',
        encoding="utf-8",
    )

    assert manager.list_recoverable_transactions() == []


def test_list_recoverable_transactions_ignores_manifest_with_invalid_change(
    tmp_path,
):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-change.json").write_text(
        """
{
    "transaction_id": "tx-invalid-change",
    "status": "executing",
    "changes": [
        {
            "path": "missing-change-type.py"
        }
    ],
    "metadata": {},
    "repair_state": {}
}
""",
        encoding="utf-8",
    )

    assert manager.list_recoverable_transactions() == []


def test_load_manifest_rejects_non_list_changes(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-changes.json").write_text(
        """
{
    "transaction_id": "tx-invalid-changes",
    "status": "executing",
    "changes": {},
    "metadata": {},
    "repair_state": {}
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="changes"):
        manager.load_manifest("tx-invalid-changes")


def test_load_manifest_rejects_non_dict_metadata(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-metadata.json").write_text(
        """
{
    "transaction_id": "tx-invalid-metadata",
    "status": "executing",
    "changes": [],
    "metadata": [],
    "repair_state": {}
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="metadata"):
        manager.load_manifest("tx-invalid-metadata")


def test_load_manifest_rejects_non_dict_repair_state(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-repair-state.json").write_text(
        """
{
    "transaction_id": "tx-invalid-repair-state",
    "status": "executing",
    "changes": [],
    "metadata": {},
    "repair_state": []
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="repair_state"):
        manager.load_manifest("tx-invalid-repair-state")
