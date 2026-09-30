from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeType(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    TESTING = "testing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass(frozen=True)
class TestResult:
    success: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestResult":
        if not isinstance(data, dict):
            raise ValueError("Resultado de testes inválido.")

        success = data.get("success", False)
        if not isinstance(success, bool):
            raise ValueError("O campo success do resultado de testes deve ser booleano.")

        returncode = data.get("returncode", 0 if success else 1)
        if not isinstance(returncode, int):
            raise ValueError("O campo returncode do resultado de testes deve ser inteiro.")

        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")

        if not isinstance(stdout, str):
            raise ValueError("stdout do resultado de testes deve ser uma string.")
        if not isinstance(stderr, str):
            raise ValueError("stderr do resultado de testes deve ser uma string.")

        return cls(
            success=success,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    @classmethod
    def combine_many(
        cls,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not results:
            return cls(
                success=True,
                returncode=0,
            ).to_dict()

        combined = cls.from_dict(results[0])

        for result in results[1:]:
            combined = cls.from_dict(
                cls.combine(
                    combined.to_dict(),
                    result,
                )
            )

        return combined.to_dict()

    @classmethod
    def combine(
        cls,
        primary: dict[str, Any],
        secondary: dict[str, Any],
    ) -> dict[str, Any]:
        first = cls.from_dict(primary)
        second = cls.from_dict(secondary)

        success = first.success and second.success

        return cls(
            success=success,
            returncode=(
                second.returncode
                if not second.success
                else first.returncode
            ),
            stdout="\n".join(
                part
                for part in (first.stdout, second.stdout)
                if part
            ),
            stderr="\n".join(
                part
                for part in (first.stderr, second.stderr)
                if part
            ),
        ).to_dict()


@dataclass
class FileInfo:
    path: str
    exists: bool
    is_file: bool
    is_directory: bool
    size: int = 0


@dataclass
class Change:
    change_type: ChangeType
    path: str
    content: str | None = None
    reason: str = ""


@dataclass
class Plan:
    objective: str
    changes: list[Change] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        if not isinstance(data, dict):
            raise ValueError("Plano inválido.")

        changes = [
            Change(
                change_type=ChangeType(change["change_type"]),
                path=change["path"],
                content=change.get("content"),
                reason=change.get("reason", ""),
            )
            for change in data.get("changes", [])
        ]

        return cls(
            objective=data["objective"],
            changes=changes,
            tests=list(data.get("tests", [])),
            risks=list(data.get("risks", [])),
        )


@dataclass
class Transaction:
    transaction_id: str
    status: TransactionStatus = TransactionStatus.PENDING
    changes: list[Change] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    repair_state: dict[str, Any] = field(default_factory=dict)
