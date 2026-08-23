from dataclasses import dataclass


@dataclass
class Command:
    raw: str
    action: str
    target: str
    instruction: str


class CommandParser:

    def parse(self, text: str) -> Command:
        text = text.strip()

        if not text:
            raise ValueError("Comando vazio.")

        lowered = text.lower()

        if lowered.startswith("crie "):
            action = "create"
        elif lowered.startswith("criar "):
            action = "create"
        elif lowered.startswith("modifique "):
            action = "modify"
        elif lowered.startswith("modificar "):
            action = "modify"
        elif lowered.startswith("altere "):
            action = "modify"
        elif lowered.startswith("delete "):
            action = "delete"
        elif lowered.startswith("apague "):
            action = "delete"
        elif lowered.startswith("remova "):
            action = "delete"
        else:
            action = "analyze"

        words = text.split(maxsplit=1)

        if len(words) == 1:
            instruction = ""
        else:
            instruction = words[1]

        target = ""

        if action in {"create", "modify", "delete"}:
            parts = instruction.split(maxsplit=1)

            if parts:
                target = parts[0]

                if len(parts) > 1:
                    instruction = parts[1]
                else:
                    instruction = ""

        return Command(
            raw=text,
            action=action,
            target=target,
            instruction=instruction,
        )
