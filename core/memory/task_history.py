import json
from datetime import datetime, timezone
from pathlib import Path


class TaskHistory:

    def __init__(
        self,
        storage_path="transactions/tasks.json",
    ):

        self.storage_path = Path(
            storage_path
        ).resolve()

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.tasks = {}

        self._load()

    def _now(self):

        return datetime.now(
            timezone.utc
        ).isoformat()

    def _load(self):

        if not self.storage_path.exists():
            self.tasks = {}
            return

        try:

            data = json.loads(
                self.storage_path.read_text(
                    encoding="utf-8"
                )
            )

            self.tasks = (
                data
                if isinstance(data, dict)
                else {}
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            self.tasks = {}

    def _save(self):

        temporary = self.storage_path.with_suffix(
            ".tmp"
        )

        temporary.write_text(
            json.dumps(
                self.tasks,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary.replace(
            self.storage_path
        )

    def create(
        self,
        approval_id,
        instruction,
        plan,
    ):

        task_id = str(
            approval_id
        )

        self.tasks[task_id] = {
            "task_id": task_id,
            "approval_id": task_id,
            "instruction": instruction,
            "plan": plan,
            "status": "pending",
            "transaction_id": None,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

        self._save()

        return self.tasks[task_id]

    def update(
        self,
        task_id,
        status=None,
        transaction_id=None,
        extra=None,
    ):

        task = self.tasks.get(
            str(task_id)
        )

        if task is None:
            raise KeyError(
                "Tarefa não encontrada."
            )

        if status is not None:
            task["status"] = status

        if transaction_id is not None:
            task["transaction_id"] = (
                transaction_id
            )

        if extra:
            task.update(extra)

        task["updated_at"] = self._now()

        self._save()

        return task

    def get(self, task_id):

        return self.tasks.get(
            str(task_id)
        )

    def list_all(self):

        return list(
            self.tasks.values()
        )

    def list_pending(self):

        return [
            task
            for task in self.tasks.values()
            if task["status"] == "pending"
        ]

    def latest(self):

        tasks = self.list_all()

        if not tasks:
            return None

        return max(
            tasks,
            key=lambda task: task.get(
                "updated_at",
                ""
            ),
        )
