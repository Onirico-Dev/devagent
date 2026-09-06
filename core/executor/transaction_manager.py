from pathlib import Path
import errno
import os
import stat
import json
import shutil
import tempfile
import uuid

from core.executor.secure_filesystem import SecureFileSystem

from core.schemas.models import (
    Change,
    ChangeType,
    Transaction,
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
        SecureFileSystem.fsync_directory(parent_fd)

    def _safe_path(self, relative_path):
        target = (self.root / relative_path).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        return target

    def _manifest_path(self, transaction_id):
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise ValueError("transaction_id inválido")
        if transaction_id in (".", "..") or "/" in transaction_id or "\\" in transaction_id:
            raise ValueError("transaction_id inválido")
        return (
            self.backup_dir / f"{transaction_id}.json"
        ).resolve()

    @staticmethod
    def _serialize_change(change):
        return {
            "change_type": change.change_type.value,
            "path": change.path,
            "content": change.content,
            "reason": change.reason,
        }

    @staticmethod
    def _deserialize_change(data):
        if not isinstance(data, dict):
            raise ValueError("Change inválido no manifesto.")

        try:
            return Change(
                change_type=ChangeType(data["change_type"]),
                path=data["path"],
                content=data.get("content"),
                reason=data.get("reason", ""),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Change inválido no manifesto.") from error

    def persist_manifest(self, transaction):
        manifest = self._manifest_path(transaction.transaction_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)

        status = getattr(transaction, "status", None)
        if status is None:
            status = TransactionStatus.PENDING

        data = {
            "transaction_id": transaction.transaction_id,
            "status": status.value,
            "changes": [
                self._serialize_change(change)
                for change in getattr(transaction, "changes", [])
            ],
            "metadata": dict(getattr(transaction, "metadata", {})),
            "repair_state": dict(getattr(transaction, "repair_state", {})),
        }

        fd, temporary_name = tempfile.mkstemp(
            prefix=".transaction.",
            suffix=".tmp",
            dir=str(manifest.parent),
        )
        temporary = Path(temporary_name)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, manifest)

            parent_fd = os.open(
                str(manifest.parent),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def load_manifest(self, transaction_id):
        manifest = self._manifest_path(transaction_id)

        try:
            raw = manifest.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(
                "Manifesto de transação inválido."
            ) from error

        if not isinstance(data, dict):
            raise ValueError("Manifesto de transação inválido.")

        if data.get("transaction_id") != transaction_id:
            raise ValueError(
                "transaction_id inconsistente no manifesto."
            )

        changes = data.get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("Campo 'changes' inválido no manifesto.")

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Campo 'metadata' inválido no manifesto.")

        repair_state = data.get("repair_state", {})
        if not isinstance(repair_state, dict):
            raise ValueError(
                "Campo 'repair_state' inválido no manifesto."
            )

        return Transaction(
            transaction_id=transaction_id,
            status=TransactionStatus(
                data.get("status", TransactionStatus.PENDING.value)
            ),
            changes=[
                self._deserialize_change(change)
                for change in changes
            ],
            metadata=dict(metadata),
            repair_state=dict(repair_state),
        )

    def list_recoverable_transactions(self):
        transactions = []

        if not self.backup_dir.exists():
            return transactions

        for manifest in self.backup_dir.glob("*.json"):
            if manifest.is_symlink() or not manifest.is_file():
                continue

            transaction_id = manifest.name[:-5]
            if not transaction_id:
                continue

            try:
                transactions.append(
                    self.load_manifest(transaction_id)
                )
            except ValueError:
                continue

        return transactions

    def recover_incomplete_transactions(self):
        recovered = []

        for transaction in self.list_recoverable_transactions():
            if transaction.status not in (
                TransactionStatus.EXECUTING,
                TransactionStatus.TESTING,
            ):
                continue

            try:
                self.rollback(transaction)
            except Exception as error:
                transaction.status = TransactionStatus.FAILED
                transaction.metadata["recovery_error"] = str(error)
                self.persist_manifest(transaction)

            recovered.append(transaction)

        return recovered

    def _create_backup_directory(self, parent_fd, backup_name):
        try:
            try:
                os.mkdir(
                    backup_name,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                pass
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise ValueError(
                        "Diretório de backup inválido."
                    ) from error

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

        return backup_parent_fd

    def _create_transaction_directory(
        self,
        backup_parent_fd,
        transaction,
    ):
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
        except FileExistsError:
            if transaction.transaction_id == "unused":
                raise ValueError(
                    "Diretório de backup já existe ou não é seguro."
                )

            transaction.transaction_id = str(uuid.uuid4())

            try:
                os.mkdir(
                    transaction.transaction_id,
                    dir_fd=backup_parent_fd,
                )
            except OSError as error:
                if error.errno in (
                    errno.ELOOP,
                    errno.ENOTDIR,
                    errno.EEXIST,
                ):
                    raise ValueError(
                        "Diretório de backup já existe ou não é seguro."
                    ) from error
                raise
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                raise ValueError(
                    "Diretório de backup já existe ou não é seguro."
                ) from error
            raise

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

    def begin(self, transaction):
        if not getattr(transaction, "transaction_id", None) or transaction.transaction_id == "unused":
            transaction.transaction_id = str(uuid.uuid4())

        transaction.status = TransactionStatus.EXECUTING

        backup_relative = self.backup_dir.relative_to(self.root)
        backup_parent_relative = backup_relative.parent
        backup_name = backup_relative.name

        parent_fd = self._open_directory_chain(
            self.root,
            backup_parent_relative.parts,
            create=True,
        )
        try:
            backup_parent_fd = self._create_backup_directory(
                parent_fd,
                backup_name,
            )
            try:
                self._create_transaction_directory(
                    backup_parent_fd,
                    transaction,
                )
            finally:
                os.close(backup_parent_fd)
        finally:
            os.close(parent_fd)

        backup = self.backup_dir / transaction.transaction_id
        transaction.metadata["backup"] = str(backup)
        transaction.metadata["created"] = []
        self.persist_manifest(transaction)
        return transaction

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
        relative_path: Path,
        *,
        create: bool = False,
    ) -> int:
        return SecureFileSystem.open_parent_directory(
            root,
            relative_path,
            create=create,
        )

    @staticmethod
    def _copy_file_no_follow(
        source_root: Path,
        source_relative: Path,
        destination_root: Path,
        destination_relative: Path,
        *,
        overwrite: bool = False,
    ) -> None:
        return SecureFileSystem.copy_file_no_follow(
            source_root,
            source_relative,
            destination_root,
            destination_relative,
            overwrite=overwrite,
        )

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
        self.persist_manifest(transaction)

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
        self.persist_manifest(transaction)

    def _validate_backup_root(self, transaction):
        expected_backup = (
            self.backup_dir / transaction.transaction_id
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

        return backup_root

    def _validate_created_file_path(self, relative_path):
        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        target = (self.root / relative).resolve()

        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        return relative

    def _get_created_file_identity(
        self,
        transaction,
        relative_path,
    ):
        expected_identity = transaction.metadata.get(
            "created_identity",
            {},
        ).get(relative_path, {})

        return (
            expected_identity.get("st_dev"),
            expected_identity.get("st_ino"),
        )

    def _remove_created_file(
        self,
        relative,
        expected_dev,
        expected_ino,
    ):
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
                return
            except OSError as error:
                if getattr(error, "errno", None) == errno.ELOOP:
                    raise ValueError(
                        "Caminho criado é um symlink: "
                        f"{relative}"
                    ) from error
                raise

            try:
                file_stat = os.fstat(file_fd)

                if not stat.S_ISREG(file_stat.st_mode):
                    raise ValueError(
                        "Caminho criado não é um arquivo regular: "
                        f"{relative}"
                    )

                if (
                    expected_dev is None
                    or expected_ino is None
                ):
                    os.unlink(
                        filename,
                        dir_fd=parent_fd,
                    )
                    self._fsync_directory(parent_fd)
                    return

                if (
                    file_stat.st_dev != expected_dev
                    or file_stat.st_ino != expected_ino
                ):
                    raise RuntimeError(
                        "Arquivo criado foi alterado durante a "
                        f"transação: {relative}"
                    )

                os.unlink(
                    filename,
                    dir_fd=parent_fd,
                )
                self._fsync_directory(parent_fd)
            finally:
                os.close(file_fd)
        finally:
            os.close(parent_fd)

    def _remove_created_files(self, transaction):
        created = transaction.metadata.get(
            "created",
            [],
        )

        for relative_path in created:
            expected_dev, expected_ino = (
                self._get_created_file_identity(
                    transaction,
                    relative_path,
                )
            )

            relative = self._validate_created_file_path(
                relative_path
            )

            self._remove_created_file(
                relative=relative,
                expected_dev=expected_dev,
                expected_ino=expected_ino,
            )


    def _restore_backup_files(self, backup_root):
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
                exist_ok=True,
            )

            self._copy_file_no_follow(
                backup_root,
                relative,
                self.root,
                relative,
                overwrite=True,
            )

    def rollback(self, transaction):
        backup_root = self._validate_backup_root(transaction)

        self._remove_created_files(transaction)
        self._restore_backup_files(
            backup_root,
        )

        transaction.status = (
            TransactionStatus.ROLLED_BACK
        )
        self.persist_manifest(transaction)

        return transaction
