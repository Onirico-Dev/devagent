import os
import pytest

def test_open_directory_chain_rejects_invalid_component(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    with pytest.raises(ValueError, match="Caminho inválido"):
        (tmp_path / "invalid").mkdir()

        SafeExecutor._open_directory_chain(
            tmp_path,
            ("invalid", ".."),
        )


def test_open_parent_directory_creates_missing_directories(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    fd = SafeExecutor._open_parent_directory(
        tmp_path,
        "a/b/file.txt",
        create=True,
    )

    try:
        assert (tmp_path / "a").is_dir()
        assert (tmp_path / "a" / "b").is_dir()
    finally:
        os.close(fd)


def test_modify_file_in_parent_rejects_missing_file(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    try:
        with pytest.raises(
            FileNotFoundError,
            match="Arquivo não encontrado",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "missing.txt",
                "content",
                "missing.txt",
            )
    finally:
        os.close(parent_fd)


def test_modify_file_in_parent_rejects_directory(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    directory = tmp_path / "directory"
    directory.mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "directory",
                "content",
                "directory",
            )
    finally:
        os.close(parent_fd)


def test_verify_regular_file_in_parent_rejects_missing_file(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    try:
        with pytest.raises(
            FileNotFoundError,
            match="Arquivo não encontrado",
        ):
            SafeExecutor._verify_regular_file_in_parent(
                parent_fd,
                "missing.txt",
                "missing.txt",
            )
    finally:
        os.close(parent_fd)


def test_verify_regular_file_in_parent_rejects_directory(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    directory = tmp_path / "directory"
    directory.mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo",
        ):
            SafeExecutor._verify_regular_file_in_parent(
                parent_fd,
                "directory",
                "directory",
            )
    finally:
        os.close(parent_fd)


def test_execute_create_rejects_existing_file(tmp_path):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "existing.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    change = Change(
        change_type=ChangeType.CREATE,
        path="existing.txt",
        content="replacement",
    )

    with pytest.raises(
        FileExistsError,
        match="Arquivo já existe",
    ):
        executor.execute_change(change)

    assert target.read_text(encoding="utf-8") == "original"

def test_open_parent_directory_rejects_invalid_parent_component(
    tmp_path,
):
    from core.executor.safe_executor import SafeExecutor

    with pytest.raises(ValueError, match="Caminho inválido"):
        SafeExecutor._open_parent_directory(
            tmp_path,
            "invalid/../file.txt",
            create=True,
        )


def test_open_parent_directory_without_create_uses_directory_chain(
    tmp_path,
):
    from core.executor.safe_executor import SafeExecutor

    directory = tmp_path / "directory"
    directory.mkdir()

    fd = SafeExecutor._open_parent_directory(
        tmp_path,
        "directory/file.txt",
        create=False,
    )

    try:
        assert fd >= 0
    finally:
        os.close(fd)


def test_modify_file_in_parent_reraises_unexpected_oserror(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    original_open = os.open

    def fail_open(*args, **kwargs):
        raise OSError(5, "simulated I/O failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_open,
    )

    try:
        with pytest.raises(OSError, match="simulated I/O failure"):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "content",
                "file.txt",
            )
    finally:
        monkeypatch.setattr(
            "core.executor.safe_executor.os.open",
            original_open,
        )
        os.close(parent_fd)


def test_verify_regular_file_in_parent_reraises_unexpected_oserror(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def fail_open(*args, **kwargs):
        raise OSError(5, "simulated I/O failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_open,
    )

    try:
        with pytest.raises(OSError, match="simulated I/O failure"):
            SafeExecutor._verify_regular_file_in_parent(
                parent_fd,
                "file.txt",
                "file.txt",
            )
    finally:
        os.close(parent_fd)


def test_modify_file_in_parent_fails_after_temporary_name_collisions(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    original_open = os.open
    temporary_attempts = 0

    def collision_on_temporary(*args, **kwargs):
        nonlocal temporary_attempts

        filename = args[0] if args else None

        if isinstance(filename, str) and ".devagent-" in filename:
            temporary_attempts += 1
            raise FileExistsError("simulated collision")

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        collision_on_temporary,
    )

    try:
        with pytest.raises(
            FileExistsError,
            match="Não foi possível criar arquivo temporário",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "replacement",
                "file.txt",
            )

        assert temporary_attempts == 32
    finally:
        os.close(parent_fd)


def test_modify_file_in_parent_cleans_temporary_after_replace_failure(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    original_replace = os.replace

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.replace",
        fail_replace,
    )

    try:
        with pytest.raises(OSError, match="simulated replace failure"):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "replacement",
                "file.txt",
            )
    finally:
        monkeypatch.setattr(
            "core.executor.safe_executor.os.replace",
            original_replace,
        )
        os.close(parent_fd)

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".file.txt.devagent-*.tmp"))


def test_execute_delete_detects_file_changed_between_checks(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    original_verify = executor._verify_regular_file_in_parent

    def verify_then_replace(parent_fd, filename, relative_path):
        identity = original_verify(
            parent_fd,
            filename,
            relative_path,
        )

        replacement = tmp_path / "replacement.txt"
        replacement.write_text("replacement", encoding="utf-8")

        os.replace(replacement, target)

        return identity

    monkeypatch.setattr(
        executor,
        "_verify_regular_file_in_parent",
        verify_then_replace,
    )

    with pytest.raises(
        RuntimeError,
        match="Arquivo foi alterado durante a remoção",
    ):
        executor.execute_change(change)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "replacement"


def test_open_parent_directory_rejects_absolute_path(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        SafeExecutor._open_parent_directory(
            tmp_path,
            "/absolute/file.txt",
        )


def test_open_parent_directory_rejects_invalid_terminal_path(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    for relative_path in ("", ".", "..", "file/.."):
        with pytest.raises(
            ValueError,
            match="Caminho inválido",
        ):
            SafeExecutor._open_parent_directory(
                tmp_path,
                relative_path,
            )


def test_write_new_file_closes_fd_when_fdopen_fails(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    captured_fd = None

    def fail_fdopen(fd, *args, **kwargs):
        nonlocal captured_fd
        captured_fd = fd
        raise OSError("simulated fdopen failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.fdopen",
        fail_fdopen,
    )

    try:
        with pytest.raises(OSError, match="simulated fdopen failure"):
            SafeExecutor._write_new_file_in_parent(
                parent_fd,
                "file.txt",
                "content",
            )

        assert captured_fd is not None

        with pytest.raises(OSError):
            os.fstat(captured_fd)

    finally:
        os.close(parent_fd)


def test_modify_file_closes_temporary_fd_when_fdopen_fails(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def fail_fdopen(*args, **kwargs):
        raise OSError("simulated fdopen failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.fdopen",
        fail_fdopen,
    )

    try:
        with pytest.raises(OSError, match="simulated fdopen failure"):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "replacement",
                "file.txt",
            )
    finally:
        os.close(parent_fd)

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".file.txt.devagent-*.tmp"))


def test_modify_file_suppresses_missing_temporary_during_cleanup(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    def missing_unlink(*args, **kwargs):
        raise FileNotFoundError("simulated missing temporary")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.replace",
        fail_replace,
    )
    monkeypatch.setattr(
        "core.executor.safe_executor.os.unlink",
        missing_unlink,
    )

    try:
        with pytest.raises(OSError, match="simulated replace failure"):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "replacement",
                "file.txt",
            )
    finally:
        os.close(parent_fd)

    assert target.read_text(encoding="utf-8") == "original"


def test_execute_delete_rejects_file_disappearing_during_second_open(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    original_open = os.open
    open_calls = 0

    def fail_second_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1

        if open_calls == 1:
            return original_open(*args, **kwargs)

        raise FileNotFoundError("simulated disappearance")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_second_open,
    )

    monkeypatch.setattr(
        executor,
        "_verify_regular_file_in_parent",
        lambda *args: (1, 2),
    )

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    with pytest.raises(
        RuntimeError,
        match="Arquivo foi alterado durante a remoção",
    ):
        executor.execute_change(change)

    assert target.exists()


def test_execute_delete_rejects_symlink_race_during_second_open(
    tmp_path,
    monkeypatch,
):
    import errno
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    original_open = os.open
    open_calls = 0

    def fail_second_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1

        if open_calls == 1:
            return original_open(*args, **kwargs)

        raise OSError(errno.ELOOP, "simulated symlink race")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_second_open,
    )

    monkeypatch.setattr(
        executor,
        "_verify_regular_file_in_parent",
        lambda *args: (1, 2),
    )

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    with pytest.raises(
        RuntimeError,
        match="Arquivo foi alterado durante a remoção",
    ):
        executor.execute_change(change)

    assert target.exists()

def test_modify_file_in_parent_rejects_directory(
    tmp_path,
):
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "directory"
    target.mkdir()

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo: directory",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "directory",
                "replacement",
                "directory",
            )
    finally:
        os.close(parent_fd)


def test_execute_delete_propagates_unexpected_oserror(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)
    original_open = os.open
    open_calls = 0

    def fail_second_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1

        if open_calls == 1:
            return original_open(*args, **kwargs)

        raise OSError(5, "simulated I/O failure")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_second_open,
    )

    monkeypatch.setattr(
        executor,
        "_verify_regular_file_in_parent",
        lambda *args: (1, 2),
    )

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    with pytest.raises(
        OSError,
        match="simulated I/O failure",
    ):
        executor.execute_change(change)

    assert target.exists()

def test_modify_file_in_parent_rejects_isadirectoryerror(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def raise_isadirectoryerror(*args, **kwargs):
        raise IsADirectoryError("simulated directory")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        raise_isadirectoryerror,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo: directory",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "directory",
                "replacement",
                "directory",
            )
    finally:
        os.close(parent_fd)

def test_create_change_writes_file_and_syncs_directory(tmp_path, monkeypatch):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    executor = SafeExecutor(tmp_path)

    change = Change(
        path="created.txt",
        change_type=ChangeType.CREATE,
        content="created content",
    )

    fsync_calls = []

    def fake_fsync_directory(parent_fd):
        fsync_calls.append(parent_fd)

    monkeypatch.setattr(
        SafeExecutor,
        "_fsync_directory",
        staticmethod(fake_fsync_directory),
    )

    executor.execute_change(change)

    target = tmp_path / "created.txt"

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "created content"
    assert len(fsync_calls) == 1

def test_safe_path_rejects_absolute_path(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    executor = SafeExecutor(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho absoluto não permitido",
    ):
        executor._safe_path("/absolute/file.txt")


def test_safe_path_rejects_path_outside_project(tmp_path):
    from core.executor.safe_executor import SafeExecutor

    executor = SafeExecutor(root=tmp_path)

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        executor._safe_path("../outside.txt")


def test_execute_change_modify_dispatches_to_modify_helper(tmp_path):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    change = Change(
        change_type=ChangeType.MODIFY,
        path="file.txt",
        content="modified",
    )

    executor.execute_change(change)

    assert target.read_text(encoding="utf-8") == "modified"


def test_execute_change_rejects_unsupported_change_type(tmp_path):
    from core.executor.safe_executor import SafeExecutor
    from types import SimpleNamespace

    executor = SafeExecutor(root=tmp_path)

    change = SimpleNamespace(
        change_type="UNSUPPORTED",
        path="file.txt",
        content="content",
    )

    with pytest.raises(
        ValueError,
        match="Tipo de alteração não suportado",
    ):
        executor.execute_change(change)


def test_execute_returns_successful_transaction(tmp_path):
    from core.executor.safe_executor import SafeExecutor
    from types import SimpleNamespace
    from core.schemas.models import TransactionStatus

    executor = SafeExecutor(root=tmp_path)

    transaction = SimpleNamespace(
        changes=[],
        status=None,
    )

    result = executor.execute(transaction)

    assert result is transaction
    assert transaction.status == TransactionStatus.EXECUTING


def test_execute_marks_transaction_failed_when_change_fails(tmp_path):
    from core.executor.safe_executor import SafeExecutor
    from types import SimpleNamespace
    from core.schemas.models import TransactionStatus

    executor = SafeExecutor(root=tmp_path)

    transaction = SimpleNamespace(
        changes=[
            SimpleNamespace(
                change_type="UNSUPPORTED",
                path="file.txt",
                content="content",
            ),
        ],
        status=None,
    )

    with pytest.raises(
        ValueError,
        match="Tipo de alteração não suportado",
    ):
        executor.execute(transaction)

    assert transaction.status == TransactionStatus.FAILED


def test_modify_file_in_parent_maps_eloop_to_value_error(
    tmp_path,
    monkeypatch,
):
    import errno
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def fail_open(*args, **kwargs):
        raise OSError(errno.ELOOP, "simulated symlink loop")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_open,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "content",
                "file.txt",
            )
    finally:
        os.close(parent_fd)


def test_verify_regular_file_in_parent_maps_eloop_to_value_error(
    tmp_path,
    monkeypatch,
):
    import errno
    from core.executor.safe_executor import SafeExecutor

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    def fail_open(*args, **kwargs):
        raise OSError(errno.ELOOP, "simulated symlink loop")

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_open,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo",
        ):
            SafeExecutor._verify_regular_file_in_parent(
                parent_fd,
                "file.txt",
                "file.txt",
            )
    finally:
        os.close(parent_fd)


def test_execute_delete_detects_file_disappearing_during_second_open(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    original_open = os.open
    open_calls = 0

    def fail_second_open(*args, **kwargs):
        nonlocal open_calls

        filename = args[0] if args else None

        if (
            isinstance(filename, str)
            and filename == "file.txt"
        ):
            open_calls += 1

            if open_calls == 2:
                raise FileNotFoundError(
                    "simulated disappearing file"
                )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_second_open,
    )

    with pytest.raises(
        RuntimeError,
        match="Arquivo foi alterado durante a remoção",
    ):
        executor.execute_change(change)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "original"


def test_execute_delete_removes_file_and_syncs_directory(
    tmp_path,
    monkeypatch,
):
    from core.executor.safe_executor import SafeExecutor
    from core.schemas.models import Change, ChangeType

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    executor = SafeExecutor(root=tmp_path)

    change = Change(
        change_type=ChangeType.DELETE,
        path="file.txt",
    )

    fsync_calls = []

    def track_fsync(parent_fd):
        fsync_calls.append(parent_fd)

    monkeypatch.setattr(
        SafeExecutor,
        "_fsync_directory",
        staticmethod(track_fsync),
    )

    executor.execute_change(change)

    assert not target.exists()
    assert len(fsync_calls) == 1


def test_modify_file_in_parent_maps_eloop_for_target_open(
    tmp_path,
    monkeypatch,
):
    import errno
    from core.executor.safe_executor import SafeExecutor

    target = tmp_path / "file.txt"
    target.write_text("original", encoding="utf-8")

    parent_fd = os.open(
        tmp_path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )

    original_open = os.open

    def fail_target_open(*args, **kwargs):
        filename = args[0] if args else None

        if (
            isinstance(filename, str)
            and filename == "file.txt"
        ):
            raise OSError(
                errno.ELOOP,
                "simulated symlink loop",
            )

        return original_open(*args, **kwargs)

    monkeypatch.setattr(
        "core.executor.safe_executor.os.open",
        fail_target_open,
    )

    try:
        with pytest.raises(
            ValueError,
            match="Caminho não é um arquivo",
        ):
            SafeExecutor._modify_file_in_parent(
                parent_fd,
                "file.txt",
                "replacement",
                "file.txt",
            )
    finally:
        os.close(parent_fd)
