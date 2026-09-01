from pathlib import Path

import pytest

from core.context.project_context import ProjectContext


def test_project_context_initializes_with_resolved_root(tmp_path):
    context = ProjectContext(tmp_path)

    assert context.root == tmp_path.resolve()
    assert context.max_file_size == 20000
    assert context.max_files == 100


def test_is_ignored_rejects_ignored_directories(tmp_path):
    context = ProjectContext(tmp_path)

    for directory in context.DEFAULT_IGNORED_DIRS:
        path = tmp_path / directory / "file.py"
        assert context._is_ignored(path) is True


def test_is_ignored_rejects_ignored_files(tmp_path):
    context = ProjectContext(tmp_path)

    for filename in context.DEFAULT_IGNORED_FILES:
        path = tmp_path / filename
        assert context._is_ignored(path) is True


def test_is_ignored_accepts_normal_file(tmp_path):
    context = ProjectContext(tmp_path)

    assert context._is_ignored(tmp_path / "main.py") is False


def test_is_relevant_rejects_directories(tmp_path):
    context = ProjectContext(tmp_path)

    directory = tmp_path / "package.py"
    directory.mkdir()

    assert context._is_relevant(directory) is False


def test_is_relevant_rejects_ignored_file(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / ".env"
    path.write_text("SECRET=value", encoding="utf-8")

    assert context._is_relevant(path) is False


def test_is_relevant_accepts_supported_extensions_case_insensitively(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / "SCRIPT.PY"
    path.write_text("print('ok')", encoding="utf-8")

    assert context._is_relevant(path) is True


def test_is_relevant_rejects_unsupported_extensions(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / "image.png"
    path.write_bytes(b"binary")

    assert context._is_relevant(path) is False


def test_list_files_returns_only_relevant_relative_sorted_files(tmp_path):
    context = ProjectContext(tmp_path)

    (tmp_path / "z.py").write_text("z", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "ignored.png").write_text("ignored", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"png")

    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "main.py").write_text("main", encoding="utf-8")

    files = context.list_files()

    assert files == [
        Path("a.py"),
        Path("src/main.py"),
        Path("z.py"),
    ]


def test_list_files_ignores_protected_directories(tmp_path):
    context = ProjectContext(tmp_path)

    for directory in context.DEFAULT_IGNORED_DIRS:
        target = tmp_path / directory
        target.mkdir()
        (target / "hidden.py").write_text(
            "should not appear",
            encoding="utf-8",
        )

    (tmp_path / "visible.py").write_text(
        "visible",
        encoding="utf-8",
    )

    assert context.list_files() == [Path("visible.py")]


def test_list_files_respects_max_files(tmp_path):
    context = ProjectContext(tmp_path, max_files=2)

    for name in ("c.py", "a.py", "b.py"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    files = context.list_files()

    assert len(files) == 2


def test_read_file_returns_text(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / "main.py"
    path.write_text("print('hello')\n", encoding="utf-8")

    assert context.read_file("main.py") == "print('hello')\n"


def test_read_file_rejects_path_escape(tmp_path):
    context = ProjectContext(tmp_path)

    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="Caminho bloqueado"):
        context.read_file("../outside.py")


def test_read_file_rejects_ignored_file(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / ".env"
    path.write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(".env")


def test_read_file_rejects_ignored_directory_file(tmp_path):
    context = ProjectContext(tmp_path)

    directory = tmp_path / ".git"
    directory.mkdir()
    (directory / "config.py").write_text(
        "protected",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(".git/config.py")


def test_read_file_rejects_missing_file(tmp_path):
    context = ProjectContext(tmp_path)

    with pytest.raises(FileNotFoundError, match="Arquivo não encontrado"):
        context.read_file("missing.py")


def test_read_file_omits_file_exceeding_size_limit(tmp_path):
    context = ProjectContext(tmp_path, max_file_size=5)

    path = tmp_path / "large.py"
    path.write_text("123456", encoding="utf-8")

    result = context.read_file("large.py")

    assert result == "[ARQUIVO OMITIDO: large.py excede o limite]"


def test_read_file_omits_binary_file(tmp_path):
    context = ProjectContext(tmp_path)

    path = tmp_path / "binary.py"
    path.write_bytes(b"\xff\xfe\x00\x01")

    result = context.read_file("binary.py")

    assert result == "[ARQUIVO BINÁRIO OMITIDO: binary.py]"


def test_build_includes_project_header_and_files(tmp_path):
    context = ProjectContext(tmp_path)

    (tmp_path / "main.py").write_text(
        "print('hello')",
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        '{"debug": true}',
        encoding="utf-8",
    )

    result = context.build()

    assert "=== CONTEXTO DO PROJETO ===" in result
    assert f"ROOT: {tmp_path.resolve()}" in result
    assert "ARQUIVOS DISPONÍVEIS: 2" in result
    assert "ARQUIVOS INCLUÍDOS NO CONTEXTO: 2" in result
    assert "=== ARQUIVO: config.json ===" in result
    assert '{"debug": true}' in result
    assert "=== ARQUIVO: main.py ===" in result
    assert "print('hello')" in result


def test_build_skips_sections_that_exceed_context_limit(tmp_path):
    context = ProjectContext(tmp_path)
    context.max_file_size = 50000

    (tmp_path / "first.py").write_text(
        "A" * 30000,
        encoding="utf-8",
    )
    (tmp_path / "second.py").write_text(
        "B" * 30000,
        encoding="utf-8",
    )

    result = context.build()

    assert "=== ARQUIVO: first.py ===" in result
    assert "=== ARQUIVO: second.py ===" not in result
    assert "ARQUIVOS INCLUÍDOS NO CONTEXTO: 1" in result


def test_build_reports_zero_included_files_when_all_sections_are_too_large(
    tmp_path,
):
    context = ProjectContext(tmp_path)

    (tmp_path / "huge.py").write_text(
        "X" * 20001,
        encoding="utf-8",
    )

    result = context.build()

    assert "ARQUIVOS DISPONÍVEIS: 1" in result
    assert "ARQUIVOS INCLUÍDOS NO CONTEXTO: 0" in result
    assert "=== ARQUIVO: huge.py ===" not in result


def test_build_handles_binary_file_content(tmp_path):
    context = ProjectContext(tmp_path)

    (tmp_path / "binary.py").write_bytes(
        b"\xff\xfe\x00\x01"
    )

    result = context.build()

    assert "=== ARQUIVO: binary.py ===" in result
    assert "[ARQUIVO BINÁRIO OMITIDO: binary.py]" in result


def test_build_skips_oversized_file_content(tmp_path):
    context = ProjectContext(tmp_path)

    context.max_file_size = 5

    (tmp_path / "large.py").write_text(
        "123456",
        encoding="utf-8",
    )

    result = context.build()

    assert "=== ARQUIVO: large.py ===" not in result
    assert "ARQUIVOS INCLUÍDOS NO CONTEXTO: 0" in result


def test_build_skips_file_when_section_exceeds_context_limit(tmp_path):
    context = ProjectContext(tmp_path)

    (tmp_path / "first.py").write_text(
        "A" * 10000,
        encoding="utf-8",
    )
    (tmp_path / "second.py").write_text(
        "B" * 30000,
        encoding="utf-8",
    )

    result = context.build()

    assert "=== ARQUIVO: first.py ===" in result
    assert "=== ARQUIVO: second.py ===" not in result
    assert "ARQUIVOS INCLUÍDOS NO CONTEXTO: 1" in result
