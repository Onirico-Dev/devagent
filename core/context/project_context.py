import os
import re
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
        "logs",
        "secrets",
        "backups",
        ".ssh",
        ".env",
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
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".css",
    }

    def __init__(
        self,
        root=".",
        max_file_size=20000,
        max_files=100,
        max_context_chars=50000,
    ):
        self.root = Path(root).resolve()
        self.max_file_size = max_file_size
        self.max_files = max_files
        self.max_context_chars = max_context_chars
        self.python_analyzer = PythonAnalyzer()

    def _is_ignored(self, path: Path) -> bool:
        if any(
            part in self.DEFAULT_IGNORED_DIRS
            for part in path.parts
        ):
            return True

        if path.name in self.DEFAULT_IGNORED_FILES:
            return True

        return any(part.startswith(".env.") for part in path.parts)

    def _is_relevant(self, path: Path) -> bool:
        if path.is_symlink():
            return False

        if not path.is_file():
            return False

        if self._is_ignored(path):
            return False

        return path.suffix.lower() in self.DEFAULT_EXTENSIONS

    def _source_files(self):
        # Prune ignored trees before descending (not after enumerating them).
        for directory, folders, names in os.walk(self.root, followlinks=False):
            folders[:] = sorted(
                name for name in folders
                if not self._is_ignored(Path(directory) / name)
                and not (Path(directory) / name).is_symlink()
            )
            for name in sorted(names):
                path = Path(directory) / name
                if self._is_relevant(path):
                    yield path.relative_to(self.root)

    def select_relevant_paths(self, instruction):
        """Find explicit files and bounded, literal matches for routes/UI labels."""
        explicit = []
        for name in re.findall(r"(?<![\w./-])[\w./-]+\.[A-Za-z0-9]+", instruction):
            relative = Path(name)
            path = (self.root / relative).resolve()
            if (
                not relative.is_absolute()
                and path.is_relative_to(self.root)
                and not self._is_ignored(path)
                and self._is_relevant(self.root / relative)
                and relative not in explicit
            ):
                explicit.append(relative)

        routes = re.findall(r"(?<![\w/])/[A-Za-z0-9_/-]+", instruction)
        labels = re.findall(r'''["“]([^"“”\r\n]{4,80})["”]''', instruction)
        identifiers = re.findall(r"\b[A-Za-z]\w*_\w+\b", instruction)
        terms = {term.casefold() for term in routes + labels + identifiers}
        route_names = {route.rstrip("/").rsplit("/", 1)[-1] for route in routes}
        matches = []
        for index, relative in enumerate(self._source_files()):
            if index >= 1000:
                break
            path = self.root / relative
            if path.stat().st_size > self.max_file_size:
                continue
            content = self.read_file(relative).casefold()
            score = sum(term in content for term in terms)
            score += sum(
                f"def {name}(" in content or f".{name}(" in content
                for name in route_names
            )
            if score:
                is_test = (
                    relative.name.startswith("test_")
                    or "tests" in relative.parts
                    or ".test." in relative.name
                )
                matches.append((is_test, -score, relative))
        source_stems = {
            path.stem for is_test, score, path in matches
            if not is_test and path.suffix not in {".md", ".txt"}
        }

        def rank(item):
            is_test, score, path = item
            category = 2 if path.suffix in {".md", ".txt"} else int(is_test)
            subject = path.stem.removeprefix("test_").removesuffix(".test")
            return category, subject not in source_stems, score, path

        return [str(path) for path in dict.fromkeys(
            explicit + [item[2] for item in sorted(matches, key=rank)]
        )]

    def list_files(self):
        files = []

        for relative in self._source_files():
            files.append(relative)

            if len(files) >= self.max_files:
                break

        return sorted(files)

    def read_file(self, relative_path):
        unresolved = self.root / relative_path
        path = unresolved.resolve()

        try:
            path.relative_to(self.root)
        except ValueError:
            raise ValueError(
                f"Caminho bloqueado: {relative_path}"
            ) from None

        if self._is_ignored(unresolved) or self._is_ignored(path):
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

    def build(self, relevant_paths=None):
        requested = list(dict.fromkeys(
            Path(path)
            for path in (relevant_paths or [])
        ))
        relevant_paths = set(requested)

        files = self.list_files()

        for relative in sorted(relevant_paths):
            if relative not in files:
                absolute = (self.root / relative).resolve()

                try:
                    absolute.relative_to(self.root)
                except ValueError:
                    continue

                if not absolute.is_file():
                    continue

                if (self.root / relative).is_symlink():
                    continue

                if self._is_ignored(self.root / relative) or self._is_ignored(absolute):
                    continue

                if absolute.suffix.lower() not in self.DEFAULT_EXTENSIONS:
                    continue

                files.append(relative)

        prioritized = [path for path in requested if path in files]

        remaining = [
            path for path in files
            if path not in relevant_paths
        ]

        files = prioritized + remaining

        sections = [
            "=== CONTEXTO DO PROJETO ===",
            f"ROOT: {self.root}",
            f"ARQUIVOS DISPONÍVEIS: {len(files)}",
            "",
        ]

        # Reserve space for line separators and the final included-file count.
        total = sum(len(x) + 1 for x in sections) + 100
        included = 0

        for relative in files:
            path = (self.root / relative).resolve()

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

            if total + len(section) + 1 > self.max_context_chars:
                continue

            sections.append(section)
            total += len(section) + 1
            included += 1

        sections.insert(
            3,
            f"ARQUIVOS INCLUÍDOS NO CONTEXTO: {included}",
        )

        return "\n".join(sections)
