from pathlib import Path

from core.context.project_context import ProjectContext


def test_build_skips_relevant_path_outside_root(tmp_path):
    context = ProjectContext(root=tmp_path)

    outside = tmp_path.parent / "outside_project_context.py"
    outside.write_text("print('outside')", encoding="utf-8")

    try:
        result = context.build([outside])
        assert str(outside.name) not in result
    finally:
        outside.unlink(missing_ok=True)


def test_build_skips_relevant_path_that_is_not_file(tmp_path):
    context = ProjectContext(root=tmp_path)

    directory = tmp_path / "directory.py"
    directory.mkdir()

    result = context.build([directory])

    assert "directory.py" not in result


def test_build_skips_ignored_relevant_path(tmp_path):
    context = ProjectContext(root=tmp_path)

    ignored = tmp_path / ".env"
    ignored.write_text("SECRET=x", encoding="utf-8")

    result = context.build([ignored])

    assert ".env" not in result


def test_build_skips_irrelevant_extension(tmp_path):
    context = ProjectContext(root=tmp_path)

    image = tmp_path / "image.jpg"
    image.write_bytes(b"not python")

    result = context.build([image])

    assert "image.jpg" not in result


def test_build_appends_valid_relevant_path(tmp_path):
    context = ProjectContext(root=tmp_path)

    target = tmp_path / "extra.py"
    target.write_text("def hello():\n    return 'ok'\n", encoding="utf-8")

    result = context.build([target])

    assert "=== ARQUIVO: extra.py ===" in result
    assert "def hello():" in result


def test_build_relevant_binary_file_uses_read_file_fallback(tmp_path):
    context = ProjectContext(root=tmp_path)

    binary = tmp_path / "binary.py"
    binary.write_bytes(b"\xff\xfe\xfd")

    result = context.build([binary])

    assert "=== ARQUIVO: binary.py ===" in result
    assert "[ARQUIVO BINÁRIO OMITIDO: binary.py]" in result
import pytest


def test_is_ignored_returns_true_for_ignored_directory(tmp_path):
    context = ProjectContext(root=tmp_path)
    path = tmp_path / ".git" / "internal.py"

    assert context._is_ignored(path) is True


def test_list_files_stops_at_max_files(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"

    first.write_text("a = 1", encoding="utf-8")
    second.write_text("b = 2", encoding="utf-8")

    context = ProjectContext(root=tmp_path, max_files=1)

    files = context.list_files()

    assert len(files) == 1


def test_read_file_blocks_path_outside_root(tmp_path):
    context = ProjectContext(root=tmp_path)
    outside = tmp_path.parent / "outside.py"

    with pytest.raises(ValueError, match="Caminho bloqueado"):
        context.read_file(outside)


def test_read_file_blocks_protected_file(tmp_path):
    context = ProjectContext(root=tmp_path)
    protected = tmp_path / ".env"

    protected.write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(ValueError, match="Arquivo protegido"):
        context.read_file(protected)


def test_read_file_rejects_non_file(tmp_path):
    context = ProjectContext(root=tmp_path)
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(FileNotFoundError, match="Arquivo não encontrado"):
        context.read_file(directory)


def test_read_file_omits_file_above_size_limit(tmp_path):
    context = ProjectContext(root=tmp_path, max_file_size=3)
    large = tmp_path / "large.txt"

    large.write_text("12345", encoding="utf-8")

    result = context.read_file(large)

    assert "excede o limite" in result


def test_build_skips_oversized_non_relevant_path(tmp_path):
    context = ProjectContext(root=tmp_path, max_file_size=3)
    large = tmp_path / "large.txt"

    large.write_text("12345", encoding="utf-8")

    result = context.build()

    assert "large.txt" not in result


def test_build_skips_section_exceeding_context_limit(tmp_path):
    context = ProjectContext(
        root=tmp_path,
        max_file_size=100000,
    )

    large = tmp_path / "large.txt"
    large.write_text("x" * 60000, encoding="utf-8")

    result = context.build()

    assert "large.txt" not in result
