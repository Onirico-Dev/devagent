from pathlib import Path


class PostExecutionVerifier:
    """Verifica se uma alteração executada produziu o estado esperado."""

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

    def verify_path(self, path, expected_content=None):
        target = (self.project_root / path).resolve()

        try:
            target.relative_to(self.project_root)
        except ValueError as exc:
            raise PermissionError(
                "Caminho inválido: fora do projeto."
            ) from exc

        if not target.exists():
            return {
                "success": False,
                "status": "missing",
                "path": str(path),
            }

        if not target.is_file():
            return {
                "success": False,
                "status": "not_file",
                "path": str(path),
            }

        if expected_content is not None:
            actual = target.read_text(encoding="utf-8")
            if actual != expected_content:
                return {
                    "success": False,
                    "status": "content_mismatch",
                    "path": str(path),
                }

        return {
            "success": True,
            "status": "verified",
            "path": str(path),
        }
