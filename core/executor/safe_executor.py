import errno
import os
import stat
import secrets
from pathlib import Path

from core.executor.secure_filesystem import SecureFileSystem

from core.schemas.models import ChangeType, TransactionStatus


class SafeExecutor:
    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()

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
    def _modify_file_in_parent(
        parent_fd: int,
        filename: str,
        content: str,
        display_path: str,
    ) -> None:
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

            mode = stat.S_IMODE(stat_result.st_mode)
        finally:
            os.close(fd)

        temporary_name = None
        temporary_fd = None

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
                temporary_name = candidate
                break
            except FileExistsError:
                continue

        if temporary_fd is None or temporary_name is None:
            raise FileExistsError(
                f"Não foi possível criar arquivo temporário para: "
                f"{display_path}"
            )

        try:
            with os.fdopen(
                temporary_fd,
                "w",
                encoding="utf-8",
            ) as handle:
                temporary_fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(
                temporary_name,
                filename,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )

            temporary_name = None

            SafeExecutor._fsync_directory(parent_fd)

        finally:
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

    def execute_change(self, change):
        target = self._safe_path(change.path)
        relative = Path(change.path)

        if change.change_type == ChangeType.CREATE:
            parent_fd = self._open_parent_directory(
                self.root,
                change.path,
                create=True,
            )
            try:
                try:
                    self._write_new_file_in_parent(
                        parent_fd,
                        relative.name,
                        change.content or "",
                    )
                except FileExistsError as error:
                    raise FileExistsError(
                        f"Arquivo já existe: {change.path}"
                    ) from error
            finally:
                os.close(parent_fd)

        elif change.change_type == ChangeType.MODIFY:
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

        elif change.change_type == ChangeType.DELETE:
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

        else:
            raise ValueError(
                f"Tipo de alteração não suportado: {change.change_type}"
            )

    def execute(self, transaction):
        transaction.status = TransactionStatus.EXECUTING
        try:
            for change in transaction.changes:
                self.execute_change(change)
        except Exception:
            transaction.status = TransactionStatus.FAILED
            raise
        return transaction
