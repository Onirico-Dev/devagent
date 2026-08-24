from pathlib import Path
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

    def begin(self, transaction):

        transaction.transaction_id = str(
            uuid.uuid4()
        )

        backup = (
            self.backup_dir /
            transaction.transaction_id
        )

        backup.mkdir(
            parents=True,
            exist_ok=True
        )

        transaction.metadata["backup"] = str(
            backup
        )

        transaction.metadata["created"] = []

        return transaction

    def backup_file(
        self,
        transaction,
        relative_path
    ):

        source = (
            self.root / relative_path
        ).resolve()

        if not source.exists():
            return

        backup_root = Path(
            transaction.metadata["backup"]
        )

        destination = (
            backup_root / relative_path
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        shutil.copy2(
            source,
            destination
        )

    def register_created(
        self,
        transaction,
        relative_path
    ):

        transaction.metadata[
            "created"
        ].append(relative_path)

    def rollback(self, transaction):

        backup_root = Path(
            transaction.metadata["backup"]
        )

        # Remove arquivos que foram criados
        # durante a transação.
        for relative_path in transaction.metadata.get(
            "created",
            []
        ):

            target = (
                self.root / relative_path
            ).resolve()

            if target.exists() and target.is_file():

                target.unlink()

        # Restaura arquivos antigos.
        if backup_root.exists():

            for backup_file in backup_root.rglob("*"):

                if not backup_file.is_file():
                    continue

                relative = (
                    backup_file.relative_to(
                        backup_root
                    )
                )

                destination = (
                    self.root / relative
                )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )

                shutil.copy2(
                    backup_file,
                    destination
                )

        transaction.status = (
            TransactionStatus.ROLLED_BACK
        )

        return transaction
