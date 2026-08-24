from pathlib import Path


class SecurityPolicy:

    ALLOWED_EXTENSIONS = {
        ".py",
        ".json",
        ".txt",
        ".md",
        ".yaml",
        ".yml",
        ".toml",
    }

    BLOCKED_PATHS = {
        ".git",
        ".ssh",
        ".env",
        "secrets",
    }

    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def validate_path(self, path):

        target = (self.root / path).resolve()

        if not str(target).startswith(
            str(self.root)
        ):
            raise PermissionError(
                "Caminho fora do projeto."
            )

        parts = target.relative_to(
            self.root
        ).parts

        for part in parts:
            if part in self.BLOCKED_PATHS:
                raise PermissionError(
                    f"Caminho bloqueado: {path}"
                )

        if target.suffix not in self.ALLOWED_EXTENSIONS:
            raise PermissionError(
                f"Extensão não permitida: {target.suffix}"
            )

        return True
