from pathlib import Path

from core.memory.persistent_store import PersistentStore


class Session:
    DEFAULT_STATE = {
        "instructions": [],
        "plans": [],
    }

    def __init__(self, path="logs/session.json"):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.store = PersistentStore(self.path)

        if not self.path.exists():
            self.store.save(self._default_state())

    @classmethod
    def _default_state(cls):
        return {
            "instructions": [],
            "plans": [],
        }

    def load(self):
        data = self.store.load(default=self._default_state())

        if not isinstance(data, dict):
            raise ValueError(
                "A sessão persistida deve ser um objeto JSON."
            )

        instructions = data.get("instructions", [])
        plans = data.get("plans", [])

        if not isinstance(instructions, list):
            raise ValueError(
                "instructions persistido deve ser uma lista."
            )

        if not isinstance(plans, list):
            raise ValueError(
                "plans persistido deve ser uma lista."
            )

        return {
            **data,
            "instructions": instructions,
            "plans": plans,
        }

    def save(self, data):
        if not isinstance(data, dict):
            raise ValueError("A sessão deve ser um objeto JSON.")

        normalized = {
            **data,
            "instructions": data.get("instructions", []),
            "plans": data.get("plans", []),
        }

        if not isinstance(normalized["instructions"], list):
            raise ValueError("instructions deve ser uma lista.")

        if not isinstance(normalized["plans"], list):
            raise ValueError("plans deve ser uma lista.")

        self.store.save(normalized)

    def add_instruction(self, instruction):
        def append_instruction(data):
            if not isinstance(data, dict):
                raise ValueError(
                    "A sessão persistida deve ser um objeto JSON."
                )

            instructions = data.get("instructions", [])

            if not isinstance(instructions, list):
                raise ValueError(
                    "instructions persistido deve ser uma lista."
                )

            data = {
                **data,
                "instructions": [
                    *instructions,
                    instruction,
                ],
            }

            return data

        self.store.update(
            append_instruction,
            default=self._default_state(),
        )

    def add_plan(self, plan):
        def append_plan(data):
            if not isinstance(data, dict):
                raise ValueError(
                    "A sessão persistida deve ser um objeto JSON."
                )

            plans = data.get("plans", [])

            if not isinstance(plans, list):
                raise ValueError(
                    "plans persistido deve ser uma lista."
                )

            data = {
                **data,
                "plans": [
                    *plans,
                    plan,
                ],
            }

            return data

        self.store.update(
            append_plan,
            default=self._default_state(),
        )

    @property
    def instructions(self):
        return self.load()["instructions"]

    @property
    def plans(self):
        return self.load()["plans"]

    def context(self):
        return self.load()
