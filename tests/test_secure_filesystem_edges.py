import errno
import os
import stat
from pathlib import Path

import pytest

from core.executor.secure_filesystem import SecureFileSystem


def test_open_directory_chain_rejects_invalid_part(tmp_path):
    (tmp_path / "ok").mkdir()

    with pytest.raises(ValueError):
        SecureFileSystem.open_directory_chain(
            tmp_path,
            ("ok", ".."),
        )


def test_open_directory_chain_creates_missing_directories(tmp_path):
    fd = SecureFileSystem.open_directory_chain(
        tmp_path,
        ("a", "b"),
        create=True,
    )
    try:
        assert (tmp_path / "a" / "b").is_dir()
    finally:
        os.close(fd)


def test_open_directory_chain_closes_fd_on_error(tmp_path):
    original_open = os.open

    def failing_open(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            raise OSError("falha")
        return original_open(path, flags, *args, **kwargs)

    with pytest.raises(OSError):
        SecureFileSystem.open_directory_chain(
            tmp_path,
            ("a",),
        )


def test_open_parent_directory_rejects_absolute_path(tmp_path):
    with pytest.raises(ValueError):
        SecureFileSystem.open_parent_directory(
            tmp_path,
            tmp_path / "arquivo.txt",
        )


@pytest.mark.parametrize("path", [".", "..", ""])
def test_open_parent_directory_rejects_invalid_final_part(tmp_path, path):
    with pytest.raises(ValueError):
        SecureFileSystem.open_parent_directory(
            tmp_path,
            path,
        )


def test_open_source_file_reraises_non_eloop_error(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(PermissionError):
        SecureFileSystem._open_source_file(
            1,
            Path("arquivo.txt"),
        )


def test_expected_destination_reraises_unexpected_error(monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(PermissionError):
        SecureFileSystem._get_expected_destination_identity(
            1,
            Path("destino.txt"),
        )


def test_expected_destination_rejects_non_regular_file(tmp_path):
    directory = tmp_path / "destino"
    directory.mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    try:
        with pytest.raises(ValueError):
            SecureFileSystem._get_expected_destination_identity(
                parent_fd,
                Path("destino"),
            )
    finally:
        os.close(parent_fd)


def test_temporary_destination_retries_collision(monkeypatch, tmp_path):
    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    calls = {"count": 0}

    real_open = os.open

    def collision_then_success(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd == parent_fd:
            calls["count"] += 1
            if calls["count"] == 1:
                raise FileExistsError
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", collision_then_success)

    try:
        fd, name = SecureFileSystem._create_temporary_destination(
            parent_fd,
            Path("destino.txt"),
            0o644,
        )
        os.close(fd)
        os.unlink(name, dir_fd=parent_fd)
        assert calls["count"] >= 2
    finally:
        os.close(parent_fd)


def test_temporary_destination_fails_after_all_collisions(
    monkeypatch,
    tmp_path,
):
    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )

    monkeypatch.setattr(
        os,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FileExistsError
        ),
    )

    try:
        with pytest.raises(FileExistsError):
            SecureFileSystem._create_temporary_destination(
                parent_fd,
                Path("destino.txt"),
                0o644,
            )
    finally:
        os.close(parent_fd)


def test_open_destination_file_reraises_non_eloop_error(monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(PermissionError):
        SecureFileSystem._open_destination_file(
            1,
            Path("destino.txt"),
            0o644,
            False,
        )


def test_copy_contents_rejects_zero_write(monkeypatch):
    monkeypatch.setattr(os, "read", lambda fd, size: b"dados")
    monkeypatch.setattr(os, "write", lambda fd, data: 0)

    with pytest.raises(OSError, match="Falha ao escrever"):
        SecureFileSystem._copy_file_contents(1, 2)


def test_verify_destination_missing_after_existing(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(os, "open", missing)

    with pytest.raises(RuntimeError, match="removido"):
        SecureFileSystem._verify_overwrite_destination(
            1,
            Path("destino.txt"),
            (1, 2),
        )


def test_verify_destination_rejects_unsafe_path(monkeypatch):
    error = OSError(errno.ELOOP, "symlink")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(RuntimeError, match="inseguro"):
        SecureFileSystem._verify_overwrite_destination(
            1,
            Path("destino.txt"),
            None,
        )


def test_verify_destination_rejects_non_regular_file(tmp_path):
    directory = tmp_path / "destino"
    directory.mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    try:
        with pytest.raises(RuntimeError, match="arquivo regular"):
            SecureFileSystem._verify_overwrite_destination(
                parent_fd,
                Path("destino"),
                None,
            )
    finally:
        os.close(parent_fd)


def test_verify_destination_detects_identity_change(tmp_path):
    target = tmp_path / "destino.txt"
    target.write_text("novo", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    try:
        with pytest.raises(RuntimeError, match="alterado"):
            SecureFileSystem._verify_overwrite_destination(
                parent_fd,
                Path("destino.txt"),
                (999999, 999999),
            )
    finally:
        os.close(parent_fd)


def test_copy_rejects_non_regular_source(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    destination = tmp_path / "dest"
    destination.mkdir()

    with pytest.raises(ValueError, match="arquivo regular"):
        SecureFileSystem.copy_file_no_follow(
            tmp_path,
            Path("source"),
            tmp_path,
            Path("destino.txt"),
        )


def test_copy_cleanup_removes_temporary_file_on_failure(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "source.txt"
    source.write_text("conteudo", encoding="utf-8")

    destination_dir = tmp_path / "destination"
    destination_dir.mkdir()

    original_copy = SecureFileSystem._copy_file_contents

    def fail_copy(source_fd, destination_fd):
        raise RuntimeError("falha durante cópia")

    monkeypatch.setattr(
        SecureFileSystem,
        "_copy_file_contents",
        fail_copy,
    )

    with pytest.raises(RuntimeError, match="falha durante cópia"):
        SecureFileSystem.copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            destination_dir,
            Path("destino.txt"),
            overwrite=True,
        )

    assert list(destination_dir.glob("*.tmp")) == []


def test_copy_cleanup_ignores_missing_temporary_file(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "source.txt"
    source.write_text("conteudo", encoding="utf-8")

    destination_dir = tmp_path / "destination"
    destination_dir.mkdir()

    original_unlink = os.unlink

    def unlink_missing(path, *args, **kwargs):
        if isinstance(path, str) and ".devagent-" in path:
            raise FileNotFoundError
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink_missing)

    monkeypatch.setattr(
        SecureFileSystem,
        "_copy_file_contents",
        lambda source_fd, destination_fd: (_ for _ in ()).throw(
            RuntimeError("forçar cleanup")
        ),
    )

    with pytest.raises(RuntimeError, match="forçar cleanup"):
        SecureFileSystem.copy_file_no_follow(
            tmp_path,
            Path("source.txt"),
            destination_dir,
            Path("destino.txt"),
            overwrite=True,
        )


def test_fsync_directory_delegates_to_os(monkeypatch):
    called = []

    monkeypatch.setattr(
        os,
        "fsync",
        lambda fd: called.append(fd),
    )

    SecureFileSystem.fsync_directory(123)

    assert called == [123]


def test_expected_destination_eisdir_is_rejected(monkeypatch):
    error = OSError(errno.EISDIR, "directory")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(ValueError, match="destino não é seguro"):
        SecureFileSystem._get_expected_destination_identity(
            1,
            Path("destino.txt"),
        )


def test_open_source_file_eloop_is_rejected(monkeypatch):
    error = OSError(errno.ELOOP, "symlink")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(ValueError, match="arquivo regular"):
        SecureFileSystem._open_source_file(
            1,
            Path("origem.txt"),
        )


def test_open_destination_file_eloop_is_rejected(monkeypatch):
    error = OSError(errno.ELOOP, "symlink")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(ValueError, match="destino não é seguro"):
        SecureFileSystem._open_destination_file(
            1,
            Path("destino.txt"),
            0o644,
            False,
        )


def test_verify_destination_eisdir_is_rejected(monkeypatch):
    error = OSError(errno.EISDIR, "directory")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(RuntimeError, match="inseguro"):
        SecureFileSystem._verify_overwrite_destination(
            1,
            Path("destino.txt"),
            None,
        )


def test_verify_destination_reraises_unexpected_error(monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(PermissionError):
        SecureFileSystem._verify_overwrite_destination(
            1,
            Path("destino.txt"),
            None,
        )


def test_open_destination_file_rejects_eisdir(monkeypatch):
    error = OSError(errno.EISDIR, "directory")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(OSError):
        SecureFileSystem._open_destination_file(
            1,
            Path("destino.txt"),
            0o644,
            False,
        )


def test_verify_destination_detects_removed_destination_without_identity(
    monkeypatch,
):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(os, "open", missing)

    SecureFileSystem._verify_overwrite_destination(
        1,
        Path("destino.txt"),
        None,
    )


def test_verify_destination_identity_matches(tmp_path):
    target = tmp_path / "destino.txt"
    target.write_text("conteudo", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY,
    )

    try:
        info = os.stat(target)
        SecureFileSystem._verify_overwrite_destination(
            parent_fd,
            Path("destino.txt"),
            (info.st_dev, info.st_ino),
        )
    finally:
        os.close(parent_fd)


def test_copy_file_no_follow_without_overwrite(tmp_path):
    source = tmp_path / "origem.txt"
    destination = tmp_path / "destino.txt"

    source.write_text("conteudo", encoding="utf-8")

    SecureFileSystem.copy_file_no_follow(
        tmp_path,
        Path("origem.txt"),
        tmp_path,
        Path("destino.txt"),
    )

    assert destination.read_text(encoding="utf-8") == "conteudo"




def test_open_destination_file_rejects_unexpected_os_error(
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(os, "open", fail)

    with pytest.raises(PermissionError):
        SecureFileSystem._open_destination_file(
            1,
            Path("destino.txt"),
            0o644,
            False,
        )


def test_copy_file_no_follow_rejects_non_regular_source(
    tmp_path,
):
    source = tmp_path / "origem"
    source.mkdir()

    destination = tmp_path / "destino"
    destination.mkdir()

    with pytest.raises(ValueError, match="arquivo regular"):
        SecureFileSystem.copy_file_no_follow(
            tmp_path,
            Path("origem"),
            destination,
            Path("arquivo.txt"),
        )

def test_copy_file_no_follow_overwrite_existing_destination(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"

    source.mkdir()
    destination.mkdir()

    source_file = source / "arquivo.txt"
    destination_file = destination / "arquivo.txt"

    source_file.write_text("novo conteúdo")
    destination_file.write_text("conteúdo antigo")

    SecureFileSystem.copy_file_no_follow(
        source,
        Path("arquivo.txt"),
        destination,
        Path("arquivo.txt"),
        overwrite=True,
    )

    assert destination_file.read_text() == "novo conteúdo"


def test_copy_file_no_follow_overwrite_missing_destination(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"

    source.mkdir()
    destination.mkdir()

    source_file = source / "arquivo.txt"
    source_file.write_text("novo conteúdo")

    SecureFileSystem.copy_file_no_follow(
        source,
        Path("arquivo.txt"),
        destination,
        Path("arquivo.txt"),
        overwrite=True,
    )

    assert (destination / "arquivo.txt").read_text() == "novo conteúdo"


def test_copy_overwrite_preserves_destination_replaced_after_verification(
    tmp_path, monkeypatch
):
    from core.executor.secure_filesystem import SecureFileSystem

    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text("BACKUP", encoding="utf-8")
    destination = destination_root / "copy.txt"
    destination.write_text("ORIGINAL", encoding="utf-8")

    original_replace = SecureFileSystem._replace_temporary_destination

    def replace_after_race(
        cls,
        destination_parent_fd,
        destination_relative,
        temporary_name,
        expected_destination_identity,
    ):
        destination.unlink()
        destination.write_text("MUST_SURVIVE", encoding="utf-8")
        return original_replace(
            destination_parent_fd,
            destination_relative,
            temporary_name,
            expected_destination_identity,
        )

    monkeypatch.setattr(
        SecureFileSystem,
        "_replace_temporary_destination",
        classmethod(replace_after_race),
    )

    try:
        with pytest.raises(RuntimeError, match="substituído"):
            SecureFileSystem.copy_file_no_follow(
                source_root,
                Path("source.txt"),
                destination_root,
                Path("copy.txt"),
                overwrite=True,
            )
    finally:
        content = destination.read_text(encoding="utf-8") if destination.exists() else None

    assert content == "MUST_SURVIVE", (
        "A restauração sobrescreveu uma substituição concorrente; "
        f"conteúdo final: {content!r}"
    )


def test_copy_overwrite_restores_original_when_publication_fails(
    tmp_path, monkeypatch
):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text("NEW", encoding="utf-8")
    destination = destination_root / "copy.txt"
    destination.write_text("ORIGINAL", encoding="utf-8")

    original_rename = SecureFileSystem._rename_noreplace_in_parent

    def fail_publication(parent_fd, source, target):
        if (
            target == "copy.txt"
            and "quarantine" not in source
            and ".devagent-" in source
        ):
            raise OSError(5, "falha injetada na publicação")
        return original_rename(parent_fd, source, target)

    monkeypatch.setattr(
        SecureFileSystem,
        "_rename_noreplace_in_parent",
        staticmethod(fail_publication),
    )

    with pytest.raises(OSError, match="falha injetada"):
        SecureFileSystem.copy_file_no_follow(
            source_root,
            Path("source.txt"),
            destination_root,
            Path("copy.txt"),
            overwrite=True,
        )

    assert destination.read_text(encoding="utf-8") == "ORIGINAL"
    assert not list(destination_root.glob(".*.devagent-quarantine-*"))


def test_copy_overwrite_preserves_quarantine_if_unlink_fails(
    tmp_path, monkeypatch
):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "source.txt").write_text("NEW", encoding="utf-8")
    destination = destination_root / "copy.txt"
    destination.write_text("ORIGINAL", encoding="utf-8")

    original_unlink = os.unlink

    def fail_quarantine_unlink(path, *args, **kwargs):
        if "devagent-quarantine-" in str(path):
            raise PermissionError(13, "falha injetada ao remover quarentena")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_quarantine_unlink)

    SecureFileSystem.copy_file_no_follow(
        source_root,
        Path("source.txt"),
        destination_root,
        Path("copy.txt"),
        overwrite=True,
    )

    assert destination.read_text(encoding="utf-8") == "NEW"

    quarantines = list(
        destination_root.glob(".*.devagent-quarantine-*")
    )
    assert len(quarantines) == 1
    assert quarantines[0].read_text(encoding="utf-8") == "ORIGINAL"



def test_open_directory_chain_maps_eloop_to_value_error(monkeypatch, tmp_path):
    original_open = os.open

    def fail(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is not None and path == "unsafe":
            raise OSError(errno.ELOOP, "symlink loop")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail)
    with pytest.raises(ValueError, match="Caminho de diretório não é seguro"):
        SecureFileSystem.open_directory_chain(tmp_path, ("unsafe",))


def test_coverage_renameat2_unavailable_branch(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(
        "core.executor.secure_filesystem.ctypes.CDLL",
        lambda *a, **k: SimpleNamespace(),
    )
    with pytest.raises(OSError) as caught:
        SecureFileSystem._rename_noreplace_in_parent(1, "source", "dest")
    assert caught.value.errno == errno.ENOSYS


def test_coverage_renameat2_syscall_error(monkeypatch):
    from types import SimpleNamespace

    class FailedRename:
        def __call__(self, *args):
            return -1

    rename = FailedRename()
    monkeypatch.setattr(
        "core.executor.secure_filesystem.ctypes.CDLL",
        lambda *a, **k: SimpleNamespace(renameat2=rename),
    )
    monkeypatch.setattr(
        "core.executor.secure_filesystem.ctypes.get_errno",
        lambda: errno.EPERM,
    )
    with pytest.raises(OSError) as caught:
        SecureFileSystem._rename_noreplace_in_parent(1, "source", "dest")
    assert caught.value.errno == errno.EPERM


def test_replace_temporary_destination_reports_removed_destination(tmp_path):
    dest = tmp_path / "destination.txt"
    temp = tmp_path / ".destination.txt.devagent-temp"
    dest.write_text("original", encoding="utf-8")
    temp.write_text("replacement", encoding="utf-8")
    identity = (dest.stat().st_dev, dest.stat().st_ino)
    dest.unlink()
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError, match="Destino foi removido"):
            SecureFileSystem._replace_temporary_destination(
                fd, Path(dest.name), temp.name, identity
            )
    finally:
        os.close(fd)
    assert temp.exists()


def test_replace_temporary_destination_stops_after_quarantine_collisions(
    monkeypatch, tmp_path
):
    dest = tmp_path / "destination.txt"
    temp = tmp_path / ".destination.txt.devagent-temp"
    dest.write_text("original", encoding="utf-8")
    temp.write_text("replacement", encoding="utf-8")
    identity = (dest.stat().st_dev, dest.stat().st_ino)
    calls = {"count": 0}

    def collide(parent, source, target):
        calls["count"] += 1
        raise FileExistsError(errno.EEXIST, "collision", target)

    monkeypatch.setattr(
        SecureFileSystem, "_rename_noreplace_in_parent", staticmethod(collide)
    )
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError, match="Não foi possível criar quarentena"):
            SecureFileSystem._replace_temporary_destination(
                fd, Path(dest.name), temp.name, identity
            )
    finally:
        os.close(fd)
    assert calls["count"] == 32
    assert dest.read_text(encoding="utf-8") == "original"


def test_replace_temporary_destination_preserves_quarantine_if_restore_fails(
    monkeypatch, tmp_path
):
    dest = tmp_path / "destination.txt"
    temp = tmp_path / ".destination.txt.devagent-temp"
    dest.write_text("original", encoding="utf-8")
    temp.write_text("replacement", encoding="utf-8")
    identity = (dest.stat().st_dev, dest.stat().st_ino)
    original_rename = SecureFileSystem._rename_noreplace_in_parent
    calls = {"publish": False, "restore": False}

    def fail_publish_and_restore(parent, source, target):
        if source == temp.name and target == dest.name:
            calls["publish"] = True
            raise OSError(errno.EIO, "publication failed")
        if "quarantine" in source and target == dest.name:
            calls["restore"] = True
            raise OSError(errno.EIO, "restore failed")
        return original_rename(parent, source, target)

    monkeypatch.setattr(
        SecureFileSystem,
        "_rename_noreplace_in_parent",
        staticmethod(fail_publish_and_restore),
    )
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError, match="publication failed"):
            SecureFileSystem._replace_temporary_destination(
                fd, Path(dest.name), temp.name, identity
            )
    finally:
        os.close(fd)

    quarantines = list(tmp_path.glob(".*.devagent-quarantine-*"))
    assert calls["publish"] and calls["restore"]
    assert not dest.exists()
    assert len(quarantines) == 1
    assert quarantines[0].read_text(encoding="utf-8") == "original"
