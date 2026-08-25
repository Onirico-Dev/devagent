from datetime import datetime, timezone
from pathlib import Path

from core.memory.persistent_store import PersistentStore


class Memory:
    def __init__(self, path: str = "logs/memory.json"):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.store = PersistentStore(self.path)

        if not self.path.exists():
            self.store.save([])

    def _load(self):
        data = self.store.load(default=[])

        if not isinstance(data, list):
            return []

        return data

    def _save(self, data):
        if not isinstance(data, list):
            raise ValueError("A memória deve ser uma lista.")

        self.store.save(data)

    def add(self, event: str, data=None):
        if not isinstance(event, str) or not event.strip():
            raise ValueError("O evento da memória não pode ser vazio.")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "data": data,
        }

        def append_event(memory):
            if not isinstance(memory, list):
                memory = []

            memory.append(entry)
            return memory

        self.store.update(
            append_event,
            default=[],
        )

    def all(self):
        return self._load()

    def last(self, amount: int = 10):
        if not isinstance(amount, int):
            raise TypeError("amount deve ser um inteiro.")

        if amount < 0:
            raise ValueError("amount não pode ser negativo.")

        return self._load()[-amount:] if amount else []
