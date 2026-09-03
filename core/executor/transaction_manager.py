from pathlib import Path
import errno
import os
import stat
import shutil
import uuid

from core.schemas.models import (
    ChangeType,
    TransactionStatus,
)


class TransactionManager:

    def __init__(self, root=".", backup_dir="transactions"):

        self.root = Path(root).resolve()
        self.backup_dir = (
            self.root / backup_dir
        ).resolve()

        try:
            self.backup_dir.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Diretório de backup fora do projeto: {backup_dir}"
            ) from error

    @staticmethod
    def _fsync_directory(parent_fd: int) -> None:
        os.fsync(parent_fd)

    def _safe_path(self, relative_path):
        target = (self.root / relative_path).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        return target

    def begin(self, transaction):
        transaction.transaction_id = str(uuid.uuid4())

        backup_relative = self.backup_dir.relative_to(self.root)
        backup_parent_relative = backup_relative.parent
        backup_name = backup_relative.name

        parent_fd = self._open_directory_chain(
            self.root,
            backup_parent_relative.parts,
            create=True,
        )
        try:
            try:
                try:
                    os.mkdir(
                        backup_name,
                        dir_fd=parent_fd,
                    )
                except FileExistsError:
                    pass

                backup_parent_fd = os.open(
                    backup_name,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except OSError as error:
                raise ValueError(
                    "Diretório de backup inválido."
                ) from error

            try:
                backup_stat = os.fstat(backup_parent_fd)
                if not stat.S_ISDIR(backup_stat.st_mode):
                    raise ValueError(
                        "Diretório de backup inválido."
                    )

                try:
                    os.mkdir(
                        transaction.transaction_id,
                        dir_fd=backup_parent_fd,
                    )
                except FileExistsError as error:
                    raise ValueError(
                        "Diretório de backup já existe ou não é seguro."
                    ) from error

                transaction_fd = os.open(
                    transaction.transaction_id,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW,
                    dir_fd=backup_parent_fd,
                )
                try:
                    transaction_stat = os.fstat(transaction_fd)
                    if not stat.S_ISDIR(transaction_stat.st_mode):
                        raise ValueError(
                            "Diretório de backup inválido."
                        )
                finally:
                    os.close(transaction_fd)
            finally:
                os.close(backup_parent_fd)
        finally:
            os.close(parent_fd)

        backup = self.backup_dir / transaction.transaction_id
        transaction.metadata["backup"] = str(backup)
        transaction.metadata["created"] = []
        return transaction

    @classmethod
    def _open_directory_chain(
    cls,
        root: Path,
        parts: tuple[str, ...],
        *,
        create: bool = False,
    ) -> int:
        fd = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )

        try:
            for part in parts:
                if part in ("", ".", ".."):
                    raise ValueError(f"Caminho inválido: {part}")

                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=fd)
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=fd,
                    )

                os.close(fd)
                fd = next_fd

            return fd
        except Exception:
            os.close(fd)
            raise

    @classmethod
    def _open_parent_directory(
        cls,
        root: Path,
        relative_path: Path,
        *,
        create: bool = False,
    ) -> int:
        if relative_path.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        parts = relative_path.parts
        if not parts or parts[-1] in ("", ".", ".."):
            raise ValueError(f"Caminho inválido: {relative_path}")

        return cls._open_directory_chain(
            root,
            parts[:-1],
            create=create,
        )

    @classmethod
    def _copy_file_no_follow(
        cls,
        source_root: Path,
        source_relative: Path,
        destination_root: Path,
        destination_relative: Path,
        *,
        overwrite: bool = False,
    ) -> None:
        source_parent_fd = cls._open_parent_directory(
            source_root,
            source_relative,
        )
        destination_parent_fd = cls._open_parent_directory(
            destination_root,
            destination_relative,
            create=True,
        )

        source_fd = None
        destination_fd = None
        temporary_name = None

        try:
            try:
                source_fd = os.open(
                    source_relative.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=source_parent_fd,
                )
            except OSError as error:
                if getattr(error, "errno", None) == errno.ELOOP:
                    raise ValueError(
                        f"Caminho não é um arquivo regular: "
                        f"{source_relative}"
                    ) from error
                raise

            source_stat = os.fstat(source_fd)

            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError(
                    f"Caminho não é um arquivo regular: "
                    f"{source_relative}"
                )

            mode = stat.S_IMODE(source_stat.st_mode)

            expected_destination_identity = None

            if overwrite:
                try:
                    existing_destination_fd = os.open(
                        destination_relative.name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=destination_parent_fd,
                    )
                except FileNotFoundError:
                    pass
                except OSError as error:
                    if getattr(error, "errno", None) in (
                        errno.ELOOP,
                        errno.EISDIR,
                    ):
                        raise ValueError(
                            f"Caminho de destino não é seguro: "
                            f"{destination_relative}"
                        ) from error
                    raise
                else:
                    try:
                        destination_stat = os.fstat(
                            existing_destination_fd
                        )

                        if not stat.S_ISREG(destination_stat.st_mode):
                            raise ValueError(
                                f"Caminho de destino não é um "
                                f"arquivo regular: {destination_relative}"
                            )

                        expected_destination_identity = (
                            destination_stat.st_dev,
                            destination_stat.st_ino,
                        )
                    finally:
                        os.close(existing_destination_fd)

                for _ in range(32):
                    candidate = (
                        f".{destination_relative.name}.devagent-"
                        f"{uuid.uuid4().hex}.tmp"
                    )

                    try:
                        destination_fd = os.open(
                            candidate,
                            (
                                os.O_WRONLY
                                | os.O_CREAT
                                | os.O_EXCL
                                | os.O_NOFOLLOW
                            ),
                            mode,
                            dir_fd=destination_parent_fd,
                        )
                        temporary_name = candidate
                        break
                    except FileExistsError:
                        continue

                if destination_fd is None or temporary_name is None:
                    raise FileExistsError(
                        "Não foi possível criar arquivo temporário "
                        f"para: {destination_relative}"
                    )
            else:
                try:
                    destination_fd = os.open(
                        destination_relative.name,
                        (
                            os.O_WRONLY
                            | os.O_CREAT
                            | os.O_EXCL
                            | os.O_NOFOLLOW
                        ),
                        mode,
                        dir_fd=destination_parent_fd,
                    )
                except OSError as error:
                    if getattr(error, "errno", None) == errno.ELOOP:
                        raise ValueError(
                            f"Caminho de destino não é seguro: "
                            f"{destination_relative}"
                        ) from error
                    raise

            while True:
                chunk = os.read(source_fd, 1024 * 1024)

                if not chunk:
                    break

                view = memoryview(chunk)

                while view:
                    written = os.write(destination_fd, view)

                    if written <= 0:
                        raise OSError(
                            "Falha ao escrever arquivo de destino."
                        )

                    view = view[written:]

            os.fchmod(destination_fd, mode)
            os.fsync(destination_fd)

            os.close(destination_fd)
            destination_fd = None

            if overwrite:
                try:
                    current_destination_fd = os.open(
                        destination_relative.name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=destination_parent_fd,
                    )
                except FileNotFoundError:
                    if expected_destination_identity is not None:
                        raise RuntimeError(
                            "Destino foi removido durante a restauração: "
                            f"{destination_relative}"
                        )
                except OSError as error:
                    if getattr(error, "errno", None) in (
                        errno.ELOOP,
                        errno.EISDIR,
                    ):
                        raise RuntimeError(
                            "Destino foi alterado para um caminho inseguro "
                            f"durante a restauração: {destination_relative}"
                        ) from error
                    raise
                else:
                    try:
                        current_destination_stat = os.fstat(
                            current_destination_fd
                        )

                        if not stat.S_ISREG(
                            current_destination_stat.st_mode
                        ):
                            raise RuntimeError(
                                "Destino deixou de ser um arquivo regular "
                                f"durante a restauração: {destination_relative}"
                            )

                        current_destination_identity = (
                            current_destination_stat.st_dev,
                            current_destination_stat.st_ino,
                        )

                        if (
                            expected_destination_identity is not None
                            and current_destination_identity
                            != expected_destination_identity
                        ):
                            raise RuntimeError(
                                "Destino foi alterado durante a restauração: "
                                f"{destination_relative}"
                            )
                    finally:
                        os.close(current_destination_fd)

                os.replace(
                    temporary_name,
                    destination_relative.name,
                    src_dir_fd=destination_parent_fd,
                    dst_dir_fd=destination_parent_fd,
                )
                temporary_name = None

            cls._fsync_directory(destination_parent_fd)

        finally:
            if source_fd is not None:
                os.close(source_fd)

            if destination_fd is not None:
                os.close(destination_fd)

            if temporary_name is not None:
                try:
                    os.unlink(
                        temporary_name,
                        dir_fd=destination_parent_fd,
                    )
                except FileNotFoundError:
                    pass

            os.close(source_parent_fd)
            os.close(destination_parent_fd)

    def backup_file(self, transaction, relative_path: str) -> None:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        backup_value = transaction.metadata.get("backup")
        if not backup_value:
            raise ValueError("Diretório de backup não configurado")

        backup_dir = Path(backup_value).resolve()
        try:
            backup_dir.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                "Diretório de backup fora do projeto"
            ) from error

        expected_backup = (
            self.root / "transactions" / transaction.transaction_id
        ).resolve()
        if backup_dir != expected_backup:
            raise ValueError("Caminho de backup inválido")

        source = (self.root / relative).resolve()
        try:
            source.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        if not source.exists():
            return

        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"Caminho não é um arquivo: {relative_path}"
            )

        destination = (backup_dir / relative).resolve()
        try:
            destination.relative_to(backup_dir)
        except ValueError as error:
            raise ValueError(
                f"Caminho de backup inválido: {relative_path}"
            ) from error

        if destination.is_symlink():
            raise ValueError(
                f"Caminho de backup inválido: {relative_path}"
            )

        if destination.exists():
            return

        self._copy_file_no_follow(
            self.root,
            relative,
            backup_dir,
            relative,
        )

    def register_created(
        self,
        transaction,
        relative_path
    ):

        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        target = (
            self.root / relative
        ).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        if target.exists() and target.is_dir():
            raise ValueError(
                f"Caminho aponta para um diretório: {relative_path}"
            )

        transaction.metadata[
            "created"
        ].append(relative_path)

        if target.exists() and target.is_file():
            file_stat = target.stat()

            transaction.metadata.setdefault(
                "created_identity",
                {},
            )[relative_path] = {
                "st_dev": file_stat.st_dev,
                "st_ino": file_stat.st_ino,
            }

    def rollback(self, transaction):
        expected_backup = (
            self.backup_dir /
            transaction.transaction_id
        ).resolve()

        backup_root = Path(
            transaction.metadata["backup"]
        ).resolve()

        if backup_root != expected_backup:
            raise ValueError(
                "Diretório de backup inválido."
            )

        if not backup_root.is_dir():
            raise ValueError(
                "Diretório de backup inválido."
            )

        # Remove arquivos criados durante a transação.
        for relative_path in transaction.metadata.get(
            "created",
            []
        ):
            expected_identity = transaction.metadata.get(
                "created_identity",
                {},
            ).get(relative_path, {})

            expected_dev = expected_identity.get("st_dev")
            expected_ino = expected_identity.get("st_ino")

            relative = Path(relative_path)

            if relative.is_absolute():
                raise ValueError(
                    f"Caminho absoluto não permitido: {relative_path}"
                )

            target = (
                self.root / relative
            ).resolve()

            try:
                target.relative_to(self.root)
            except ValueError as error:
                raise ValueError(
                    f"Caminho fora do projeto: {relative_path}"
                ) from error

            parent_fd = self._open_parent_directory(
                self.root,
                relative,
            )

            try:
                filename = relative.name

                try:
                    file_fd = os.open(
                        filename,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                except FileNotFoundError:
                    continue
                except OSError as error:
                    if getattr(error, "errno", None) == errno.ELOOP:
                        raise ValueError(
                            f"Caminho criado é um symlink: "
                            f"{relative_path}"
                        ) from error
                    raise

                try:
                    file_stat = os.fstat(file_fd)

                    if not stat.S_ISREG(file_stat.st_mode):
                        raise ValueError(
                            f"Caminho criado não é um arquivo regular: "
                            f"{relative_path}"
                        )

                    # Transações antigas podem não possuir identidade
                    # registrada. Mantemos compatibilidade com esse formato.
                    if (
                        expected_dev is None
                        or expected_ino is None
                    ):
                        os.unlink(
                            filename,
                            dir_fd=parent_fd,
                        )
                        self._fsync_directory(parent_fd)
                        continue

                    # Para transações novas, verificamos a identidade
                    # registrada antes de qualquer decisão destrutiva.
                    if (
                        file_stat.st_dev != expected_dev
                        or file_stat.st_ino != expected_ino
                    ):
                        raise RuntimeError(
                            "Arquivo criado foi alterado durante a "
                            f"transação: {relative_path}"
                        )

                    # A identidade foi validada contra o inode registrado
                    # durante o registro da criação. A remoção continua
                    # relativa ao parent_fd já validado.
                    os.unlink(
                        filename,
                        dir_fd=parent_fd,
                    )
                    self._fsync_directory(parent_fd)

                finally:
                    os.close(file_fd)
            finally:
                os.close(parent_fd)

        # Restaura arquivos antigos.
        for backup_file in backup_root.rglob("*"):

            # Nunca seguir symlinks encontrados no backup.
            if backup_file.is_symlink():
                raise ValueError(
                    f"Backup contém symlink: {backup_file}"
                )

            if not backup_file.is_file():
                continue

            relative = backup_file.relative_to(
                backup_root
            )

            destination = (
                self.root / relative
            ).resolve()

            raw_destination = self.root / relative

            if raw_destination.is_symlink():
                raise ValueError(
                    f"Destino de rollback é um symlink: {relative}"
                )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            self._copy_file_no_follow(
                backup_root,
                relative,
                self.root,
                relative,
                overwrite=True,
            )

        transaction.status = (
            TransactionStatus.ROLLED_BACK
        )

        return transaction
