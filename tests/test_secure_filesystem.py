import pytest
import os
import errno

def test_open_directory_chain_reraises_unexpected_oserror(monkeypatch, tmp_path):
    from core.executor.secure_filesystem import SecureFileSystem

    original_error = OSError(errno.EACCES, "permissão negada")
    real_open = os.open

    def fake_open(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            raise original_error
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(
        "core.executor.secure_filesystem.os.open",
        fake_open,
    )

    with pytest.raises(OSError) as exc_info:
        SecureFileSystem.open_directory_chain(tmp_path, ("subdir",))

    assert exc_info.value is original_error
