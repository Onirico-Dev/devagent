from pathlib import Path
from core.schemas.models import FileInfo


class ProjectScanner:

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def scan(self) -> list[FileInfo]:
        results = []

        if not self.root.exists():
            raise FileNotFoundError(
                f"Projeto não encontrado: {self.root}"
            )

        for path in sorted(self.root.rglob("*")):

            if ".git" in path.parts:
                continue

            if path.is_file():
                results.append(
                    FileInfo(
                        path=str(path.relative_to(self.root)),
                        exists=True,
                        is_file=True,
                        is_directory=False,
                        size=path.stat().st_size,
                    )
                )

            elif path.is_dir():
                results.append(
                    FileInfo(
                        path=str(path.relative_to(self.root)),
                        exists=True,
                        is_file=False,
                        is_directory=True,
                    )
                )

        return results
