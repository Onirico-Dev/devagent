from pathlib import Path
import re


class SecurityPolicy:
    ALLOWED_EXTENSIONS = {
        ".py", ".json", ".txt", ".md",
        ".yaml", ".yml", ".toml",
    }

    BLOCKED_PATHS = {
        ".git", ".ssh", ".env", "secrets",
    }

    HIGH_RISK_PATTERNS = [
        r"\brm\s+-rf\b",
        r"\bsubprocess\b",
        r"\bos\.system\s*\(",
        r"\bos\.popen\s*\(",
        r"\bshutil\.rmtree\s*\(",
        r"\beval\s*\(",
        r"\bexec\s*\(",
    ]

    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def validate_path(self, path):
        if not isinstance(path, str) or not path.strip():
            raise PermissionError("Caminho inválido.")

        target = (self.root / path).resolve()

        try:
            target.relative_to(self.root)
        except ValueError:
            raise PermissionError("Caminho fora do projeto.")

        parts = target.relative_to(self.root).parts

        for part in parts:
            if part in self.BLOCKED_PATHS:
                raise PermissionError(f"Caminho bloqueado: {path}")

        if target.suffix not in self.ALLOWED_EXTENSIONS:
            raise PermissionError(
                f"Extensão não permitida: {target.suffix}"
            )

        return True

    def assess_content_risk(self, content):
        if not isinstance(content, str):
            return "alto"

        for pattern in self.HIGH_RISK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return "alto"

        return "baixo"

    def validate_content(self, content):
        risk = self.assess_content_risk(content)

        if risk == "alto":
            raise PermissionError(
                "Conteúdo de alto risco não autorizado pela política de segurança."
            )

        return True
