from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Observation:
    instruction: str
    metadata: dict[str, Any]
