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

        try:
            self.backup_dir.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Diretório de backup fora do projeto: {backup_dir}"
            ) from error

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
        relative = Path(relative_path)

        if relative.is_absolute():
            raise ValueError(
                f"Caminho absoluto não permitido: {relative_path}"
            )

        source = (
            self.root / relative
        ).resolve()

        try:
            source.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                f"Caminho fora do projeto: {relative_path}"
            ) from error

        if not source.exists():
            return

        if not source.is_file():
            raise ValueError(
                f"Caminho não é um arquivo: {relative_path}"
            )

        backup_root = Path(
            transaction.metadata["backup"]
        ).resolve()

        try:
            backup_root.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                "Diretório de backup fora do projeto."
            ) from error

        destination = (
            backup_root / relative
        ).resolve()

        try:
            destination.relative_to(backup_root)
        except ValueError as error:
            raise ValueError(
                f"Caminho de backup inválido: {relative_path}"
            ) from error

        # Um arquivo só pode ter um backup por transação.
        # Nunca sobrescrever o primeiro estado original.
        if destination.exists():
            return

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

        # O diretório de backup deve permanecer dentro do projeto.
        try:
            backup_root.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                "Diretório de backup fora do projeto."
            ) from error

        # Remove arquivos criados durante a transação.
        for relative_path in transaction.metadata.get(
            "created",
            []
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

            # Não seguir symlink durante rollback.
            raw_target = self.root / relative

            if raw_target.is_symlink():
                raise ValueError(
                    f"Caminho criado é um symlink: {relative_path}"
                )

            if target.exists() and target.is_file():
                target.unlink()

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

            try:
                destination.relative_to(self.root)
            except ValueError as error:
                raise ValueError(
                    f"Destino de rollback fora do projeto: {relative}"
                ) from error

            raw_destination = self.root / relative

            if raw_destination.is_symlink():
                raise ValueError(
                    f"Destino de rollback é um symlink: {relative}"
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
