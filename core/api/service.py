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
        return {
            "status": "ok",
            "service": "devagent",
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

    def create_task(self, instruction):
        self.gateway.agent = self.agent
        return self.gateway.create_task(instruction)

    def approve(self, approval_id):
        return self.gateway.approve(approval_id)

    def reject(self, approval_id):
        return self.gateway.reject(approval_id)
