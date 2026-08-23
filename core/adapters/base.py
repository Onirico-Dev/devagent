from abc import ABC, abstractmethod


class AIAdapter(ABC):

    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass
