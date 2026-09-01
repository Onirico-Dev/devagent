import json

import pytest

from core.adapters.mock import MockAdapter


def test_mock_generate_rejects_non_string_prompt():
    adapter = MockAdapter()

    with pytest.raises(TypeError, match="O prompt deve ser uma string."):
        adapter.generate(None)


def test_mock_generate_rejects_empty_prompt():
    adapter = MockAdapter()

    with pytest.raises(ValueError, match="O prompt não pode ser vazio."):
        adapter.generate("   ")


def test_mock_generate_returns_empty_plan_for_unrecognized_instruction():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "INSTRUÇÃO DO USUÁRIO:\n"
            "faça alguma coisa\n"
            "CONTEXTO DO PROJETO:\n"
            "arquivo.py"
        )
    )

    assert result == {
        "objective": "faça alguma coisa",
        "changes": [],
        "tests": [],
        "risks": [],
    }


def test_mock_generate_create_with_explicit_content():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "INSTRUÇÃO DO USUÁRIO:\n"
            "crie app.py com conteúdo print('ok')\n"
            "CONTEXTO DO PROJETO:\n"
        )
    )

    assert result["objective"] == "crie app.py com conteúdo print('ok')"
    assert result["changes"] == [
        {
            "type": "create",
            "path": "app.py",
            "content": "print('ok')",
            "reason": "crie app.py com conteúdo print('ok')",
        }
    ]


def test_mock_generate_create_uses_legacy_content_fallback():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "INSTRUÇÃO DO USUÁRIO:\n"
            "crie app.py print('ok')\n"
            "CONTEXTO DO PROJETO:\n"
        )
    )

    assert result["changes"][0]["type"] == "create"
    assert result["changes"][0]["path"] == "app.py"
    assert result["changes"][0]["content"] == "print('ok')"


@pytest.mark.parametrize(
    "instruction",
    [
        "crie um arquivo chamado app.py com conteúdo print('ok')",
        "crie arquivo app.py com conteúdo print('ok')",
        "criar arquivo app.py com conteúdo print('ok')",
        "create app.py com conteúdo print('ok')",
    ],
)
def test_mock_create_recognizes_creation_variants(instruction):
    adapter = MockAdapter()

    result = adapter._build_planner_change(instruction)

    assert result["type"] == "create"
    assert result["path"] == "app.py"
    assert result["content"] == "print('ok')"


@pytest.mark.parametrize(
    "instruction",
    [
        "modifique app.py print('alterado')",
        "modificar o app.py print('alterado')",
        "altere o arquivo app.py print('alterado')",
        "alterar a app.py print('alterado')",
        "modify arquivo app.py print('alterado')",
    ],
)
def test_mock_modify_recognizes_modify_variants(instruction):
    adapter = MockAdapter()

    result = adapter._build_planner_change(instruction)

    assert result["type"] == "modify"
    assert result["path"] == "app.py"
    assert result["content"] == "print('alterado')"
    assert result["reason"] == instruction


@pytest.mark.parametrize(
    "instruction",
    [
        "delete app.py",
        "apague app.py",
        "remova app.py",
        "remover o arquivo app.py",
    ],
)
def test_mock_delete_recognizes_delete_variants(instruction):
    adapter = MockAdapter()

    result = adapter._build_planner_change(instruction)

    assert result == {
        "type": "delete",
        "path": "app.py",
        "reason": instruction,
    }


def test_mock_modify_without_content_returns_empty_content():
    adapter = MockAdapter()

    result = adapter._build_planner_change("modifique app.py")

    assert result == {
        "type": "modify",
        "path": "app.py",
        "content": "",
        "reason": "modifique app.py",
    }


def test_mock_create_without_content_returns_empty_content():
    adapter = MockAdapter()

    result = adapter._build_planner_change("crie app.py")

    assert result == {
        "type": "create",
        "path": "app.py",
        "content": "",
        "reason": "crie app.py",
    }


def test_mock_build_planner_change_returns_none_for_unknown_instruction():
    adapter = MockAdapter()

    assert adapter._build_planner_change("faça qualquer coisa") is None


@pytest.mark.parametrize(
    "instruction,expected",
    [
        ("crie app.py", "app.py"),
        ("crie um arquivo app.py", "app.py"),
        ("crie um arquivo chamado app.py", "app.py"),
        ("create app.py", "app.py"),
        ("criar arquivo app.py", "app.py"),
    ],
)
def test_mock_extract_create_target(instruction, expected):
    assert MockAdapter._extract_create_target(instruction) == expected


def test_mock_extract_create_target_returns_empty_when_missing():
    assert MockAdapter._extract_create_target("modifique app.py") == ""


@pytest.mark.parametrize(
    "marker",
    [
        " contendo ",
        " com conteúdo ",
        " com conteudo ",
    ],
)
def test_mock_extract_create_content_supports_all_markers(marker):
    instruction = f"crie app.py{marker}print('ok')"

    assert MockAdapter._extract_create_content(instruction) == "print('ok')"


def test_mock_extract_create_content_returns_empty_when_missing():
    assert MockAdapter._extract_create_content("crie app.py") == ""


def test_mock_repair_flow_extracts_path_and_content():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            "modifique broken.py contendo isto não é Python válido\n"
            "Erro:\n"
            "SyntaxError"
        )
    )

    assert result["diagnosis"]
    assert result["correction"]
    assert result["risk"] == "baixo"
    assert result["action"] == "modify"
    assert result["path"] == "broken.py"
    assert result["content"] == "isto não é Python válido"


def test_mock_repair_flow_uses_default_path_when_missing():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            "corrija o problema\n"
            "Erro:\n"
            "SyntaxError"
        )
    )

    assert result["path"] == "reparo.py"


def test_mock_repair_flow_uses_default_content_when_missing():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            "corrija broken.py\n"
            "Erro:\n"
            "SyntaxError"
        )
    )

    assert result["path"] == "broken.py"
    assert result["content"] == "isto não é Python válido"


def test_mock_extract_repair_path():
    assert (
        MockAdapter._extract_repair_path("corrija o arquivo broken.py")
        == "broken.py"
    )


def test_mock_extract_repair_path_returns_empty_when_missing():
    assert MockAdapter._extract_repair_path("corrija o arquivo") == ""


@pytest.mark.parametrize(
    "marker",
    [
        " contendo ",
        " com conteúdo ",
        " com conteudo ",
    ],
)
def test_mock_extract_invalid_content_supports_all_markers(marker):
    instruction = f"corrija broken.py{marker}conteúdo inválido"

    assert (
        MockAdapter._extract_invalid_content(instruction)
        == "conteúdo inválido"
    )


def test_mock_extract_invalid_content_uses_default():
    assert (
        MockAdapter._extract_invalid_content("corrija broken.py")
        == "isto não é Python válido"
    )


def test_mock_generate_repair_marker_must_be_at_prompt_start():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "contexto:\n"
            "Você é o módulo de reparo automático do DevAgent.\n"
            "INSTRUÇÃO DO USUÁRIO:\n"
            "crie app.py"
        )
    )

    assert result["objective"] == "crie app.py"
    assert result["changes"][0]["type"] == "create"


def test_mock_generate_extracts_instruction_only_before_context():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "INSTRUÇÃO DO USUÁRIO:\n"
            "crie app.py\n"
            "CONTEXTO DO PROJETO:\n"
            "crie outro.py"
        )
    )

    assert result["objective"] == "crie app.py"
    assert result["changes"][0]["path"] == "app.py"


def test_mock_create_target_returns_empty_for_unrecognized_instruction():
    adapter = MockAdapter()

    result = adapter._extract_create_target("modifique app.py")

    assert result == ""


def test_mock_build_planner_change_returns_none_for_empty_instruction():
    adapter = MockAdapter()

    assert adapter._build_planner_change("") is None
