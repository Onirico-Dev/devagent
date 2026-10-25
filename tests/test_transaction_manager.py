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


def test_begin_preserves_backup_when_manifest_published_but_directory_fsync_fails(
    tmp_path,
    monkeypatch,
):
    import os
    import stat

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import TransactionStatus

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)
    published = {"manifest": None}

    original_replace = os.replace
    original_fsync = os.fsync

    def track_replace(source, destination):
        result = original_replace(source, destination)
        destination = Path(destination)
        if (
            destination.parent == manager.backup_dir
            and destination.suffix == ".json"
        ):
            published["manifest"] = destination
        return result

    def fail_directory_fsync_after_publication(fd):
        if (
            published["manifest"] is not None
            and stat.S_ISDIR(os.fstat(fd).st_mode)
        ):
            raise OSError("simulated post-publication directory fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(
        "core.executor.transaction_manager.os.replace",
        track_replace,
    )
    monkeypatch.setattr(
        "core.executor.transaction_manager.os.fsync",
        fail_directory_fsync_after_publication,
    )

    with pytest.raises(
        OSError,
        match="post-publication directory fsync failure",
    ):
        manager.begin(transaction)

    manifest = manager._manifest_path(transaction.transaction_id)
    backup = manager.backup_dir / transaction.transaction_id

    assert published["manifest"] == manifest
    assert manifest.is_file()
    assert backup.is_dir()

    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status == TransactionStatus.EXECUTING
    assert Path(persisted.metadata["backup"]) == backup


def test_begin_cleans_transaction_directory_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    def fail_persist(_transaction):
        raise OSError("simulated manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    with pytest.raises(OSError, match="simulated manifest persist failure"):
        manager.begin(transaction)

    assert not (
        manager.backup_dir / transaction.transaction_id
    ).exists()


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


def test_backup_file_cleans_backup_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)
    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\\n", encoding="utf-8")

    def fail_persist(_transaction):
        raise OSError("simulated manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    with pytest.raises(
        OSError,
        match="simulated manifest persist failure",
    ):
        manager.backup_file(transaction, "arquivo.py")

    backup = (
        Path(transaction.metadata["backup"])
        / "arquivo.py"
    )
    assert not backup.exists()


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


def test_register_created_restores_metadata_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)
    target = tmp_path / "novo.py"
    target.write_text("VALUE = 1\\n", encoding="utf-8")

    transaction.metadata["created"] = ["existing.py"]
    transaction.metadata["created_identity"] = {
        "existing.py": {
            "st_dev": 1,
            "st_ino": 2,
        }
    }

    created_before = list(transaction.metadata["created"])
    identity_before = dict(transaction.metadata["created_identity"])

    def fail_persist(_transaction):
        raise OSError("simulated manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    with pytest.raises(
        OSError,
        match="simulated manifest persist failure",
    ):
        manager.register_created(transaction, "novo.py")

    assert transaction.metadata["created"] == created_before
    assert transaction.metadata["created_identity"] == identity_before


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
    manager.record_created_identity(transaction, "novo.py")

    manager.rollback(transaction)

    assert not created.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK



def test_rollback_recovers_when_final_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)

    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\n", encoding="utf-8")

    manager.backup_file(transaction, "arquivo.py")
    source.write_text("ALTERADO\n", encoding="utf-8")

    def fail_persist(_transaction):
        raise OSError("simulated rollback persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    with pytest.raises(
        OSError,
        match="simulated rollback persist failure",
    ):
        manager.rollback(transaction)

    assert source.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert transaction.status == TransactionStatus.ROLLED_BACK

    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status == TransactionStatus.EXECUTING

    monkeypatch.undo()

    recovered = manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.ROLLED_BACK

    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status == TransactionStatus.ROLLED_BACK
    assert source.read_text(encoding="utf-8") == "ORIGINAL\n"


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


def test_rollback_recovers_after_partial_created_file_removal(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("FIRST\n", encoding="utf-8")
    second.write_text("SECOND\n", encoding="utf-8")

    manager.register_created(transaction, "first.py")
    manager.register_created(transaction, "second.py")

    original_unlink = manager._unlink_created_file
    calls = {"count": 0}

    def fail_on_second_unlink(
        parent_fd, relative, expected_dev, expected_ino
    ):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated partial rollback failure")
        return original_unlink(
            parent_fd, relative, expected_dev, expected_ino
        )

    monkeypatch.setattr(
        manager,
        "_unlink_created_file",
        fail_on_second_unlink,
    )

    with pytest.raises(
        OSError,
        match="simulated partial rollback failure",
    ):
        manager.rollback(transaction)

    assert not first.exists()
    assert second.exists()
    assert transaction.status != TransactionStatus.ROLLED_BACK

    monkeypatch.undo()

    manager.rollback(transaction)

    assert not first.exists()
    assert not second.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK



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


def test_rollback_recovers_after_partial_backup_restoration(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)

    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("FIRST\n", encoding="utf-8")
    second.write_text("SECOND\n", encoding="utf-8")

    manager.backup_file(transaction, "first.py")
    manager.backup_file(transaction, "second.py")

    first.write_text("CHANGED FIRST\n", encoding="utf-8")
    second.write_text("CHANGED SECOND\n", encoding="utf-8")

    original_copy = manager._copy_file_no_follow
    calls = {"count": 0}

    def fail_on_second_restore(
        source_root,
        source_relative,
        destination_root,
        destination_relative,
        overwrite=False,
    ):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated partial backup restoration failure")
        return original_copy(
            source_root,
            source_relative,
            destination_root,
            destination_relative,
            overwrite=overwrite,
        )

    monkeypatch.setattr(
        manager,
        "_copy_file_no_follow",
        fail_on_second_restore,
    )

    with pytest.raises(
        OSError,
        match="simulated partial backup restoration failure",
    ):
        manager.rollback(transaction)

    assert first.read_text(encoding="utf-8") == "FIRST\n"
    assert second.read_text(encoding="utf-8") == "CHANGED SECOND\n"
    assert transaction.status != TransactionStatus.ROLLED_BACK

    monkeypatch.undo()

    manager.rollback(transaction)

    assert first.read_text(encoding="utf-8") == "FIRST\n"
    assert second.read_text(encoding="utf-8") == "SECOND\n"
    assert transaction.status == TransactionStatus.ROLLED_BACK



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



def test_rollback_preserves_replacement_swapped_before_unlink(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    race_dir = tmp_path / "race"
    race_dir.mkdir()
    created = race_dir / "created.py"
    replacement = race_dir / "replacement.py"
    created.write_text("ORIGINAL\\n", encoding="utf-8")
    replacement.write_text("MUST_SURVIVE\\n", encoding="utf-8")
    manager.register_created(transaction, "race/created.py")

    real_unlink = manager._unlink_created_file

    def swap_before_unlink(
        parent_fd, relative, expected_dev, expected_ino
    ):
        created.unlink()
        replacement.rename(created)
        return real_unlink(
            parent_fd, relative, expected_dev, expected_ino
        )

    monkeypatch.setattr(
        manager, "_unlink_created_file", swap_before_unlink
    )
    with pytest.raises(
        RuntimeError, match="substituído durante o rollback"
    ):
        manager.rollback(transaction)

    assert created.exists()
    assert created.read_text(encoding="utf-8") == "MUST_SURVIVE\\n"
    assert not replacement.exists()

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


def test_transaction_manifest_lists_terminal_transactions(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)

    committed = Transaction(transaction_id="tx-committed")
    rolled_back = Transaction(transaction_id="tx-rolled-back")
    failed = Transaction(transaction_id="tx-failed")
    executing = Transaction(transaction_id="tx-executing")
    testing = Transaction(transaction_id="tx-testing")

    manager.begin(committed)
    manager.begin(rolled_back)
    manager.begin(failed)
    manager.begin(executing)
    manager.begin(testing)

    manager.transition(committed, TransactionStatus.COMMITTED)
    manager.persist_manifest(committed)

    manager.transition(rolled_back, TransactionStatus.ROLLED_BACK)
    manager.persist_manifest(rolled_back)

    manager.transition(failed, TransactionStatus.FAILED)
    manager.persist_manifest(failed)

    manager.transition(testing, TransactionStatus.TESTING)
    manager.persist_manifest(testing)

    terminal = manager.list_terminal_transactions()

    assert {item.transaction_id for item in terminal} == {
        "tx-committed",
        "tx-rolled-back",
        "tx-failed",
    }


def test_list_terminal_transactions_returns_empty_without_backup_dir(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)

    assert manager.list_terminal_transactions() == []


def test_list_terminal_transactions_ignores_invalid_manifest(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    manager.backup_dir.mkdir(parents=True, exist_ok=True)
    (manager.backup_dir / "invalid.json").write_text(
        "{invalid",
        encoding="utf-8",
    )

    assert manager.list_terminal_transactions() == []


def test_list_terminal_transactions_ignores_manifest_symlink(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    manager.backup_dir.mkdir(parents=True, exist_ok=True)

    target = manager.backup_dir / "real.json"
    target.write_text("{}", encoding="utf-8")

    link = manager.backup_dir / "link.json"
    link.symlink_to(target)

    assert manager.list_terminal_transactions() == []


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


def test_load_manifest_rejects_invalid_status(tmp_path):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=tmp_path)
    manifest = manager._manifest_path("tx-invalid-status")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        '{"transaction_id": "tx-invalid-status", '
        '"status": "INVALID", "changes": [], '
        '"metadata": {}, "repair_state": {}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        manager.load_manifest("tx-invalid-status")


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

    from core.executor.secure_filesystem import SecureFileSystem

    original_rename = SecureFileSystem._rename_noreplace_in_parent

    def fail_replace(parent_fd, source, destination):
        if source.endswith(".tmp") and destination == "copy.txt":
            raise RuntimeError("simulated replace failure")
        return original_rename(parent_fd, source, destination)

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
        SecureFileSystem,
        "_rename_noreplace_in_parent",
        staticmethod(fail_replace),
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


def test_rollback_preserves_preexisting_destination_after_unpublished_staging(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)

    race_dir = tmp_path / "race"
    race_dir.mkdir()

    destination = race_dir / "created.py"
    temporary = race_dir / ".created.py.tmp"

    destination.write_text("PREEXISTING", encoding="utf-8")
    temporary.write_text("STAGED", encoding="utf-8")
    staged_stat = temporary.stat()

    manager.record_staged_created_identity(
        transaction,
        "race/created.py",
        "race/.created.py.tmp",
        staged_stat.st_dev,
        staged_stat.st_ino,
    )

    # Simula a limpeza do staging após falha de publicação por conflito.
    temporary.unlink()

    manager.rollback(transaction)

    assert destination.read_text(encoding="utf-8") == "PREEXISTING"
    assert not temporary.exists()


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


def test_rollback_removes_create_published_before_directory_fsync_failure(
    tmp_path, monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    manager, transaction = make_started_transaction(tmp_path)
    transaction.changes = [
        Change(change_type=ChangeType.CREATE, path="created.txt", content="CONTENT")
    ]
    executor = SafeExecutor(tmp_path)
    calls = []

    def fail_second_directory_fsync(parent_fd):
        calls.append(parent_fd)
        if len(calls) == 2:
            raise OSError("simulated post-publication fsync failure")

    monkeypatch.setattr(
        executor, "_fsync_directory", fail_second_directory_fsync,
    )

    def on_create_prepared(change, temporary_path, device, inode):
        manager.record_staged_created_identity(
            transaction, change.path, temporary_path, device, inode,
        )

    with pytest.raises(OSError, match="post-publication fsync failure"):
        executor.execute(
            transaction,
            on_create_prepared=on_create_prepared,
        )

    target = tmp_path / "created.txt"
    assert target.read_text(encoding="utf-8") == "CONTENT"
    assert transaction.metadata["created"] == []
    assert transaction.metadata["created_identity"]["created.txt"]["temporary_path"]

    manager.rollback(transaction)

    assert not target.exists()
    assert transaction.status == TransactionStatus.ROLLED_BACK


def test_rollback_preserves_replacement_after_create_fsync_failure(
    tmp_path, monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    manager, transaction = make_started_transaction(tmp_path)
    transaction.changes = [
        Change(change_type=ChangeType.CREATE, path="created.txt", content="ORIGINAL")
    ]
    executor = SafeExecutor(tmp_path)
    calls = []

    def fail_second_directory_fsync(parent_fd):
        calls.append(parent_fd)
        if len(calls) == 2:
            raise OSError("simulated post-publication fsync failure")

    monkeypatch.setattr(
        executor, "_fsync_directory", fail_second_directory_fsync,
    )

    def on_create_prepared(change, temporary_path, device, inode):
        manager.record_staged_created_identity(
            transaction, change.path, temporary_path, device, inode,
        )

    with pytest.raises(OSError, match="post-publication fsync failure"):
        executor.execute(
            transaction,
            on_create_prepared=on_create_prepared,
        )

    target = tmp_path / "created.txt"
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("MUST_SURVIVE", encoding="utf-8")
    replacement.replace(target)

    manager.rollback(transaction)

    assert target.read_text(encoding="utf-8") == "MUST_SURVIVE"
    assert transaction.status == TransactionStatus.ROLLED_BACK

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


@pytest.mark.parametrize(
    "metadata, field",
    [
        ({"backup": 123}, "backup"),
        ({"created": {}}, "created"),
        ({"created": [123]}, "created"),
        ({"created_identity": []}, "created_identity"),
        ({"created_identity": {"file.py": []}}, "created_identity"),
        (
            {"created_identity": {"file.py": {"st_dev": "x"}}},
            "created_identity",
        ),
        (
            {"created_identity": {"file.py": {"st_ino": True}}},
            "created_identity",
        ),
    ],
)
def test_load_manifest_rejects_invalid_metadata_fields(
    tmp_path,
    metadata,
    field,
):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-metadata-field.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-invalid-metadata-field",
                "status": "executing",
                "changes": [],
                "metadata": metadata,
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=rf"metadata\.{field}",
    ):
        manager.load_manifest("tx-invalid-metadata-field")


def test_load_manifest_preserves_valid_metadata_fields(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    metadata = {
        "backup": "transactions/tx-valid-metadata",
        "created": ["created.py"],
        "created_identity": {
            "created.py": {
                "st_dev": 1,
                "st_ino": 2,
            }
        },
    }

    (backup_dir / "tx-valid-metadata.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-valid-metadata",
                "status": "executing",
                "changes": [],
                "metadata": metadata,
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    restored = manager.load_manifest("tx-valid-metadata")

    assert restored.metadata == metadata


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
def test_recover_incomplete_transactions_is_serialized_across_processes(tmp_path):
    import multiprocessing

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
        TransactionStatus,
    )

    target = tmp_path / "concurrent-recovery.py"
    target.write_text(
        'VALUE = "original"\\n',
        encoding="utf-8",
    )

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(
        transaction_id="concurrent-recovery",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="concurrent-recovery.py",
                content='VALUE = "changed"\\n',
                reason="Teste de recuperação concorrente",
            )
        ],
    )
    transaction = manager.begin(transaction)
    manager.backup_file(transaction, "concurrent-recovery.py")
    target.write_text(
        'VALUE = "changed"\\n',
        encoding="utf-8",
    )
    transaction.status = TransactionStatus.EXECUTING
    manager.persist_manifest(transaction)

    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()

    def recover_worker(root, sync_barrier, output):
        worker_manager = TransactionManager(root)
        original_list = worker_manager.list_recoverable_transactions

        def synchronized_list():
            transactions = original_list()
            sync_barrier.wait()
            return transactions

        worker_manager.list_recoverable_transactions = synchronized_list
        recovered = worker_manager.recover_incomplete_transactions()
        output.put(
            [item.transaction_id for item in recovered]
        )

    processes = [
        ctx.Process(
            target=recover_worker,
            args=(tmp_path, barrier, results),
        )
        for _ in range(2)
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    recovered_results = [
        results.get(timeout=2)
        for _ in processes
    ]

    assert sum(bool(result) for result in recovered_results) == 1
    assert target.read_text(encoding="utf-8") == 'VALUE = "original"\\n'

    final_transaction = manager.load_manifest(
        "concurrent-recovery",
    )
    assert final_transaction.status == TransactionStatus.ROLLED_BACK
    assert manager.list_recoverable_transactions() == []

def test_persist_manifest_is_serialized_across_processes(tmp_path):
    import multiprocessing
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    transaction = Transaction(transaction_id="concurrent-manifest")
    manager = TransactionManager(root=tmp_path)
    manager.begin(transaction)

    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()

    def persist_worker(root, sync_barrier, output, marker):
        worker_manager = TransactionManager(root)
        item = worker_manager.load_manifest("concurrent-manifest")
        item.metadata["worker"] = marker
        sync_barrier.wait()
        worker_manager.persist_manifest(item)
        output.put(True)

    processes = [
        ctx.Process(
            target=persist_worker,
            args=(tmp_path, barrier, results, marker),
        )
        for marker in ("a", "b")
    ]

    for process in processes:
        process.start()

    for process in processes:
        process.join(timeout=10)

    assert all(process.exitcode == 0 for process in processes)

    results_received = [
        results.get(timeout=2)
        for _ in processes
    ]

    assert results_received == [True, True]

    persisted = manager.load_manifest("concurrent-manifest")
    assert persisted.transaction_id == "concurrent-manifest"
    assert persisted.metadata["worker"] in {"a", "b"}


def test_recover_incomplete_transactions_skips_transaction_no_longer_recoverable(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)
    transaction = Transaction(transaction_id="tx-no-longer-recoverable")

    monkeypatch.setattr(
        manager,
        "list_recoverable_transactions",
        lambda: [transaction],
    )
    monkeypatch.setattr(
        manager,
        "load_manifest",
        lambda _transaction_id: Transaction(
            transaction_id="tx-no-longer-recoverable",
            status=TransactionStatus.PENDING,
        ),
    )

    recovered = manager.recover_incomplete_transactions()

    assert recovered == []


def test_begin_suppresses_backup_cleanup_error_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(tmp_path)
    transaction = make_transaction(tmp_path)

    def fail_persist(_transaction):
        raise OSError("simulated manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    def fail_backup_rmdir(_path):
        raise OSError("simulated backup cleanup failure")

    monkeypatch.setattr(Path, "rmdir", fail_backup_rmdir)

    with pytest.raises(OSError, match="simulated manifest persist failure"):
        manager.begin(transaction)


def test_backup_file_suppresses_destination_cleanup_error_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager

    manager, transaction = make_started_transaction(tmp_path)
    source = tmp_path / "arquivo.py"
    source.write_text("ORIGINAL\n", encoding="utf-8")

    backup = Path(transaction.metadata["backup"])
    destination = backup / "arquivo.py"

    def fail_persist(_transaction):
        raise OSError("simulated manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    original_unlink = Path.unlink

    def fail_destination_unlink(path, *args, **kwargs):
        if path == destination:
            raise OSError("simulated destination cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_destination_unlink)

    with pytest.raises(OSError, match="simulated manifest persist failure"):
        manager.backup_file(transaction, "arquivo.py")

    assert destination.exists()


def test_recover_incomplete_transactions_releases_lock_on_unhandled_error(
    tmp_path,
    monkeypatch,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-lock-release")
    manager.begin(transaction)

    def fail_recovery(*_args):
        raise RuntimeError("simulated recovery failure")

    monkeypatch.setattr(manager, "_recover_transaction", fail_recovery)

    with pytest.raises(RuntimeError, match="simulated recovery failure"):
        manager.recover_incomplete_transactions()

    lock = manager._recovery_lock("tx-lock-release")
    try:
        assert lock is not None
    finally:
        import fcntl

        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_recover_incomplete_transactions_commits_when_commit_detector_finds_commit(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)
    transaction = Transaction(transaction_id="tx-recovery-commit")
    manager.begin(transaction)

    result = {
        "status": "committed",
        "commit_hash": "abc123",
        "transaction_id": "tx-recovery-commit",
    }

    calls = []

    def commit_detector(transaction_id):
        calls.append(transaction_id)
        return result

    recovered = manager.recover_incomplete_transactions(
        commit_detector=commit_detector,
    )

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.COMMITTED
    assert recovered[0].metadata["recovery_git"] == result
    assert calls == ["tx-recovery-commit"]

    persisted = manager.load_manifest("tx-recovery-commit")
    assert persisted.status == TransactionStatus.COMMITTED
    assert persisted.metadata["recovery_git"] == result


def test_recovery_rejects_commit_detector_result_without_committed_status(tmp_path):
    import pytest

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)
    transaction = Transaction(transaction_id="tx-invalid-commit-evidence")
    manager.begin(transaction)

    result = {
        "status": "error",
        "transaction_id": transaction.transaction_id,
        "commit_hash": None,
    }

    with pytest.raises(ValueError, match="evidência de commit inválida"):
        manager.recover_incomplete_transactions(
            commit_detector=lambda _transaction_id: result,
        )

    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status == TransactionStatus.EXECUTING
    assert persisted.metadata.get("recovery") is not True



def test_recovery_rejects_commit_evidence_with_wrong_id_or_empty_hash(tmp_path):
    import pytest

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    invalid_results = [
        (
            "wrong-id",
            {
                "status": "committed",
                "transaction_id": "different-transaction",
                "commit_hash": "abc123",
            },
        ),
        (
            "empty-hash",
            {
                "status": "committed",
                "transaction_id": "tx-empty-hash",
                "commit_hash": "   ",
            },
        ),
    ]

    for case_name, result in invalid_results:
        root = tmp_path / case_name
        root.mkdir()
        manager = TransactionManager(root)
        transaction_id = (
            "tx-wrong-id" if case_name == "wrong-id" else "tx-empty-hash"
        )
        transaction = Transaction(transaction_id=transaction_id)
        manager.begin(transaction)

        with pytest.raises(ValueError, match="evidência de commit inválida"):
            manager.recover_incomplete_transactions(
                commit_detector=lambda _transaction_id, result=result: result,
            )

        persisted = manager.load_manifest(transaction_id)
        assert persisted.status == TransactionStatus.EXECUTING
        assert persisted.metadata.get("recovery") is not True

def test_recover_incomplete_transactions_rolls_back_when_commit_detector_returns_none(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)
    transaction = Transaction(transaction_id="tx-recovery-no-commit")
    manager.begin(transaction)

    calls = []

    def commit_detector(transaction_id):
        calls.append(transaction_id)
        return None

    recovered = manager.recover_incomplete_transactions(
        commit_detector=commit_detector,
    )

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    assert calls == ["tx-recovery-no-commit"]

def test_recover_incomplete_transactions_skips_after_recovery_guard(
    tmp_path,
    monkeypatch,
):
    from contextlib import nullcontext

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)

    transaction = Transaction(
        transaction_id="tx-guard-race",
        status=TransactionStatus.EXECUTING,
    )

    states = iter(
        [
            Transaction(
                transaction_id="tx-guard-race",
                status=TransactionStatus.EXECUTING,
            ),
            Transaction(
                transaction_id="tx-guard-race",
                status=TransactionStatus.COMMITTED,
            ),
        ]
    )

    monkeypatch.setattr(
        manager,
        "list_recoverable_transactions",
        lambda: [transaction],
    )
    monkeypatch.setattr(
        manager,
        "load_manifest",
        lambda _transaction_id: next(states),
    )

    recovered = manager.recover_incomplete_transactions(
        recovery_guard=lambda _transaction: nullcontext(),
    )

    assert recovered == []

def test_recover_incomplete_transactions_recovers_after_recovery_guard(
    tmp_path,
    monkeypatch,
):
    from contextlib import nullcontext

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(tmp_path)

    transaction = Transaction(
        transaction_id="tx-guard-recover",
        status=TransactionStatus.EXECUTING,
    )

    monkeypatch.setattr(
        manager,
        "list_recoverable_transactions",
        lambda: [transaction],
    )
    monkeypatch.setattr(
        manager,
        "load_manifest",
        lambda _transaction_id: transaction,
    )
    monkeypatch.setattr(
        manager,
        "_recover_transaction",
        lambda current, commit_detector: current,
    )

    recovered = manager.recover_incomplete_transactions(
        recovery_guard=lambda _transaction: nullcontext(),
    )

    assert recovered == [transaction]

@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [
        (TransactionStatus.PENDING, TransactionStatus.TESTING),
        (TransactionStatus.PENDING, TransactionStatus.COMMITTED),
        (TransactionStatus.PENDING, TransactionStatus.ROLLED_BACK),
        (TransactionStatus.PENDING, TransactionStatus.FAILED),
        (TransactionStatus.EXECUTING, TransactionStatus.PENDING),
        (TransactionStatus.TESTING, TransactionStatus.PENDING),
        (TransactionStatus.TESTING, TransactionStatus.EXECUTING),
        (TransactionStatus.FAILED, TransactionStatus.PENDING),
        (TransactionStatus.FAILED, TransactionStatus.EXECUTING),
        (TransactionStatus.FAILED, TransactionStatus.TESTING),
        (TransactionStatus.FAILED, TransactionStatus.COMMITTED),
        (TransactionStatus.COMMITTED, TransactionStatus.PENDING),
        (TransactionStatus.COMMITTED, TransactionStatus.EXECUTING),
        (TransactionStatus.COMMITTED, TransactionStatus.TESTING),
        (TransactionStatus.COMMITTED, TransactionStatus.ROLLED_BACK),
        (TransactionStatus.COMMITTED, TransactionStatus.FAILED),
        (TransactionStatus.ROLLED_BACK, TransactionStatus.PENDING),
        (TransactionStatus.ROLLED_BACK, TransactionStatus.EXECUTING),
        (TransactionStatus.ROLLED_BACK, TransactionStatus.TESTING),
        (TransactionStatus.ROLLED_BACK, TransactionStatus.COMMITTED),
        (TransactionStatus.ROLLED_BACK, TransactionStatus.FAILED),
    ],
)
def test_transaction_manager_rejects_invalid_state_transitions(
    tmp_path,
    current_status,
    new_status,
):
    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)
    transaction.status = current_status

    with pytest.raises(ValueError, match="Transição de estado inválida"):
        manager.transition(transaction, new_status)

    assert transaction.status == current_status

@pytest.mark.parametrize(
    "invalid_path",
    [None, 123, [], {}],
)
def test_deserialize_change_rejects_non_string_path(invalid_path):
    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        TransactionManager._deserialize_change(
            {
                "change_type": ChangeType.MODIFY.value,
                "path": invalid_path,
            }
        )


def test_deserialize_change_rejects_non_string_content():
    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        TransactionManager._deserialize_change(
            {
                "change_type": ChangeType.MODIFY.value,
                "path": "app.py",
                "content": 123,
            }
        )


@pytest.mark.parametrize("invalid_reason", [None, 123, [], {}])
def test_deserialize_change_rejects_non_string_reason(invalid_reason):
    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        TransactionManager._deserialize_change(
            {
                "change_type": ChangeType.MODIFY.value,
                "path": "app.py",
                "reason": invalid_reason,
            }
        )


@pytest.mark.parametrize(
    "invalid_status",
    [None, 123, [], {}, "status-inexistente"],
)
def test_load_manifest_rejects_invalid_status(tmp_path, invalid_status):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-status.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-invalid-status",
                "status": invalid_status,
                "changes": [],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        manager.load_manifest("tx-invalid-status")


@pytest.mark.parametrize(
    "status",
    [
        TransactionStatus.PENDING,
        TransactionStatus.EXECUTING,
        TransactionStatus.TESTING,
        TransactionStatus.COMMITTED,
        TransactionStatus.ROLLED_BACK,
        TransactionStatus.FAILED,
    ],
)
def test_load_manifest_preserves_valid_status(tmp_path, status):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-valid-status.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-valid-status",
                "status": status.value,
                "changes": [],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    restored = manager.load_manifest("tx-valid-status")

    assert restored.status is status


@pytest.mark.parametrize(
    "change_type",
    [
        ChangeType.CREATE,
        ChangeType.MODIFY,
        ChangeType.DELETE,
    ],
)
def test_deserialize_change_preserves_valid_change_type(change_type):
    result = TransactionManager._deserialize_change(
        {
            "change_type": change_type.value,
            "path": "app.py",
        }
    )

    assert result.change_type is change_type


@pytest.mark.parametrize(
    "invalid_change_type",
    [None, 123, [], {}, "invalid"],
)
def test_deserialize_change_rejects_invalid_change_type(
    invalid_change_type,
):
    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        TransactionManager._deserialize_change(
            {
                "change_type": invalid_change_type,
                "path": "app.py",
            }
        )


@pytest.mark.parametrize(
    "invalid_path",
    [
        "/absolute/path.py",
        "../escape.py",
        "nested/../../escape.py",
        "./../escape.py",
    ],
)
def test_load_manifest_rejects_unsafe_change_path(tmp_path, invalid_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-unsafe-path.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-unsafe-path",
                "status": TransactionStatus.EXECUTING.value,
                "changes": [
                    {
                        "change_type": ChangeType.MODIFY.value,
                        "path": invalid_path,
                    }
                ],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        manager.load_manifest("tx-unsafe-path")


def test_load_manifest_rejects_symlink_change_path(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    outside = tmp_path.parent / "manifest-outside"
    outside.mkdir(exist_ok=True)

    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)

    (backup_dir / "tx-symlink-path.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-symlink-path",
                "status": TransactionStatus.EXECUTING.value,
                "changes": [
                    {
                        "change_type": ChangeType.MODIFY.value,
                        "path": "linked/escape.py",
                    }
                ],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Caminho fora do projeto"):
        manager.load_manifest("tx-symlink-path")

@pytest.mark.parametrize(
    "invalid_transaction_id",
    [None, 123, [], {}, ""],
)
def test_load_manifest_rejects_invalid_transaction_id_field(
    tmp_path,
    invalid_transaction_id,
):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-id-field.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": invalid_transaction_id,
                "status": TransactionStatus.EXECUTING.value,
                "changes": [],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="transaction_id inconsistente"):
        manager.load_manifest("tx-invalid-id-field")


@pytest.mark.parametrize(
    "invalid_changes_item",
    [None, 123, [], "invalid"],
)
def test_load_manifest_rejects_invalid_change_entries(
    tmp_path,
    invalid_changes_item,
):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-invalid-change-entry.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-invalid-change-entry",
                "status": TransactionStatus.EXECUTING.value,
                "changes": [invalid_changes_item],
                "metadata": {},
                "repair_state": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Change inválido no manifesto"):
        manager.load_manifest("tx-invalid-change-entry")


def test_load_manifest_preserves_valid_change_fields(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_dir = tmp_path / "transactions"
    backup_dir.mkdir(parents=True)

    (backup_dir / "tx-valid-change.json").write_text(
        __import__("json").dumps(
            {
                "transaction_id": "tx-valid-change",
                "status": TransactionStatus.EXECUTING.value,
                "changes": [
                    {
                        "change_type": ChangeType.MODIFY.value,
                        "path": "app.py",
                        "content": "print('ok')\n",
                        "reason": "teste de persistência",
                    }
                ],
                "metadata": {"source": "test"},
                "repair_state": {"attempts": 1},
            }
        ),
        encoding="utf-8",
    )

    transaction = manager.load_manifest("tx-valid-change")

    assert transaction.transaction_id == "tx-valid-change"
    assert transaction.status is TransactionStatus.EXECUTING
    assert len(transaction.changes) == 1
    assert transaction.changes[0].change_type is ChangeType.MODIFY
    assert transaction.changes[0].path == "app.py"
    assert transaction.changes[0].content == "print('ok')\n"
    assert transaction.changes[0].reason == "teste de persistência"
    assert transaction.metadata == {"source": "test"}
    assert transaction.repair_state == {"attempts": 1}

def test_rollback_rejects_ancestor_directory_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    backup_root = Path(transaction.metadata["backup"])
    backup_nested = backup_root / "nested"
    backup_nested.mkdir()
    (backup_nested / "arquivo.py").write_text(
        "ORIGINAL\n",
        encoding="utf-8",
    )

    outside = tmp_path / "outside"
    outside.mkdir()

    destination_nested = tmp_path / "nested"
    destination_nested.symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(
        ValueError,
        match="Caminho de diretório não é seguro: nested",
    ):
        manager.rollback(transaction)

    assert not (outside / "arquivo.py").exists()


def test_record_created_identity_restores_metadata_when_manifest_persist_fails(
    tmp_path,
    monkeypatch,
):
    manager, transaction = make_started_transaction(tmp_path)
    target = tmp_path / "novo.py"
    target.write_text("NOVO\n", encoding="utf-8")

    transaction.metadata["created_identity"] = {
        "existing.py": {
            "st_dev": 1,
            "st_ino": 2,
        }
    }
    identity_before = dict(transaction.metadata["created_identity"])

    def fail_persist(_transaction):
        raise OSError("simulated identity manifest persist failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)

    with pytest.raises(
        OSError,
        match="simulated identity manifest persist failure",
    ):
        manager.record_created_identity(transaction, "novo.py")

    assert transaction.metadata["created_identity"] == identity_before


def test_record_created_identity_rejects_symlink(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    target = tmp_path / "real.py"
    target.write_text("REAL\n", encoding="utf-8")

    link = tmp_path / "link.py"
    link.symlink_to(target)

    with pytest.raises(
        ValueError,
        match="Caminho criado é um symlink",
    ):
        manager.record_created_identity(transaction, "link.py")


def test_validate_created_identity_rejects_missing_created_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    transaction.metadata["created_identity"] = {
        "novo.py": {
            "st_dev": 1,
            "st_ino": 2,
        }
    }

    with pytest.raises(
        RuntimeError,
        match="Arquivo criado não existe durante a transação",
    ):
        manager.validate_created_identity(transaction, "novo.py")


def test_validate_created_identity_rejects_missing_registered_identity(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    target = tmp_path / "novo.py"
    target.write_text("NOVO\n", encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="Identidade do arquivo criado não foi registrada",
    ):
        manager.validate_created_identity(transaction, "novo.py")

def test_validate_manifest_rejects_non_string_created_identity_key(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    data = {
        "transaction_id": transaction.transaction_id,
        "changes": [],
        "metadata": {
            "created_identity": {
                123: {
                    "st_dev": 1,
                    "st_ino": 2,
                }
            }
        },
        "repair_state": {},
    }

    with pytest.raises(
        ValueError,
        match="metadata.created_identity",
    ):
        manager._validate_manifest_data(data, transaction.transaction_id)

def test_list_terminal_transactions_ignores_empty_transaction_id_manifest(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager

    manager = TransactionManager(root=str(tmp_path))
    manager.backup_dir.mkdir(parents=True, exist_ok=True)
    (manager.backup_dir / ".json").write_text("{}", encoding="utf-8")

    assert manager.list_terminal_transactions() == []

def test_create_backup_directory_continues_after_unrelated_mkdir_oserror(
    tmp_path,
    monkeypatch,
):
    manager = TransactionManager(root=tmp_path)
    backup_name = "transactions"

    (tmp_path / backup_name).mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )

    original_mkdir = os.mkdir

    def fail_backup_mkdir(path, *args, **kwargs):
        if path == backup_name:
            error = OSError()
            error.errno = errno.EACCES
            raise error
        return original_mkdir(path, *args, **kwargs)

    import core.executor.transaction_manager as module

    monkeypatch.setattr(
        module.os,
        "mkdir",
        fail_backup_mkdir,
    )

    try:
        backup_parent_fd = manager._create_backup_directory(
            parent_fd,
            backup_name,
        )
        os.close(backup_parent_fd)
    finally:
        os.close(parent_fd)


def test_record_created_identity_normalizes_path_key_to_string(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)

    target = tmp_path / "novo.py"
    target.write_text("NOVO\n", encoding="utf-8")

    transaction.metadata["created_identity"] = {
        "novo.py": {
            "st_dev": 1,
            "st_ino": 2,
        },
    }

    manager.record_created_identity(transaction, "novo.py")

    assert "novo.py" in transaction.metadata["created_identity"]
    assert all(
        isinstance(key, str)
        for key in transaction.metadata["created_identity"]
    )
    assert len(transaction.metadata["created_identity"]) == 1
    assert transaction.metadata["created_identity"]["novo.py"]["st_ino"] > 0


def test_transition_returns_same_transaction_when_status_is_unchanged(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)

    result = manager.transition(
        transaction,
        TransactionStatus.EXECUTING,
    )

    assert result is transaction
    assert transaction.status is TransactionStatus.EXECUTING


def test_record_created_identity_ignores_missing_file(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)

    manager.record_created_identity(transaction, "nao-existe.py")

    assert transaction.metadata.get("created_identity", {}) == {}


def test_recovery_error_manifest_persistence_failure_releases_lock(
    tmp_path, monkeypatch
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-recovery-persist-failure")
    manager.begin(transaction)

    original_rollback = manager.rollback
    original_persist = manager.persist_manifest
    calls = {"rollback": 0}

    def fail_rollback_once(item):
        calls["rollback"] += 1
        if calls["rollback"] == 1:
            raise RuntimeError("simulated rollback failure")
        return original_rollback(item)

    def fail_recovery_persist(item):
        if item.metadata.get("recovery_error"):
            raise OSError("simulated recovery manifest failure")
        return original_persist(item)

    monkeypatch.setattr(manager, "rollback", fail_rollback_once)
    monkeypatch.setattr(manager, "persist_manifest", fail_recovery_persist)

    with pytest.raises(OSError, match="simulated recovery manifest failure"):
        manager.recover_incomplete_transactions()

    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status in (
        TransactionStatus.EXECUTING,
        TransactionStatus.TESTING,
    )
    assert "recovery_error" not in persisted.metadata

    monkeypatch.setattr(manager, "persist_manifest", original_persist)

    recovered = manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    assert calls["rollback"] == 2
    assert manager.load_manifest(transaction.transaction_id).status == (
        TransactionStatus.ROLLED_BACK
    )


def test_recovery_retries_after_commit_detector_failure(tmp_path):
    import pytest

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-detector-retry")
    manager.begin(transaction)

    def fail_detector(_transaction_id):
        raise RuntimeError("simulated git inspection failure")

    with pytest.raises(RuntimeError, match="simulated git inspection failure"):
        manager.recover_incomplete_transactions(
            commit_detector=fail_detector,
        )

    persisted = manager.load_manifest("tx-detector-retry")
    assert persisted.status == TransactionStatus.EXECUTING
    assert persisted.metadata.get("recovery") is not True

    recovered = manager.recover_incomplete_transactions(
        commit_detector=lambda _transaction_id: None,
    )

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    assert manager.load_manifest(
        "tx-detector-retry"
    ).status == TransactionStatus.ROLLED_BACK

def test_recovery_continues_after_failure_and_preserves_first_transaction(
    tmp_path, monkeypatch,
):
    import pytest
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    first = Transaction(transaction_id="tx-recovery-first-fails")
    second = Transaction(transaction_id="tx-recovery-second-succeeds")
    manager.begin(first)
    manager.begin(second)

    monkeypatch.setattr(
        manager, "list_recoverable_transactions", lambda: [first, second]
    )
    original_recover = manager._recover_transaction
    calls = []
    failure = RuntimeError("first transaction recovery failed")

    def recover_in_order(current, commit_detector):
        calls.append(current.transaction_id)
        if current.transaction_id == first.transaction_id:
            raise failure
        return original_recover(current, commit_detector)

    monkeypatch.setattr(manager, "_recover_transaction", recover_in_order)

    with pytest.raises(
        RuntimeError, match="first transaction recovery failed"
    ) as exc:
        manager.recover_incomplete_transactions()

    assert exc.value is failure
    assert calls == [first.transaction_id, second.transaction_id]
    persisted_first = manager.load_manifest(first.transaction_id)
    persisted_second = manager.load_manifest(second.transaction_id)
    assert persisted_first.status == TransactionStatus.EXECUTING
    assert persisted_first.metadata.get("recovery") is not True
    assert persisted_second.status == TransactionStatus.ROLLED_BACK


def test_recovery_propagates_first_exception_after_all_attempts(
    tmp_path, monkeypatch,
):
    import pytest
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    first = Transaction(transaction_id="tx-recovery-error-one")
    second = Transaction(transaction_id="tx-recovery-error-two")
    manager.begin(first)
    manager.begin(second)

    monkeypatch.setattr(
        manager, "list_recoverable_transactions", lambda: [first, second]
    )
    first_error = RuntimeError("first recovery exception")
    second_error = ValueError("second recovery exception")
    calls = []

    def fail_each(current, _commit_detector):
        calls.append(current.transaction_id)
        if current.transaction_id == first.transaction_id:
            raise first_error
        raise second_error

    monkeypatch.setattr(manager, "_recover_transaction", fail_each)

    with pytest.raises(RuntimeError, match="first recovery exception") as exc:
        manager.recover_incomplete_transactions()

    assert exc.value is first_error
    assert calls == [first.transaction_id, second.transaction_id]


def test_recovery_exposes_created_file_without_persisted_identity(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction, TransactionStatus

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-missing-created-identity")
    manager.begin(transaction)
    manager.register_created(transaction, "novo.py")

    # Simula a queda após criar o arquivo, mas antes de persistir sua identidade.
    created = tmp_path / "novo.py"
    created.write_text("VALUE = 1\n", encoding="utf-8")

    restarted_manager = TransactionManager(root=tmp_path)
    recovered = restarted_manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.FAILED
    assert "Identidade do arquivo criado não foi registrada" in (
        recovered[0].metadata["recovery_error"]
    )
    assert created.read_text(encoding="utf-8") == "VALUE = 1\n"

def test_recovery_retries_manifest_persist_after_rollback_completed(
    tmp_path, monkeypatch
):
    from core.schemas.models import TransactionStatus

    manager, transaction = make_started_transaction(tmp_path)
    original_persist = manager.persist_manifest
    failed_once = {"value": False}

    def fail_once_after_rollback(item):
        if (
            item.status == TransactionStatus.ROLLED_BACK
            and not failed_once["value"]
        ):
            failed_once["value"] = True
            raise OSError("simulated final rollback manifest failure")
        return original_persist(item)

    monkeypatch.setattr(manager, "persist_manifest", fail_once_after_rollback)

    recovered = manager.recover_incomplete_transactions()

    assert failed_once["value"] is True
    assert len(recovered) == 1
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    persisted = manager.load_manifest(transaction.transaction_id)
    assert persisted.status == TransactionStatus.ROLLED_BACK


def test_rollback_preserves_quarantine_when_restore_collides(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    created = tmp_path / "created.py"
    created.write_text("ORIGINAL\n", encoding="utf-8")
    original_stat = created.stat()

    parent_fd = os.open(
        tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    real_rename = manager._rename_noreplace_in_parent
    calls = {"count": 0}

    def fail_restore_on_collision(fd, source, destination):
        calls["count"] += 1
        if calls["count"] == 2:
            created.write_text("MUST_SURVIVE\n", encoding="utf-8")
        return real_rename(fd, source, destination)

    monkeypatch.setattr(
        manager, "_rename_noreplace_in_parent", fail_restore_on_collision
    )
    try:
        with pytest.raises(
            RuntimeError, match="substituído durante o rollback"
        ):
            manager._unlink_created_file(
                parent_fd,
                Path("created.py"),
                original_stat.st_dev,
                original_stat.st_ino + 1,
            )
    finally:
        os.close(parent_fd)

    assert calls["count"] == 2
    assert created.read_text(encoding="utf-8") == "MUST_SURVIVE\n"
    quarantined = list(tmp_path.glob(".devagent-rollback-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "ORIGINAL\n"



def test_backup_file_uses_configured_backup_directory(tmp_path):
    from pathlib import Path

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Transaction

    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.txt").write_text("original", encoding="utf-8")

    manager = TransactionManager(
        root=root,
        backup_dir="state/transactions",
    )
    transaction = Transaction(transaction_id="custom-backup-test")

    manager.begin(transaction)
    manager.backup_file(transaction, "sample.txt")

    backup = Path(transaction.metadata["backup"]) / "sample.txt"
    assert backup.read_text(encoding="utf-8") == "original"
    assert backup.is_relative_to(root / "state" / "transactions")


@pytest.mark.parametrize("damage", ["missing", "truncated", "altered"])
def test_rollback_rejects_missing_or_corrupted_backup(
    tmp_path, damage
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import (
        Change,
        ChangeType,
        Transaction,
        TransactionStatus,
    )

    manager = TransactionManager(root=tmp_path)
    original = tmp_path / "original.py"
    original.write_text("ORIGINAL CONTENT\n", encoding="utf-8")

    transaction = Transaction(
        transaction_id=f"tx-backup-integrity-{damage}",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="original.py",
                content="ALTERED CONTENT\n",
            )
        ],
    )
    manager.begin(transaction)
    manager.backup_file(transaction, "original.py")

    backup = Path(transaction.metadata["backup"]) / "original.py"
    original.write_text("ALTERED CONTENT\n", encoding="utf-8")

    if damage == "missing":
        backup.unlink()
    elif damage == "truncated":
        backup.write_bytes(b"")
    else:
        backup.write_text("TAMPERED CONTENT\n", encoding="utf-8")

    with pytest.raises(ValueError):
        manager.rollback(transaction)

    assert original.read_text(encoding="utf-8") == "ALTERED CONTENT\n"
    assert transaction.status != TransactionStatus.ROLLED_BACK


@pytest.mark.parametrize(
    "relative_path",
    ["pkg/../outside.py", "../outside.py"],
)
def test_backup_file_rejects_parent_traversal(tmp_path, relative_path):
    manager, transaction = make_started_transaction(tmp_path)

    with pytest.raises(ValueError, match="Caminho fora do projeto"):
        manager.backup_file(transaction, relative_path)


def test_backup_file_rejects_malformed_existing_integrity_record(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = {
        "missing.py": {"size": -1, "sha256": "invalid"}
    }

    with pytest.raises(ValueError, match="Registro de integridade inválido"):
        manager.backup_file(transaction, "missing.py")


def test_rollback_requires_backup_when_legacy_execution_count_is_positive(
    tmp_path,
):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    manager = TransactionManager(root=tmp_path)
    target = tmp_path / "target.py"
    target.write_text("alterado", encoding="utf-8")

    transaction = Transaction(
        transaction_id="tx-legacy-positive-count",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="target.py",
                content="original",
            )
        ],
    )
    manager.begin(transaction)
    transaction.metadata["execution"] = {"changes_applied": 1}

    with pytest.raises(
        ValueError, match="Backup obrigatório ausente ou sem registro"
    ):
        manager.rollback(transaction)

    assert target.read_text(encoding="utf-8") == "alterado"


@pytest.mark.parametrize("invalid_count", [True, -1, 2, "1"])
def test_rollback_rejects_invalid_execution_count(tmp_path, invalid_count):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(
        transaction_id=f"tx-invalid-count-{str(invalid_count)}",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="target.py",
                content="original",
            )
        ],
    )
    manager.begin(transaction)
    transaction.metadata["execution"] = {
        "phase": "executing",
        "changes_applied": invalid_count,
    }

    with pytest.raises(ValueError, match="Contador de alterações aplicadas"):
        manager.rollback(transaction)


def test_rollback_testing_phase_requires_all_change_backups(tmp_path):
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    manager = TransactionManager(root=tmp_path)
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first original", encoding="utf-8")
    second.write_text("second altered", encoding="utf-8")

    transaction = Transaction(
        transaction_id="tx-testing-requires-all-backups",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="first.py",
                content="first altered",
            ),
            Change(
                change_type=ChangeType.MODIFY,
                path="second.py",
                content="second original",
            ),
        ],
    )
    manager.begin(transaction)
    manager.backup_file(transaction, "first.py")
    transaction.metadata["execution"] = {
        "phase": "testing",
        "changes_applied": 2,
    }

    with pytest.raises(
        ValueError, match="Backup obrigatório ausente ou sem registro"
    ):
        manager.rollback(transaction)

    assert first.read_text(encoding="utf-8") == "first original"
    assert second.read_text(encoding="utf-8") == "second altered"

def test_backup_file_rejects_existing_backup_without_integrity_record(
    tmp_path,
):
    from pathlib import Path

    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import Change, ChangeType, Transaction

    manager = TransactionManager(root=tmp_path)
    target = tmp_path / "target.py"
    target.write_text("original source\\n", encoding="utf-8")

    transaction = Transaction(
        transaction_id="tx-orphan-backup-no-integrity-record",
        changes=[
            Change(
                change_type=ChangeType.MODIFY,
                path="target.py",
                content="modified source\\n",
            )
        ],
    )
    manager.begin(transaction)

    backup = Path(transaction.metadata["backup"]) / "target.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("unverified backup\\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match="Backup existente sem registro de integridade"
    ):
        manager.backup_file(transaction, "target.py")

    assert backup.read_text(encoding="utf-8") == "unverified backup\\n"
    assert "target.py" not in transaction.metadata["backup_integrity"]
    assert target.read_text(encoding="utf-8") == "original source\\n"


def test_restart_recovers_after_partial_created_file_removal(
    tmp_path, monkeypatch
):
    import pytest
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import TransactionStatus

    manager, transaction = make_started_transaction(tmp_path)
    first = tmp_path / "restart-first.py"
    second = tmp_path / "restart-second.py"
    first.write_text("FIRST\n", encoding="utf-8")
    second.write_text("SECOND\n", encoding="utf-8")
    manager.register_created(transaction, "restart-first.py")
    manager.register_created(transaction, "restart-second.py")

    original_unlink = manager._unlink_created_file
    calls = {"count": 0}

    def fail_on_second_unlink(parent_fd, relative, expected_dev, expected_ino):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated failure before restart")
        return original_unlink(parent_fd, relative, expected_dev, expected_ino)

    monkeypatch.setattr(manager, "_unlink_created_file", fail_on_second_unlink)
    with pytest.raises(OSError, match="simulated failure before restart"):
        manager.rollback(transaction)

    assert not first.exists()
    assert second.exists()
    transaction_id = transaction.transaction_id
    monkeypatch.undo()

    restarted_manager = TransactionManager(root=tmp_path)
    recovered = restarted_manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].transaction_id == transaction_id
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    assert not first.exists()
    assert not second.exists()
    assert restarted_manager.load_manifest(transaction_id).status == (
        TransactionStatus.ROLLED_BACK
    )


def test_restart_recovers_after_partial_backup_restoration(
    tmp_path, monkeypatch
):
    import pytest
    from core.executor.transaction_manager import TransactionManager
    from core.schemas.models import TransactionStatus

    manager, transaction = make_started_transaction(tmp_path)
    first = tmp_path / "restart-original-first.py"
    second = tmp_path / "restart-original-second.py"
    first.write_text("ORIGINAL FIRST\n", encoding="utf-8")
    second.write_text("ORIGINAL SECOND\n", encoding="utf-8")
    manager.backup_file(transaction, "restart-original-first.py")
    manager.backup_file(transaction, "restart-original-second.py")
    first.write_text("CHANGED FIRST\n", encoding="utf-8")
    second.write_text("CHANGED SECOND\n", encoding="utf-8")

    original_copy = manager._copy_file_no_follow
    calls = {"count": 0}

    def fail_on_second_restore(
        source_root, source_relative, destination_root,
        destination_relative, overwrite=False,
    ):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated restore failure before restart")
        return original_copy(
            source_root, source_relative, destination_root,
            destination_relative, overwrite=overwrite,
        )

    monkeypatch.setattr(manager, "_copy_file_no_follow", fail_on_second_restore)
    with pytest.raises(OSError, match="simulated restore failure before restart"):
        manager.rollback(transaction)

    assert first.read_text(encoding="utf-8") == "ORIGINAL FIRST\n"
    assert second.read_text(encoding="utf-8") == "CHANGED SECOND\n"
    transaction_id = transaction.transaction_id
    monkeypatch.undo()

    restarted_manager = TransactionManager(root=tmp_path)
    recovered = restarted_manager.recover_incomplete_transactions()

    assert len(recovered) == 1
    assert recovered[0].transaction_id == transaction_id
    assert recovered[0].status == TransactionStatus.ROLLED_BACK
    assert first.read_text(encoding="utf-8") == "ORIGINAL FIRST\n"
    assert second.read_text(encoding="utf-8") == "ORIGINAL SECOND\n"
    assert restarted_manager.load_manifest(transaction_id).status == (
        TransactionStatus.ROLLED_BACK
    )



def test_coverage_validate_backup_path_rejects_non_pathlike(tmp_path):
    manager = TransactionManager(root=tmp_path)

    class NotPathLike:
        def __str__(self):
            return "valid-looking-name"

    with pytest.raises(ValueError, match="Caminho inválido"):
        manager._validate_backup_path(NotPathLike())


@pytest.mark.parametrize("path", ["", ".", "bad\x00name"])
def test_coverage_validate_backup_path_rejects_empty_dot_and_nul(
    tmp_path, path
):
    manager = TransactionManager(root=tmp_path)
    with pytest.raises(ValueError, match="Caminho inválido"):
        manager._validate_backup_path(path)


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {},
        {"size": True, "sha256": "a" * 64},
        {"size": -1, "sha256": "a" * 64},
        {"size": 0, "sha256": "A" * 64},
        {"size": 0, "sha256": "a" * 63},
        {"size": 0, "sha256": "a" * 64, "extra": 1},
    ],
)
def test_coverage_invalid_backup_fingerprints_are_rejected(tmp_path, record):
    manager = TransactionManager(root=tmp_path)
    assert manager._is_valid_backup_fingerprint(record) is False


def test_coverage_fingerprint_rejects_non_regular_file(tmp_path):
    manager = TransactionManager(root=tmp_path)
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    with pytest.raises(ValueError, match="não é um arquivo regular"):
        manager._fingerprint_backup(directory)


def test_coverage_backup_file_rejects_non_dict_integrity_records(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = []
    with pytest.raises(ValueError, match="Registros de integridade"):
        manager.backup_file(transaction, "missing.py")


def test_coverage_backup_file_reuses_absent_file_record(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = {
        "missing.py": {"exists": False}
    }
    manager.backup_file(transaction, "missing.py")
    assert transaction.metadata["backup_integrity"]["missing.py"] == {
        "exists": False
    }


def test_coverage_backup_file_rolls_back_absent_record_on_persist_failure(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)

    def fail_persist(_transaction):
        raise OSError("injected absent-record persistence failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)
    with pytest.raises(OSError, match="absent-record persistence failure"):
        manager.backup_file(transaction, "missing.py")
    assert "missing.py" not in transaction.metadata["backup_integrity"]


def test_coverage_backup_file_preserves_valid_record_after_source_disappears(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)
    source = tmp_path / "present.py"
    source.write_text("original", encoding="utf-8")
    manager.backup_file(transaction, "present.py")
    source.unlink()

    expected = transaction.metadata["backup_integrity"]["present.py"]
    manager.backup_file(transaction, "present.py")
    assert transaction.metadata["backup_integrity"]["present.py"] == expected


def test_coverage_validate_backup_integrity_rejects_non_dict_records(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = []
    with pytest.raises(ValueError, match="Registros de integridade"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_validate_backup_integrity_rejects_non_dict_execution(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["execution"] = []
    with pytest.raises(ValueError, match="Metadados de execução inválidos"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_validate_backup_integrity_rejects_unknown_phase(tmp_path):
    from core.schemas.models import Change, ChangeType

    manager, transaction = make_started_transaction(tmp_path)
    transaction.changes = [
        Change(change_type=ChangeType.CREATE, path="new.py", content="x")
    ]
    transaction.metadata["execution"] = {
        "phase": "unknown-phase",
        "changes_applied": 0,
    }
    with pytest.raises(ValueError, match="Fase de execução inválida"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_validate_backup_integrity_rejects_preparing_contradiction(
    tmp_path,
):
    from core.schemas.models import Change, ChangeType

    manager, transaction = make_started_transaction(tmp_path)
    transaction.changes = [
        Change(change_type=ChangeType.CREATE, path="new.py", content="x")
    ]
    transaction.metadata["execution"] = {
        "phase": "preparing",
        "changes_applied": 1,
    }
    with pytest.raises(ValueError, match="preparação com alterações aplicadas"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_validate_backup_integrity_rejects_invalid_created_registry(
    tmp_path,
):
    from core.schemas.models import Change, ChangeType

    manager, transaction = make_started_transaction(tmp_path)
    transaction.changes = [
        Change(change_type=ChangeType.CREATE, path="new.py", content="x")
    ]
    transaction.metadata["execution"] = {
        "phase": "executing",
        "changes_applied": 1,
    }
    transaction.metadata["created"] = "not-a-list"
    with pytest.raises(ValueError, match="Registro de arquivos criados inválido"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_validate_backup_integrity_rejects_malformed_fingerprint(
    tmp_path,
):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = {
        "sample.py": {"size": -1, "sha256": "invalid"}
    }
    with pytest.raises(ValueError, match="Registro de integridade inválido"):
        manager._validate_backup_integrity(
            transaction, Path(transaction.metadata["backup"])
        )


def test_coverage_record_staged_identity_rejects_different_parent(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    with pytest.raises(ValueError, match="Temporário deve estar no diretório"):
        manager.record_staged_created_identity(
            transaction, "dir/target.py", "other/temp.py", 1, 2
        )


def test_coverage_record_staged_identity_restores_previous_metadata(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    transaction.metadata["created_identity"] = {
        "target.py": {"st_dev": 11, "st_ino": 22}
    }

    def fail_persist(_transaction):
        raise OSError("injected identity persistence failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)
    with pytest.raises(OSError, match="identity persistence failure"):
        manager.record_staged_created_identity(
            transaction, "target.py", ".target.py.tmp", 33, 44
        )
    assert transaction.metadata["created_identity"]["target.py"] == {
        "st_dev": 11, "st_ino": 22
    }


def test_coverage_record_staged_identity_removes_new_metadata_on_failure(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)

    def fail_persist(_transaction):
        raise OSError("injected new identity persistence failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)
    with pytest.raises(OSError, match="new identity persistence failure"):
        manager.record_staged_created_identity(
            transaction, "target.py", ".target.py.tmp", 33, 44
        )
    assert "target.py" not in transaction.metadata["created_identity"]


def test_coverage_backup_source_symlink_resolving_outside_project(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-coverage.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape-coverage.txt"
    link.symlink_to(outside)

    try:
        with pytest.raises(ValueError, match="Caminho fora do projeto"):
            manager.backup_file(transaction, link.name)
    finally:
        link.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def test_coverage_validate_backup_integrity_defaults_none_metadata(tmp_path):
    manager = TransactionManager(root=tmp_path, backup_dir="transactions")
    transaction = make_transaction(tmp_path)
    transaction.metadata["backup_integrity"] = None
    transaction.metadata["execution"] = None
    backup_root = tmp_path / "backup-root"
    backup_root.mkdir()

    manager._validate_backup_integrity(transaction, backup_root)


def test_coverage_backup_file_rejects_directory_at_destination(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    (tmp_path / "target-coverage.py").write_text("source", encoding="utf-8")
    backup_dir = manager._resolve_transaction_backup_directory(transaction)
    (backup_dir / "target-coverage.py").mkdir()

    with pytest.raises(ValueError, match="Backup não é um arquivo regular"):
        manager.backup_file(transaction, "target-coverage.py")


def test_coverage_backup_file_detects_changed_existing_backup(tmp_path):
    manager, transaction = make_started_transaction(tmp_path)
    (tmp_path / "changed-backup-coverage.py").write_text(
        "original", encoding="utf-8"
    )
    manager.backup_file(transaction, "changed-backup-coverage.py")
    backup = (
        manager._resolve_transaction_backup_directory(transaction)
        / "changed-backup-coverage.py"
    )
    backup.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="Integridade do backup comprometida"):
        manager.backup_file(transaction, "changed-backup-coverage.py")


def test_coverage_backup_file_rejects_non_dict_copy_fingerprint(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    (tmp_path / "bad-fingerprint-coverage.py").write_text(
        "source", encoding="utf-8"
    )
    monkeypatch.setattr(manager, "_copy_file_no_follow", lambda *_args: "invalid")

    with pytest.raises(RuntimeError, match="não retornou a integridade"):
        manager.backup_file(transaction, "bad-fingerprint-coverage.py")


def test_coverage_backup_file_handles_manifest_read_error_and_cleans_copy(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    (tmp_path / "manifest-read-coverage.py").write_text(
        "source", encoding="utf-8"
    )

    def fail_persist(_transaction):
        raise OSError("simulated persist failure")

    def fail_read(_manifest):
        raise ValueError("simulated manifest read failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)
    monkeypatch.setattr(manager, "_read_manifest_data", fail_read)

    with pytest.raises(OSError, match="simulated persist failure"):
        manager.backup_file(transaction, "manifest-read-coverage.py")

    backup = (
        manager._resolve_transaction_backup_directory(transaction)
        / "manifest-read-coverage.py"
    )
    assert not backup.exists()
    assert "manifest-read-coverage.py" not in transaction.metadata["backup_integrity"]


def test_coverage_backup_file_restores_previous_record_after_persist_failure(
    tmp_path, monkeypatch
):
    manager, transaction = make_started_transaction(tmp_path)
    (tmp_path / "previous-record-coverage.py").write_text(
        "source", encoding="utf-8"
    )
    records = transaction.metadata.setdefault("backup_integrity", {})
    previous = {"previous": "record"}
    records["previous-record-coverage.py"] = previous

    def fail_persist(_transaction):
        raise OSError("simulated persist failure")

    def fail_read(_manifest):
        raise ValueError("simulated manifest read failure")

    monkeypatch.setattr(manager, "persist_manifest", fail_persist)
    monkeypatch.setattr(manager, "_read_manifest_data", fail_read)

    with pytest.raises(OSError, match="simulated persist failure"):
        manager.backup_file(transaction, "previous-record-coverage.py")

    assert records["previous-record-coverage.py"] == previous
    backup = (
        manager._resolve_transaction_backup_directory(transaction)
        / "previous-record-coverage.py"
    )
    assert not backup.exists()


def test_coverage_rename_noreplace_reports_unavailable_syscall(monkeypatch):
    import ctypes
    import errno

    monkeypatch.setattr(ctypes, "CDLL", lambda *_args, **_kwargs: object())

    with pytest.raises(OSError) as exc_info:
        TransactionManager._rename_noreplace_in_parent(
            -1, b"source", b"destination"
        )

    assert exc_info.value.errno == errno.ENOSYS


def test_coverage_remove_created_files_rejects_temporary_in_other_directory(
    tmp_path, monkeypatch
):
    manager = TransactionManager(root=tmp_path)
    transaction = make_transaction(tmp_path)
    transaction.metadata["created_identity"] = {
        "target-coverage.txt": {
            "temporary_path": "subdir/temp-coverage.txt"
        }
    }

    monkeypatch.setattr(
        manager, "_get_created_file_identity", lambda *_args: (10, 20)
    )
    monkeypatch.setattr(manager, "_remove_created_file", lambda **_kwargs: None)

    with pytest.raises(ValueError, match="Temporário registrado fora"):
        manager._remove_created_files(transaction)


def test_coverage_restore_backup_files_rejects_symlink(tmp_path):
    manager = TransactionManager(root=tmp_path)
    backup_root = tmp_path / "backup-symlink-coverage"
    backup_root.mkdir()
    outside = tmp_path / "outside-symlink-coverage.txt"
    outside.write_text("content", encoding="utf-8")
    (backup_root / "linked.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="Backup contém symlink"):
        manager._restore_backup_files(backup_root)


def test_coverage_recovery_records_unlock_and_close_errors(
    tmp_path, monkeypatch
):
    import fcntl
    from core.schemas.models import Transaction

    manager = TransactionManager(root=tmp_path)
    transaction = Transaction(transaction_id="tx-coverage-lock-errors")
    manager.begin(transaction)

    class FailingLock:
        def fileno(self):
            return 123

        def close(self):
            raise OSError("simulated close failure")

    lock = FailingLock()
    monkeypatch.setattr(manager, "_recovery_lock", lambda *_args: lock)
    monkeypatch.setattr(
        manager, "_recover_transaction", lambda current, *_args: current
    )

    original_flock = fcntl.flock

    def fail_unlock(fd, operation):
        if operation == fcntl.LOCK_UN:
            raise OSError("simulated unlock failure")
        return original_flock(fd, operation)

    monkeypatch.setattr(
        "core.executor.transaction_manager.fcntl.flock", fail_unlock
    )

    with pytest.raises(OSError, match="simulated unlock failure"):
        manager.recover_incomplete_transactions()
