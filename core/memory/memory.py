import json
from pathlib import Path
from datetime import datetime


class Memory:

    def __init__(self, path: str = "logs/memory.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self._save([])

    def _load(self):
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self, data):
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    def add(self, event: str, data=None):
        memory = self._load()

        memory.append({
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "data": data,
        })

        self._save(memory)

    def all(self):
        return self._load()

    def last(self, amount: int = 10):
        return self._load()[-amount:]

