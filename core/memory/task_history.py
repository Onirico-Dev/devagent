from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from core.memory.persistent_store import PersistentStore


class TaskHistoryStatus(str, Enum):
    PENDING = "pending"
    REPAIRING = "repairing"
    EXECUTING = "executing"
    TESTING = "testing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskHistory:
    REQUIRED_FIELDS = {
        "task_id",
        "approval_id",
        "instruction",
        "plan",
        "status",
        "transaction_id",
        "created_at",
        "updated_at",
    }

    def __init__(
        self,
        storage_path="transactions/tasks.json",
    ):
        self.storage_path = Path(storage_path).resolve()
        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.store = PersistentStore(self.storage_path)
        self.tasks = {}
        self._load()

    def _now(self):
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self):
        data = self.store.load(default={})

        if not isinstance(data, dict):
            self.tasks = {}
            return

        valid_statuses = {
            status.value
            for status in TaskHistoryStatus
        }

        legacy_completed_status = "completed"
        accepted_statuses = valid_statuses | {
            "completed",
            "approved",
        }

        valid_tasks = {}

        for key, task in data.items():
            if not isinstance(task, dict):
                continue

            status = task.get("status")
            if status not in accepted_statuses:
                continue

            task_id = task.get("task_id")
            updated_at = task.get("updated_at")

            if not isinstance(task_id, str) or not task_id.strip():
                continue

            if not isinstance(updated_at, str) or not updated_at.strip():
                continue

            if status == legacy_completed_status:
                valid_tasks[str(key)] = task
                continue

            if not self.REQUIRED_FIELDS.issubset(task):
                continue

            if str(task_id) != str(key):
                continue

            if not isinstance(task.get("approval_id"), str):
                continue

            if not isinstance(task.get("instruction"), str):
                continue

            if not isinstance(task.get("plan"), dict):
                continue

            transaction_id = task.get("transaction_id")
            if (
                transaction_id is not None
                and not isinstance(transaction_id, str)
            ):
                continue

            created_at = task.get("created_at")
            if not isinstance(created_at, str) or not created_at.strip():
                continue

            valid_tasks[str(key)] = task

        self.tasks = valid_tasks

    def create(
        self,
        approval_id,
        instruction,
        plan,
    ):
        task_id = str(approval_id)
        now = self._now()

        task = {
            "task_id": task_id,
            "approval_id": task_id,
            "instruction": instruction,
            "plan": plan,
            "status": TaskHistoryStatus.PENDING.value,
            "transaction_id": None,
            "created_at": now,
            "updated_at": now,
        }

        def add_task(data):
            if not isinstance(data, dict):
                data = {}

            if task_id in data:
                raise ValueError(
                    "Tarefa já existe."
                )

            updated = dict(data)
            updated[task_id] = task
            return updated

        updated_tasks = self.store.update(
            add_task,
            default={},
        )

        if not isinstance(updated_tasks, dict):
            raise RuntimeError(
                "Estado persistido de tarefas inválido."
            )

        self.tasks = dict(updated_tasks)

        return task

    def update(
        self,
        task_id,
        status=None,
        transaction_id=None,
        extra=None,
    ):
        task_id = str(task_id)

        def update_task(data):
            if not isinstance(data, dict):
                data = {}

            task = data.get(task_id)

            if task is None:
                raise KeyError(
                    "Tarefa não encontrada."
                )

            updated_task = {
                **task,
            }

            if status is not None:
                valid_statuses = {
                    lifecycle_status.value
                    for lifecycle_status in TaskHistoryStatus
                }
                valid_statuses.add("completed")

                if status not in valid_statuses:
                    raise ValueError(
                        "status inválido"
                    )

                updated_task["status"] = status

            if transaction_id is not None:
                updated_task["transaction_id"] = transaction_id

            if extra is not None:
                if not isinstance(extra, dict):
                    raise TypeError(
                        "extra deve ser um dicionário"
                    )

                structural_fields = {
                    "task_id",
                    "approval_id",
                    "instruction",
                    "plan",
                    "status",
                    "transaction_id",
                    "created_at",
                    "updated_at",
                }

                if structural_fields.intersection(extra):
                    raise ValueError(
                        "Campos estruturais não podem ser sobrescritos"
                    )

                updated_task.update(extra)

            updated_task["updated_at"] = self._now()

            updated_tasks = dict(data)
            updated_tasks[task_id] = updated_task

            return updated_tasks

        updated_tasks = self.store.update(
            update_task,
            default={},
        )

        if not isinstance(updated_tasks, dict):
            raise RuntimeError(
                "Estado persistido de tarefas inválido."
            )

        self.tasks = dict(updated_tasks)

        return dict(updated_tasks[task_id])

    def get(self, task_id):
        return self.tasks.get(str(task_id))

    def list_all(self):
        return list(self.tasks.values())

    def list_pending(self):
        return [
            task
            for task in self.tasks.values()
            if task["status"] == TaskHistoryStatus.PENDING.value
        ]

    def latest(self):
        tasks = self.list_all()

        if not tasks:
            return None

        return max(
            tasks,
            key=lambda task: task.get(
                "updated_at",
                "",
            ),
        )
