import json
from pathlib import Path


class Session:

    def __init__(self, path="logs/session.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self.save({
                "instructions": [],
                "plans": []
            })

    def load(self):
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save(self, data):
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False
            )

    def add_instruction(self, instruction):
        data = self.load()
        data["instructions"].append(instruction)
        self.save(data)

    def add_plan(self, plan):
        data = self.load()
        data["plans"].append(plan)
        self.save(data)

    def context(self):
        return self.load()
