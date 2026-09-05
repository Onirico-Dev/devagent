from pathlib import Path

import pytest

from core.scanner.project_scanner import ProjectScanner


def test_project_scanner_rejects_missing_project(tmp_path):
    root = tmp_path / "missing"

    with pytest.raises(
        FileNotFoundError,
        match="Projeto não encontrado",
    ):
        ProjectScanner(str(root)).scan()


def test_project_scanner_rejects_non_directory(tmp_path):
    root = tmp_path / "project.py"
    root.write_text(
        "print('test')",
        encoding="utf-8",
    )

    with pytest.raises(
        NotADirectoryError,
        match="Projeto não é um diretório",
    ):
        ProjectScanner(str(root)).scan()


def test_project_scanner_collects_files_and_directories(tmp_path):
    package = tmp_path / "package"
    package.mkdir()

    main = tmp_path / "main.py"
    main.write_text(
        "print('hello')",
        encoding="utf-8",
    )

    results = ProjectScanner(str(tmp_path)).scan()

    by_path = {item.path: item for item in results}

    assert "package" in by_path
    assert by_path["package"].is_directory is True
    assert by_path["package"].is_file is False

    assert "main.py" in by_path
    assert by_path["main.py"].is_file is True
    assert by_path["main.py"].is_directory is False
    assert by_path["main.py"].size == len(
        "print('hello')".encode("utf-8")
    )


def test_project_scanner_ignores_git_directory(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    internal = git_dir / "config"
    internal.write_text(
        "git data",
        encoding="utf-8",
    )

    visible = tmp_path / "main.py"
    visible.write_text(
        "print('hello')",
        encoding="utf-8",
    )

    results = ProjectScanner(str(tmp_path)).scan()

    paths = {item.path for item in results}

    assert "main.py" in paths
    assert ".git" not in paths
    assert ".git/config" not in paths


def test_project_scanner_ignores_symlinks(tmp_path):
    target = tmp_path / "target.py"
    target.write_text(
        "print('target')",
        encoding="utf-8",
    )

    link = tmp_path / "link.py"

    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks não suportados neste ambiente.")

    results = ProjectScanner(str(tmp_path)).scan()

    paths = {item.path for item in results}

    assert "target.py" in paths
    assert "link.py" not in paths


def test_project_scanner_returns_sorted_paths(tmp_path):
    (tmp_path / "z.py").write_text(
        "z",
        encoding="utf-8",
    )
    (tmp_path / "a.py").write_text(
        "a",
        encoding="utf-8",
    )

    directory = tmp_path / "m"
    directory.mkdir()

    results = ProjectScanner(str(tmp_path)).scan()

    paths = [item.path for item in results]

    assert paths == sorted(paths)


def test_project_scanner_handles_empty_project(tmp_path):
    results = ProjectScanner(str(tmp_path)).scan()

    assert results == []


def test_project_scanner_uses_relative_paths(tmp_path):
    nested = tmp_path / "src"
    nested.mkdir()

    source = nested / "app.py"
    source.write_text(
        "print('app')",
        encoding="utf-8",
    )

    results = ProjectScanner(str(tmp_path)).scan()

    paths = {item.path for item in results}

    assert "src" in paths
    assert "src/app.py" in paths
