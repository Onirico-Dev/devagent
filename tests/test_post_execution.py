from core.engine.post_execution import PostExecutionVerifier


def test_post_execution_verifies_existing_file(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path(
        "app.py",
        "print('ok')\n",
    )

    assert result["success"] is True
    assert result["status"] == "verified"


def test_post_execution_detects_missing_file(tmp_path):
    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path("missing.py")

    assert result["success"] is False
    assert result["status"] == "missing"


def test_post_execution_rejects_path_outside_project(tmp_path):
    verifier = PostExecutionVerifier(tmp_path)

    try:
        verifier.verify_path("../outside.py")
        assert False, "Deveria rejeitar caminho fora do projeto."
    except PermissionError as exc:
        assert "Caminho inválido" in str(exc)


def test_post_execution_detects_directory_as_not_file(tmp_path):
    verifier = PostExecutionVerifier(tmp_path)
    directory = tmp_path / "directory"
    directory.mkdir()

    result = verifier.verify_path("directory")

    assert result == {
        "success": False,
        "status": "not_file",
        "path": "directory",
    }


def test_post_execution_detects_content_mismatch(tmp_path):
    verifier = PostExecutionVerifier(tmp_path)
    target = tmp_path / "file.py"
    target.write_text("actual", encoding="utf-8")

    result = verifier.verify_path("file.py", expected_content="expected")

    assert result == {
        "success": False,
        "status": "content_mismatch",
        "path": "file.py",
    }

def test_post_execution_detects_non_file_path(tmp_path):
    target = tmp_path / "directory"
    target.mkdir()

    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path("directory")

    assert result["success"] is False
    assert result["status"] == "not_file"
    assert result["path"] == "directory"


def test_post_execution_detects_content_mismatch(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("print('actual')\n", encoding="utf-8")

    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path(
        "app.py",
        "print('expected')\n",
    )

    assert result["success"] is False
    assert result["status"] == "content_mismatch"
    assert result["path"] == "app.py"


def test_post_execution_rejects_directory_as_target(tmp_path):
    target = tmp_path / "src"
    target.mkdir()

    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path("src")

    assert result["success"] is False
    assert result["status"] == "not_file"
    assert result["path"] == "src"


def test_post_execution_detects_content_mismatch(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("print('actual')\n", encoding="utf-8")

    verifier = PostExecutionVerifier(tmp_path)

    result = verifier.verify_path(
        "app.py",
        "print('expected')\n",
    )

    assert result["success"] is False
    assert result["status"] == "content_mismatch"
    assert result["path"] == "app.py"
