from pathlib import Path
import fcntl
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
            change_type = ChangeType(data["change_type"])
            path = data["path"]
            content = data.get("content")
            reason = data.get("reason", "")

            if not isinstance(path, str):
                raise ValueError("path deve ser uma string.")

            if content is not None and not isinstance(content, str):
                raise ValueError("content deve ser uma string ou None.")

            if not isinstance(reason, str):
                raise ValueError("reason deve ser uma string.")

            return Change(
                change_type=change_type,
                path=path,
                content=content,
                reason=reason,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Change inválido no manifesto.") from error

    def _build_manifest_data(self, transaction):
        status = getattr(transaction, "status", None)
        if status is None:
            status = TransactionStatus.PENDING

        return {
            "transaction_id": transaction.transaction_id,
            "status": status.value,
            "changes": [
                self._serialize_change(change)
                for change in getattr(transaction, "changes", [])
            ],
            "metadata": dict(getattr(transaction, "metadata", {})),
            "repair_state": dict(getattr(transaction, "repair_state", {})),
        }

    def _write_manifest_atomically(self, manifest, data):
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

    def persist_manifest(self, transaction):
        manifest = self._manifest_path(transaction.transaction_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        data = self._build_manifest_data(transaction)
        self._write_manifest_atomically(manifest, data)

    def _read_manifest_data(self, manifest):
        try:
            raw = manifest.read_text(encoding="utf-8")
            return json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(
                "Manifesto de transação inválido."
            ) from error

    def _validate_manifest_data(self, data, transaction_id):
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

        backup = metadata.get("backup")
        if backup is not None and not isinstance(backup, str):
            raise ValueError(
                "Campo 'metadata.backup' inválido no manifesto."
            )

        created = metadata.get("created")
        if created is not None:
            if not isinstance(created, list):
                raise ValueError(
                    "Campo 'metadata.created' inválido no manifesto."
                )
            if not all(isinstance(path, str) for path in created):
                raise ValueError(
                    "Campo 'metadata.created' inválido no manifesto."
                )

        created_identity = metadata.get("created_identity")
        if created_identity is not None:
            if not isinstance(created_identity, dict):
                raise ValueError(
                    "Campo 'metadata.created_identity' inválido no manifesto."
                )

            for relative_path, identity in created_identity.items():
                if not isinstance(relative_path, str):
                    raise ValueError(
                        "Campo 'metadata.created_identity' inválido no manifesto."
                    )
                if not isinstance(identity, dict):
                    raise ValueError(
                        "Campo 'metadata.created_identity' inválido no manifesto."
                    )

                for field in ("st_dev", "st_ino"):
                    value = identity.get(field)
                    if value is not None and (
                        not isinstance(value, int)
                        or isinstance(value, bool)
                    ):
                        raise ValueError(
                            "Campo 'metadata.created_identity' inválido "
                            "no manifesto."
                        )

        repair_state = data.get("repair_state", {})
        if not isinstance(repair_state, dict):
            raise ValueError(
                "Campo 'repair_state' inválido no manifesto."
            )

        return changes, metadata, repair_state

    def _build_transaction_from_manifest(
        self,
        transaction_id,
        data,
        changes,
        metadata,
        repair_state,
    ):
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

    def load_manifest(self, transaction_id):
        manifest = self._manifest_path(transaction_id)
        data = self._read_manifest_data(manifest)
        changes, metadata, repair_state = self._validate_manifest_data(
            data,
            transaction_id,
        )

        transaction = self._build_transaction_from_manifest(
            transaction_id,
            data,
            changes,
            metadata,
            repair_state,
        )

        for change in transaction.changes:
            self._safe_path(change.path)

        return transaction

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
                transaction = self.load_manifest(transaction_id)
                if transaction.status not in (
                    TransactionStatus.EXECUTING,
                    TransactionStatus.TESTING,
                ):
                    continue
                transactions.append(transaction)
            except ValueError:
                continue

        return transactions

    def list_terminal_transactions(self):
        transactions = []

        if not self.backup_dir.exists():
            return transactions

        terminal_statuses = {
            TransactionStatus.COMMITTED,
            TransactionStatus.ROLLED_BACK,
            TransactionStatus.FAILED,
        }

        for manifest in self.backup_dir.glob("*.json"):
            if manifest.is_symlink() or not manifest.is_file():
                continue

            transaction_id = manifest.name[:-5]
            if not transaction_id:
                continue

            try:
                transaction = self.load_manifest(transaction_id)
            except ValueError:
                continue

            if transaction.status in terminal_statuses:
                transactions.append(transaction)

        return transactions

    def _recovery_lock(self, transaction_id):
        lock_path = self.backup_dir / (
            f".{transaction_id}.recovery.lock"
        )
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _recover_transaction(self, current, commit_detector):
        if commit_detector is not None:
            commit_result = commit_detector(current.transaction_id)
            if commit_result is not None:
                valid_result = (
                    isinstance(commit_result, dict)
                    and commit_result.get("status") == "committed"
                    and commit_result.get("transaction_id") == current.transaction_id
                    and isinstance(commit_result.get("commit_hash"), str)
                    and bool(commit_result["commit_hash"].strip())
                )
                if not valid_result:
                    raise ValueError(
                        "evidência de commit inválida durante recuperação"
                    )
                self.transition(current, TransactionStatus.COMMITTED)
                current.metadata["recovery"] = True
                current.metadata["recovery_git"] = dict(commit_result)
                self.persist_manifest(current)
                return current

        try:
            self.rollback(current)
        except Exception as error:
            self.transition(current, TransactionStatus.FAILED)
            current.metadata["recovery"] = True
            current.metadata["recovery_error"] = str(error)
            self.persist_manifest(current)
            return current

        current.metadata["recovery"] = True
        self.persist_manifest(current)
        return current

    def recover_incomplete_transactions(
        self, commit_detector=None, recovery_guard=None
    ):
        recovered = []
        first_error = None
        first_traceback = None

        def record_error(error):
            nonlocal first_error, first_traceback
            if first_error is None:
                first_error = error
                first_traceback = error.__traceback__

        for transaction in self.list_recoverable_transactions():
            lock = None
            try:
                lock = self._recovery_lock(transaction.transaction_id)
                current = self.load_manifest(transaction.transaction_id)
                if current.status not in (
                    TransactionStatus.EXECUTING,
                    TransactionStatus.TESTING,
                ):
                    continue

                guard = (
                    recovery_guard(current)
                    if recovery_guard is not None
                    else None
                )
                if guard is not None:
                    with guard:
                        current = self.load_manifest(
                            transaction.transaction_id
                        )
                        if current.status not in (
                            TransactionStatus.EXECUTING,
                            TransactionStatus.TESTING,
                        ):
                            continue
                        recovered.append(
                            self._recover_transaction(
                                current, commit_detector
                            )
                        )
                else:
                    recovered.append(
                        self._recover_transaction(current, commit_detector)
                    )
            except Exception as error:
                record_error(error)
            finally:
                if lock is not None:
                    try:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                    except Exception as error:
                        record_error(error)
                    try:
                        lock.close()
                    except Exception as error:
                        record_error(error)

        if first_error is not None:
            raise first_error.with_traceback(first_traceback)

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

    def _validate_backup_parent_directory(self, backup_parent_fd):
        backup_stat = os.fstat(backup_parent_fd)

        if not stat.S_ISDIR(backup_stat.st_mode):
            raise ValueError(
                "Diretório de backup inválido."
            )

    def _create_transaction_directory_entry(
        self,
        backup_parent_fd,
        transaction,
    ):
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
            if error.errno in (
                errno.ELOOP,
                errno.ENOTDIR,
            ):
                raise ValueError(
                    "Diretório de backup já existe ou não é seguro."
                ) from error
            raise

    def _validate_transaction_directory(
        self,
        backup_parent_fd,
        transaction,
    ):
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

    def _create_transaction_directory(
        self,
        backup_parent_fd,
        transaction,
    ):
        self._validate_backup_parent_directory(
            backup_parent_fd
        )

        self._create_transaction_directory_entry(
            backup_parent_fd,
            transaction,
        )

        self._validate_transaction_directory(
            backup_parent_fd,
            transaction,
        )


    _ALLOWED_TRANSITIONS = {
        TransactionStatus.PENDING: {
            TransactionStatus.EXECUTING,
        },
        TransactionStatus.EXECUTING: {
            TransactionStatus.TESTING,
            TransactionStatus.COMMITTED,
            TransactionStatus.ROLLED_BACK,
            TransactionStatus.FAILED,
        },
        TransactionStatus.TESTING: {
            TransactionStatus.COMMITTED,
            TransactionStatus.ROLLED_BACK,
            TransactionStatus.FAILED,
        },
        TransactionStatus.FAILED: {
            TransactionStatus.ROLLED_BACK,
        },
        TransactionStatus.COMMITTED: set(),
        TransactionStatus.ROLLED_BACK: set(),
    }

    def transition(self, transaction, new_status):
        current_status = transaction.status
        if current_status is None:
            current_status = TransactionStatus.PENDING

        if current_status == new_status:
            return transaction

        allowed = self._ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Transição de estado inválida: "
                f"{current_status.value} -> {new_status.value}"
            )

        transaction.status = new_status
        return transaction

    def begin(self, transaction):
        if (
            not getattr(transaction, "transaction_id", None)
            or transaction.transaction_id == "unused"
        ):
            transaction.transaction_id = str(uuid.uuid4())

        self.transition(transaction, TransactionStatus.EXECUTING)

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

        try:
            self.persist_manifest(transaction)
        except Exception:
            try:
                backup.rmdir()
            except OSError:
                pass
            raise

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

    def _validate_backup_path(self, relative_path):
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )
        return relative

    def _resolve_transaction_backup_directory(self, transaction):
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

        return backup_dir

    def _resolve_backup_source(self, relative, relative_path):
        source = (self.root / relative).resolve()
        try:
            source.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        if not source.exists():
            return None

        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"Caminho não é um arquivo: {relative_path}"
            )

        return source

    def _validate_backup_destination(
        self,
        backup_dir,
        relative,
        relative_path,
    ):
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

        return destination

    def backup_file(self, transaction, relative_path: str) -> None:
        relative = self._validate_backup_path(relative_path)
        backup_dir = self._resolve_transaction_backup_directory(
            transaction
        )
        source = self._resolve_backup_source(
            relative,
            relative_path,
        )
        if source is None:
            return

        destination = self._validate_backup_destination(
            backup_dir,
            relative,
            relative_path,
        )
        if destination.exists():
            return

        self._copy_file_no_follow(
            self.root,
            relative,
            backup_dir,
            relative,
        )
        try:
            self.persist_manifest(transaction)
        except Exception:
            try:
                destination.unlink()
            except OSError:
                pass
            raise

    def _validate_created_path(self, relative_path):
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

        if target.exists() and target.is_dir():
            raise ValueError(
                f"Caminho aponta para um diretório: {relative_path}"
            )

        return target


    def record_created_identity(self, transaction, relative_path):
        relative = str(self._validate_created_file_path(relative_path))
        target = self.root / relative

        if target.is_symlink():
            raise ValueError(
                f"Caminho criado é um symlink: {relative}"
            )

        if not target.exists() or not target.is_file():
            return

        created_identity = transaction.metadata.setdefault(
            "created_identity",
            {},
        )
        identity_before = dict(created_identity)

        self._record_created_identity(
            transaction,
            relative,
            target,
        )

        try:
            self.persist_manifest(transaction)
        except Exception:
            transaction.metadata["created_identity"] = identity_before
            raise

    def _record_created_path(self, transaction, relative_path):
        transaction.metadata["created"].append(relative_path)


    def _record_created_identity(
        self,
        transaction,
        relative_path,
        target,
    ):
        if not target.exists() or not target.is_file():
            return

        file_stat = target.stat()

        transaction.metadata.setdefault(
            "created_identity",
            {},
        )[relative_path] = {
            "st_dev": file_stat.st_dev,
            "st_ino": file_stat.st_ino,
        }


    def register_created(
        self,
        transaction,
        relative_path
    ):
        target = self._validate_created_path(relative_path)

        created = transaction.metadata.setdefault(
            "created",
            [],
        )
        created_identity = transaction.metadata.setdefault(
            "created_identity",
            {},
        )

        created_before = list(created)
        identity_before = dict(created_identity)

        self._record_created_path(transaction, relative_path)
        self._record_created_identity(
            transaction,
            relative_path,
            target,
        )

        try:
            self.persist_manifest(transaction)
        except Exception:
            transaction.metadata["created"] = created_before
            transaction.metadata["created_identity"] = identity_before
            raise

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
        ).get(str(relative_path), {})

        return (
            expected_identity.get("st_dev"),
            expected_identity.get("st_ino"),
        )

    def validate_created_identity(self, transaction, relative_path):
        relative = self._validate_created_file_path(relative_path)
        expected_dev, expected_ino = self._get_created_file_identity(
            transaction,
            relative,
        )

        parent_fd = self._open_parent_directory(
            self.root,
            relative,
        )
        try:
            file_fd = self._open_created_file(parent_fd, relative)
            if file_fd is None:
                raise RuntimeError(
                    "Arquivo criado não existe durante a transação: "
                    f"{relative}"
                )
            try:
                file_stat = self._validate_created_file(
                    file_fd,
                    relative,
                )
                self._validate_created_identity(
                    file_stat,
                    relative,
                    expected_dev,
                    expected_ino,
                )
            finally:
                os.close(file_fd)
        finally:
            os.close(parent_fd)

    def _open_created_file(self, parent_fd, relative):
        filename = relative.name

        try:
            return os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            if getattr(error, "errno", None) == errno.ELOOP:
                raise ValueError(
                    "Caminho criado é um symlink: "
                    f"{relative}"
                ) from error
            raise


    def _validate_created_file(self, file_fd, relative):
        file_stat = os.fstat(file_fd)

        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(
                "Caminho criado não é um arquivo regular: "
                f"{relative}"
            )

        return file_stat


    def _validate_created_identity(
        self,
        file_stat,
        relative,
        expected_dev,
        expected_ino,
    ):
        if expected_dev is None or expected_ino is None:
            raise RuntimeError(
                "Identidade do arquivo criado não foi registrada: "
                f"{relative}"
            )

        if (
            file_stat.st_dev != expected_dev
            or file_stat.st_ino != expected_ino
        ):
            raise RuntimeError(
                "Arquivo criado foi alterado durante a "
                f"transação: {relative}"
            )


    def _unlink_created_file(self, parent_fd, relative):
        os.unlink(
            relative.name,
            dir_fd=parent_fd,
        )
        self._fsync_directory(parent_fd)


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
            file_fd = self._open_created_file(
                parent_fd,
                relative,
            )
            if file_fd is None:
                return

            try:
                file_stat = self._validate_created_file(
                    file_fd,
                    relative,
                )
                self._validate_created_identity(
                    file_stat,
                    relative,
                    expected_dev,
                    expected_ino,
                )
                self._unlink_created_file(
                    parent_fd,
                    relative,
                )
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

        self.transition(transaction, TransactionStatus.ROLLED_BACK)
        self.persist_manifest(transaction)

        return transaction
