from pathlib import Path


class ProjectContext:

    DEFAULT_IGNORED_DIRS = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "transactions",
        ".venv",
        "venv",
        "node_modules",
    }

    DEFAULT_IGNORED_FILES = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
    }

    DEFAULT_EXTENSIONS = {
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".md",
        ".txt",
        ".sh",
    }

    def __init__(
        self,
        root=".",
        max_file_size=20000,
        max_files=100,
    ):
        self.root = Path(root).resolve()
        self.max_file_size = max_file_size
        self.max_files = max_files

    def _is_ignored(self, path: Path) -> bool:

        if any(
            part in self.DEFAULT_IGNORED_DIRS
            for part in path.parts
        ):
            return True

        if path.name in self.DEFAULT_IGNORED_FILES:
            return True

        return False

    def _is_relevant(self, path: Path) -> bool:

        if not path.is_file():
            return False

        if self._is_ignored(path):
            return False

        return path.suffix.lower() in (
            self.DEFAULT_EXTENSIONS
        )

    def list_files(self):

        files = []

        for path in self.root.rglob("*"):

            if not self._is_relevant(path):
                continue

            relative = path.relative_to(self.root)

            files.append(relative)

            if len(files) >= self.max_files:
                break

        return sorted(files)

    def read_file(self, relative_path):

        path = (
            self.root / relative_path
        ).resolve()

        if not str(path).startswith(
            str(self.root)
        ):
            raise ValueError(
                f"Caminho bloqueado: {relative_path}"
            )

        if self._is_ignored(path):
            raise ValueError(
                f"Arquivo protegido: {relative_path}"
            )

        if not path.is_file():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {relative_path}"
            )

        if path.stat().st_size > self.max_file_size:
            return (
                f"[ARQUIVO OMITIDO: "
                f"{relative_path} excede o limite]"
            )

        try:

            return path.read_text(
                encoding="utf-8"
            )

        except UnicodeDecodeError:

            return (
                f"[ARQUIVO BINÁRIO OMITIDO: "
                f"{relative_path}]"
            )

    def build(self):
        files = self.list_files()

        MAX_CONTEXT_CHARS = 50000

        sections = [
            "=== CONTEXTO DO PROJETO ===",
            f"ROOT: {self.root}",
            f"ARQUIVOS DISPONÍVEIS: {len(files)}",
            "",
        ]

        total = sum(len(x) for x in sections)
        included = 0

        for relative in files:
            content = self.read_file(relative)
            section = (
                f"=== ARQUIVO: {relative} ===\n"
                f"{content}\n"
            )

            if total + len(section) > MAX_CONTEXT_CHARS:
                continue

            sections.append(section)
            total += len(section)
            included += 1

        sections.insert(
            3,
            f"ARQUIVOS INCLUÍDOS NO CONTEXTO: {included}",
        )

        return "\n".join(sections)
