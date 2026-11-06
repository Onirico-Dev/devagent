from core.adapters.codex_adapter import CodexAdapter
from core.adapters.mock import MockAdapter
from core.adapters.groq import GroqAdapter
from core.api.task_diagnostic import diagnose_task
from core.api.task_investigation import TASK_INVESTIGATIONS


class APIService:
    """Application-facing operations exposed by the HTTP API."""

    PUBLIC_TASK_FIELDS = (
        "task_id",
        "approval_id",
        "instruction",
        "plan",
        "status",
        "transaction_id",
        "created_at",
        "updated_at",
        "tests",
        "git",
        "repair_attempts",
        "repair",
        "error",
        "rollback_error",
    )

    def __init__(self, agent, gateway):
        self.agent = agent
        self.gateway = gateway

    @classmethod
    def _public_task(cls, task):
        if task is None:
            return None

        return {
            key: task[key]
            for key in cls.PUBLIC_TASK_FIELDS
            if key in task
        }

    def health(self):
        adapter = getattr(self.agent, "ai", None)
        if isinstance(adapter, CodexAdapter):
            provider = "Codex"
        elif isinstance(adapter, MockAdapter):
            provider = "Mock"
        elif isinstance(adapter, GroqAdapter):
            provider = "Groq"
        else:
            provider = "Desconhecido"
        return {
            "status": "ok",
            "service": "devagent",
            "ai_provider": provider,
        }

    def list_tasks(self):
        return [
            self._public_task(task)
            for task in self.gateway.list_tasks()
        ]

    def latest_task(self):
        return self._public_task(
            self.gateway.latest_task()
        )

    def get_task(self, task_id):
        return self._public_task(
            self.gateway.get_task(task_id)
        )

    def task_diagnostic(self, task_id):
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.get("approval_id") != task_id:
            raise ValueError("A tarefa não corresponde ao identificador solicitado.")
        return {"approval_id": task_id, **diagnose_task(task)}

    def start_task_investigation(self, task_id):
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.get("approval_id") != task_id:
            raise ValueError("A tarefa não corresponde ao identificador solicitado.")
        return TASK_INVESTIGATIONS.start(task, getattr(self.agent, "ai", None), self.gateway)

    def get_task_investigation(self, task_id, job_id):
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.get("approval_id") != task_id:
            raise ValueError("A tarefa não corresponde ao identificador solicitado.")
        return TASK_INVESTIGATIONS.get(task, job_id, self.gateway)

    def create_task(self, instruction):
        self.gateway.agent = self.agent
        return self.gateway.create_task(instruction)

    def approve(self, approval_id):
        return self.gateway.approve(approval_id)

    def reject(self, approval_id):
        return self.gateway.reject(approval_id)
