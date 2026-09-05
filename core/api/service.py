class APIService:
    """Application-facing operations exposed by the HTTP API."""

    def __init__(self, agent, gateway):
        self.agent = agent
        self.gateway = gateway

    def health(self):
        return {
            "status": "ok",
            "service": "devagent",
        }

    def list_tasks(self):
        return self.gateway.list_tasks()

    def latest_task(self):
        return self.gateway.latest_task()

    def get_task(self, task_id):
        return self.gateway.get_task(task_id)

    def create_task(self, instruction):
        self.gateway.agent = self.agent
        return self.gateway.create_task(instruction)

    def approve(self, approval_id):
        return self.gateway.approve(approval_id)

    def reject(self, approval_id):
        return self.gateway.reject(approval_id)
