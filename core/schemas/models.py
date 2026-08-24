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


@dataclass
class Transaction:
    transaction_id: str
    status: TransactionStatus = TransactionStatus.PENDING
    changes: list[Change] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
