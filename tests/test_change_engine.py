from pathlib import Path

import pytest

from core.engine.change_engine import ChangeEngine
from core.schemas.models import Change, ChangeType, Plan


def make_change(path, change_type, content="conteudo"):
    return Change(
        change_type=change_type,
        path=path,
        content=content,
    )


def make_plan(changes):
    return Plan(
        objective="teste",
        changes=changes,
        tests=[],
        risks=[],
    )


def test_validate_create_accepts_missing_file(tmp_path):
    engine = ChangeEngine(tmp_path)

    change = make_change("novo.py", ChangeType.CREATE)

    engine.validate_change(change)

    assert not (tmp_path / "novo.py").exists()


def test_validate_create_rejects_existing_file(tmp_path):
    target = tmp_path / "existente.py"
    target.write_text("x = 1\n", encoding="utf-8")

    engine = ChangeEngine(tmp_path)
    change = make_change("existente.py", ChangeType.CREATE)

    with pytest.raises(
        FileExistsError,
        match="Arquivo já existe",
    ):
        engine.validate_change(change)


def test_validate_modify_accepts_existing_file(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")

    engine = ChangeEngine(tmp_path)
    change = make_change("app.py", ChangeType.MODIFY)

    engine.validate_change(change)


def test_validate_modify_rejects_missing_file(tmp_path):
    engine = ChangeEngine(tmp_path)
    change = make_change("ausente.py", ChangeType.MODIFY)

    with pytest.raises(
        FileNotFoundError,
        match="Arquivo não encontrado",
    ):
        engine.validate_change(change)


def test_validate_modify_rejects_directory(tmp_path):
    (tmp_path / "pasta").mkdir()

    engine = ChangeEngine(tmp_path)
    change = make_change("pasta", ChangeType.MODIFY)

    with pytest.raises(
        IsADirectoryError,
        match="Caminho não é um arquivo",
    ):
        engine.validate_change(change)


def test_validate_delete_accepts_existing_file(tmp_path):
    target = tmp_path / "apagar.py"
    target.write_text("x = 1\n", encoding="utf-8")

    engine = ChangeEngine(tmp_path)
    change = make_change("apagar.py", ChangeType.DELETE)

    engine.validate_change(change)


def test_validate_delete_rejects_missing_file(tmp_path):
    engine = ChangeEngine(tmp_path)
    change = make_change("ausente.py", ChangeType.DELETE)

    with pytest.raises(
        FileNotFoundError,
        match="Arquivo não encontrado",
    ):
        engine.validate_change(change)


def test_validate_delete_rejects_directory(tmp_path):
    (tmp_path / "pasta").mkdir()

    engine = ChangeEngine(tmp_path)
    change = make_change("pasta", ChangeType.DELETE)

    with pytest.raises(
        IsADirectoryError,
        match="Caminho não é um arquivo",
    ):
        engine.validate_change(change)


def test_validate_rejects_path_outside_project(tmp_path):
    engine = ChangeEngine(tmp_path)

    change = make_change(
        "../fora.py",
        ChangeType.CREATE,
    )

    with pytest.raises(
        ValueError,
        match="Caminho fora do projeto",
    ):
        engine.validate_change(change)


def test_validate_accepts_nested_path_inside_project(tmp_path):
    engine = ChangeEngine(tmp_path)

    change = make_change(
        "src/app.py",
        ChangeType.CREATE,
    )

    engine.validate_change(change)


def test_prepare_validates_all_changes_and_returns_same_list(tmp_path):
    engine = ChangeEngine(tmp_path)

    changes = [
        make_change("a.py", ChangeType.CREATE),
        make_change("b.py", ChangeType.CREATE),
    ]

    plan = make_plan(changes)

    result = engine.prepare(plan)

    assert result is changes
    assert result == changes


def test_prepare_propagates_validation_error(tmp_path):
    engine = ChangeEngine(tmp_path)

    existing = tmp_path / "existente.py"
    existing.write_text("x = 1\n", encoding="utf-8")

    changes = [
        make_change("novo.py", ChangeType.CREATE),
        make_change("existente.py", ChangeType.CREATE),
    ]

    plan = make_plan(changes)

    with pytest.raises(
        FileExistsError,
        match="Arquivo já existe",
    ):
        engine.prepare(plan)


def test_validate_unsupported_change_type_does_not_raise(tmp_path):
    engine = ChangeEngine(tmp_path)

    change = make_change(
        "arquivo.py",
        "unsupported",
    )

    engine.validate_change(change)
