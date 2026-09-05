from pathlib import Path

from core.context.python_analyzer import PythonAnalyzer


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
        self.python_analyzer = PythonAnalyzer()

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

        return path.suffix.lower() in self.DEFAULT_EXTENSIONS

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

        try:
            path.relative_to(self.root)
        except ValueError:
            raise ValueError(
                f"Caminho bloqueado: {relative_path}"
            ) from None

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

    def _build_python_metadata(
        self,
        relative_path,
        content,
    ):
        try:
            analysis = self.python_analyzer.analyze(
                content
            )
        except ValueError as exc:
            return (
                "=== ANÁLISE PYTHON ===\n"
                f"ERRO: {exc}\n"
            )

        return (
            "=== ANÁLISE PYTHON ===\n"
            f"IMPORTS: {analysis['imports']}\n"
            f"FUNÇÕES: {analysis['functions']}\n"
            f"CLASSES: {analysis['classes']}\n"
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
            path = (
                self.root / relative
            ).resolve()

            if path.stat().st_size > self.max_file_size:
                continue

            content = self.read_file(relative)

            section = (
                f"=== ARQUIVO: {relative} ===\n"
                f"{content}\n"
            )

            if path.suffix.lower() == ".py":
                section += self._build_python_metadata(
                    relative,
                    content,
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
