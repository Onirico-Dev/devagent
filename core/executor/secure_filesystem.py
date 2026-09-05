from pathlib import Path
import errno
import os
import stat
import uuid


class SecureFileSystem:
    """Operações de filesystem com resolução segura e sem seguir symlinks."""

    @staticmethod
    def fsync_directory(parent_fd: int) -> None:
        os.fsync(parent_fd)

    @classmethod
    def open_directory_chain(
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
    def open_parent_directory(
        cls,
        root: Path,
        relative_path: str | Path,
        *,
        create: bool = False,
    ) -> int:
        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        parts = relative.parts

        if not parts or parts[-1] in ("", ".", ".."):
            raise ValueError(
                f"Caminho inválido: {relative_path}"
            )

        return cls.open_directory_chain(
            root,
            parts[:-1],
            create=create,
        )

    @classmethod
    def copy_file_no_follow(
        cls,
        source_root: Path,
        source_relative: Path,
        destination_root: Path,
        destination_relative: Path,
        *,
        overwrite: bool = False,
    ) -> None:
        source_parent_fd = cls.open_parent_directory(
            source_root,
            source_relative,
        )

        destination_parent_fd = cls.open_parent_directory(
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
                        "Caminho não é um arquivo regular: "
                        f"{source_relative}"
                    ) from error
                raise

            source_stat = os.fstat(source_fd)

            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError(
                    "Caminho não é um arquivo regular: "
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
                            "Caminho de destino não é seguro: "
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
                                "Caminho de destino não é um "
                                "arquivo regular: "
                                f"{destination_relative}"
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
                            "Caminho de destino não é seguro: "
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
                            f"durante a restauração: "
                            f"{destination_relative}"
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
                                "durante a restauração: "
                                f"{destination_relative}"
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

            if overwrite:
                os.replace(
                    temporary_name,
                    destination_relative.name,
                    src_dir_fd=destination_parent_fd,
                    dst_dir_fd=destination_parent_fd,
                )

            temporary_name = None
            cls.fsync_directory(destination_parent_fd)

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
