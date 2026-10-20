import errno
import ctypes
import os
import stat
import secrets
from pathlib import Path

from core.executor.secure_filesystem import SecureFileSystem

from core.schemas.models import ChangeType
from core.security import SecurityPolicy


class SafeExecutor:
    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()
        self.security = SecurityPolicy(self.root)

    def _safe_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError(f"Caminho absoluto não permitido: {relative_path}")

        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error
        return target

    @staticmethod
    def _open_directory_chain(
        root: Path,
        parts: tuple[str, ...],
        *,
        create: bool = False,
    ) -> int:
        return SecureFileSystem.open_directory_chain(
            root,
            parts,
            create=create,
        )

    @staticmethod
    def _open_parent_directory(
        root: Path,
        relative_path: str,
        *,
        create: bool = False,
    ) -> int:
        return SecureFileSystem.open_parent_directory(
            root,
            relative_path,
            create=create,
        )

    @staticmethod
    def _fsync_directory(parent_fd: int) -> None:
        SecureFileSystem.fsync_directory(parent_fd)

    @staticmethod
    def _write_new_file_in_parent(
        parent_fd: int,
        filename: str,
        content: str,
    ) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
        )

        fd = os.open(
            filename,
            flags,
            0o644,
            dir_fd=parent_fd,
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

            SafeExecutor._fsync_directory(parent_fd)
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    @staticmethod
    def _open_file_mode_in_parent(
        parent_fd: int,
        filename: str,
        display_path: str,
    ) -> int:
        try:
            fd = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError as error:
            raise FileNotFoundError(
                f"Arquivo não encontrado: {display_path}"
            ) from error
        except IsADirectoryError as error:
            raise ValueError(
                f"Caminho não é um arquivo: {display_path}"
            ) from error
        except OSError as error:
            if getattr(error, "errno", None) in (
                errno.ELOOP,
                errno.EISDIR,
            ):
                raise ValueError(
                    f"Caminho não é um arquivo: {display_path}"
                ) from error
            raise

        try:
            stat_result = os.fstat(fd)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValueError(
                    f"Caminho não é um arquivo: {display_path}"
                )
            return stat.S_IMODE(stat_result.st_mode)
        finally:
            os.close(fd)

    @staticmethod
    def _create_temporary_file_in_parent(
        parent_fd: int,
        filename: str,
        mode: int,
        display_path: str,
    ) -> tuple[int, str]:
        for _ in range(32):
            candidate = (
                f".{filename}.devagent-"
                f"{secrets.token_hex(12)}.tmp"
            )
            try:
                temporary_fd = os.open(
                    candidate,
                    (
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | os.O_NOFOLLOW
                    ),
                    mode,
                    dir_fd=parent_fd,
                )
                return temporary_fd, candidate
            except FileExistsError:
                continue

        raise FileExistsError(
            f"Não foi possível criar arquivo temporário para: "
            f"{display_path}"
        )

    @staticmethod
    def _write_and_replace_file_in_parent(
        parent_fd: int,
        filename: str,
        content: str,
        temporary_fd: int,
        temporary_name: str,
    ) -> None:
        fd = temporary_fd
        try:
            handle = os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            )
            fd = None
        except Exception:
            os.close(fd)
            raise

        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        SafeExecutor._fsync_directory(parent_fd)

    @staticmethod
    def _cleanup_temporary_file_in_parent(
        parent_fd: int,
        temporary_fd: int | None,
        temporary_name: str | None,
    ) -> None:
        if temporary_fd is not None:
            os.close(temporary_fd)

        if temporary_name is not None:
            try:
                os.unlink(
                    temporary_name,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                pass

    @staticmethod
    def _modify_file_in_parent(
        parent_fd: int,
        filename: str,
        content: str,
        display_path: str,
    ) -> None:
        mode = SafeExecutor._open_file_mode_in_parent(
            parent_fd,
            filename,
            display_path,
        )
        temporary_fd, temporary_name = (
            SafeExecutor._create_temporary_file_in_parent(
                parent_fd,
                filename,
                mode,
                display_path,
            )
        )

        try:
            SafeExecutor._write_and_replace_file_in_parent(
                parent_fd,
                filename,
                content,
                temporary_fd,
                temporary_name,
            )
            temporary_name = None
        finally:
            SafeExecutor._cleanup_temporary_file_in_parent(
                parent_fd,
                None,
                temporary_name,
            )

    @staticmethod
    def _verify_regular_file_in_parent(
        parent_fd: int,
        filename: str,
        relative_path: str,
    ) -> tuple[int, int]:
        try:
            fd = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError as error:
            raise FileNotFoundError(
                f"Arquivo não encontrado: {relative_path}"
            ) from error
        except OSError as error:
            if getattr(error, "errno", None) in (
                errno.ELOOP,
                errno.EISDIR,
            ):
                raise ValueError(
                    f"Caminho não é um arquivo: {relative_path}"
                ) from error
            raise

        try:
            stat_result = os.fstat(fd)
            if not stat.S_ISREG(stat_result.st_mode):
                raise ValueError(
                    f"Caminho não é um arquivo: {relative_path}"
                )
            return (
                stat_result.st_dev,
                stat_result.st_ino,
            )
        finally:
            os.close(fd)

    @staticmethod
    def _rename_noreplace_in_parent(parent_fd, source, destination):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOSYS, "renameat2 indisponível")

        renameat2.argtypes = [
            ctypes.c_int, ctypes.c_char_p,
            ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            parent_fd, os.fsencode(source),
            parent_fd, os.fsencode(destination),
            1,  # RENAME_NOREPLACE
        )
        if result != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), destination)

    @staticmethod
    def _cleanup_staged_file(parent_fd, name, device, inode):
        if not name:
            return

        quarantine = f".devagent-cleanup-{secrets.token_hex(16)}"
        try:
            SafeExecutor._rename_noreplace_in_parent(
                parent_fd, name, quarantine
            )
        except FileNotFoundError:
            return

        quarantined = True
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_CLOEXEC", 0)
            file_fd = os.open(quarantine, flags, dir_fd=parent_fd)
            try:
                info = os.fstat(file_fd)
                matches = (
                    stat.S_ISREG(info.st_mode)
                    and info.st_dev == device
                    and info.st_ino == inode
                )
            finally:
                os.close(file_fd)

            if not matches:
                SafeExecutor._rename_noreplace_in_parent(
                    parent_fd, quarantine, name
                )
                quarantined = False
                SafeExecutor._fsync_directory(parent_fd)
                return

            os.unlink(quarantine, dir_fd=parent_fd)
            quarantined = False
            SafeExecutor._fsync_directory(parent_fd)
        except BaseException:
            if quarantined:
                try:
                    SafeExecutor._rename_noreplace_in_parent(
                        parent_fd, quarantine, name
                    )
                    SafeExecutor._fsync_directory(parent_fd)
                except OSError:
                    # Preserva o arquivo na quarentena se não for possível
                    # restaurá-lo sem sobrescrever outro destino.
                    pass
            raise

    def _create_change(
        self, change, relative, on_create_prepared=None
    ):
        parent_fd = self._open_parent_directory(
            self.root, change.path, create=True
        )
        temporary_name = None
        device = inode = None
        published = False
        fd = None
        try:
            for _ in range(32):
                candidate = (
                    f".{relative.name}.devagent-"
                    f"{secrets.token_hex(16)}.tmp"
                )
                try:
                    fd = os.open(
                        candidate,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL
                        | os.O_NOFOLLOW,
                        0o644,
                        dir_fd=parent_fd,
                    )
                    temporary_name = candidate
                    info = os.fstat(fd)
                    device, inode = info.st_dev, info.st_ino
                    break
                except FileExistsError:
                    continue
            if fd is None or temporary_name is None:
                raise FileExistsError(
                    f"Não foi possível criar temporário: {change.path}"
                )

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(change.content or "")
                handle.flush()
                os.fsync(handle.fileno())
                info = os.fstat(handle.fileno())
                device, inode = info.st_dev, info.st_ino

            self._fsync_directory(parent_fd)

            temporary_path = str(relative.parent / temporary_name)
            if on_create_prepared is not None:
                on_create_prepared(
                    change, temporary_path, device, inode
                )

            try:
                self._rename_noreplace_in_parent(
                    parent_fd, temporary_name, relative.name
                )
            except OSError as error:
                if error.errno == errno.EEXIST:
                    raise FileExistsError(
                        f"Arquivo já existe: {change.path}"
                    ) from error
                raise

            published = True
            self._fsync_directory(parent_fd)
        except Exception as original_error:
            if not published and temporary_name is not None:
                try:
                    self._cleanup_staged_file(
                        parent_fd, temporary_name, device, inode
                    )
                except OSError as cleanup_error:
                    original_error.add_note(
                        f"Falha ao limpar arquivo temporário {temporary_name}: "
                        f"{cleanup_error!r}"
                    )
            raise
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent_fd)

    def _modify_change(self, change, relative):
        parent_fd = self._open_parent_directory(
            self.root,
            change.path,
        )
        try:
            self._modify_file_in_parent(
                parent_fd,
                relative.name,
                change.content or "",
                change.path,
            )
        finally:
            os.close(parent_fd)

    def _delete_change(self, change, relative):
        parent_fd = self._open_parent_directory(
            self.root,
            change.path,
        )
        try:
            expected_identity = self._verify_regular_file_in_parent(
                parent_fd,
                relative.name,
                change.path,
            )

            try:
                fd = os.open(
                    relative.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as error:
                raise RuntimeError(
                    f"Arquivo foi alterado durante a remoção: "
                    f"{change.path}"
                ) from error
            except OSError as error:
                if getattr(error, "errno", None) in (
                    errno.ELOOP,
                    errno.EISDIR,
                ):
                    raise RuntimeError(
                        f"Arquivo foi alterado durante a remoção: "
                        f"{change.path}"
                    ) from error
                raise

            try:
                current_stat = os.fstat(fd)
                current_identity = (
                    current_stat.st_dev,
                    current_stat.st_ino,
                )
            finally:
                os.close(fd)

            if current_identity != expected_identity:
                raise RuntimeError(
                    f"Arquivo foi alterado durante a remoção: "
                    f"{change.path}"
                )

            os.unlink(relative.name, dir_fd=parent_fd)
            self._fsync_directory(parent_fd)
        finally:
            os.close(parent_fd)

    def execute_change(self, change, on_create_prepared=None):
        target = self._safe_path(change.path)

        if (
            change.change_type in (ChangeType.MODIFY, ChangeType.DELETE)
            and target.exists()
            and not target.is_file()
        ):
            raise ValueError(f"Caminho não é um arquivo: {change.path}")

        self.security.validate_path(change.path)

        if change.change_type in (ChangeType.CREATE, ChangeType.MODIFY):
            self.security.validate_content(change.content)

        relative = Path(change.path)

        if change.change_type == ChangeType.CREATE:
            self._create_change(
                change, relative, on_create_prepared=on_create_prepared
            )
        elif change.change_type == ChangeType.MODIFY:
            self._modify_change(change, relative)
        elif change.change_type == ChangeType.DELETE:
            self._delete_change(change, relative)
        else:
            raise ValueError(
                f"Tipo de alteração não suportado: {change.change_type}"
            )


    def execute(
        self, transaction, on_change_applied=None,
        on_create_prepared=None,
    ):

        if on_change_applied is not None and not callable(on_change_applied):
            raise ValueError(
                "Callback de progresso inválido."
            )

        metadata = getattr(
            transaction,
            "metadata",
            None,
        )
        if metadata is None:
            metadata = {}
            transaction.metadata = metadata

        execution = metadata.setdefault(
            "execution",
            {},
        )
        execution["phase"] = "executing"
        execution["changes_applied"] = 0

        try:
            for change in transaction.changes:
                if (
                    change.change_type == ChangeType.CREATE
                    and on_create_prepared is not None
                ):
                    self.execute_change(
                        change, on_create_prepared=on_create_prepared
                    )
                else:
                    self.execute_change(change)
                execution["changes_applied"] += 1

                if on_change_applied is not None:
                    on_change_applied()
        except Exception:
            raise

        execution["phase"] = "completed"
        return transaction
