import os
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
