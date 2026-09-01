from pathlib import Path
from types import SimpleNamespace

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
    outside = tmp_path.parent / "outside-backup"
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
