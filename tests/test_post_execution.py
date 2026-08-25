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
