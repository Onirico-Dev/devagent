import pytest

from core.parser.command_parser import Command, CommandParser


@pytest.fixture
def parser():
    return CommandParser()


def assert_command(command, *, raw, action, target, instruction):
    assert isinstance(command, Command)
    assert command.raw == raw
    assert command.action == action
    assert command.target == target
    assert command.instruction == instruction


def test_parse_rejects_empty_command(parser):
    with pytest.raises(ValueError, match="Comando vazio."):
        parser.parse("   ")


def test_parse_analyze_without_instruction(parser):
    result = parser.parse("analise")

    assert_command(
        result,
        raw="analise",
        action="analyze",
        target="",
        instruction="",
    )


def test_parse_analyze_with_instruction(parser):
    result = parser.parse("análise o projeto atual")

    assert_command(
        result,
        raw="análise o projeto atual",
        action="analyze",
        target="",
        instruction="análise o projeto atual",
    )


def test_parse_unknown_command_becomes_analysis(parser):
    result = parser.parse("explique o projeto")

    assert_command(
        result,
        raw="explique o projeto",
        action="analyze",
        target="",
        instruction="explique o projeto",
    )


@pytest.mark.parametrize(
    "text",
    [
        "crie",
        "criar",
        "modifique",
        "modificar",
        "altere",
        "alterar",
        "delete",
        "apague",
        "remova",
        "remover",
    ],
)
def test_parse_operation_without_target_becomes_analysis(parser, text):
    result = parser.parse(text)

    assert_command(
        result,
        raw=text,
        action="analyze",
        target="",
        instruction="",
    )


def test_parse_operation_with_empty_remainder_becomes_analysis(parser):
    result = parser.parse("crie   ")

    assert_command(
        result,
        raw="crie",
        action="analyze",
        target="",
        instruction="",
    )


def test_parse_operation_with_remainder_but_no_target(parser):
    result = parser.parse("crie    ")

    assert_command(
        result,
        raw="crie",
        action="analyze",
        target="",
        instruction="",
    )


@pytest.mark.parametrize(
    "text, expected_target, expected_instruction",
    [
        (
            "crie um arquivo chamado teste.py conteúdo aqui",
            "teste.py",
            "conteúdo aqui",
        ),
        (
            "crie um arquivo de nome teste.py conteúdo aqui",
            "teste.py",
            "conteúdo aqui",
        ),
        (
            "crie arquivo chamado teste.py conteúdo aqui",
            "teste.py",
            "conteúdo aqui",
        ),
        (
            "crie arquivo de nome teste.py conteúdo aqui",
            "teste.py",
            "conteúdo aqui",
        ),
        (
            "crie arquivo teste.py conteúdo aqui",
            "teste.py",
            "conteúdo aqui",
        ),
    ],
)
def test_parse_create_supports_all_target_patterns(
    parser,
    text,
    expected_target,
    expected_instruction,
):
    result = parser.parse(text)

    assert_command(
        result,
        raw=text,
        action="create",
        target=expected_target,
        instruction=expected_instruction,
    )


def test_parse_target_without_instruction(parser):
    result = parser.parse("crie arquivo teste.py")

    assert_command(
        result,
        raw="crie arquivo teste.py",
        action="create",
        target="teste.py",
        instruction="",
    )


def test_parse_delete_discards_instruction(parser):
    result = parser.parse("delete arquivo teste.py conteúdo que deve ser ignorado")

    assert_command(
        result,
        raw="delete arquivo teste.py conteúdo que deve ser ignorado",
        action="delete",
        target="teste.py",
        instruction="",
    )


@pytest.mark.parametrize(
    "action",
    ["crie", "modifique", "altere"],
)
def test_parse_modify_style_operations(parser, action):
    result = parser.parse(f"{action} arquivo teste.py VALUE = 1")

    assert result.action == {
        "crie": "create",
        "modifique": "modify",
        "altere": "modify",
    }[action]
    assert result.target == "teste.py"
    assert result.instruction == "VALUE = 1"


def test_parse_fallback_target_extraction(parser):
    result = parser.parse("crie caminho-complexo.py conteúdo")

    assert_command(
        result,
        raw="crie caminho-complexo.py conteúdo",
        action="create",
        target="caminho-complexo.py",
        instruction="conteúdo",
    )


@pytest.mark.parametrize(
    "prefix",
    ["de", "do", "da", "dos", "das", "para", "por", "com", "contendo"],
)
def test_extract_target_skips_reserved_words(parser, prefix):
    target, instruction = parser._extract_target_and_instruction(
        f"{prefix} arquivo.py conteúdo",
        "create",
    )

    assert target == prefix
    assert instruction == "arquivo.py conteúdo"


def test_extract_target_skips_reserved_word_inside_matching_pattern(parser):
    target, instruction = parser._extract_target_and_instruction(
        "arquivo de arquivo.py conteúdo",
        "create",
    )

    assert target == "de"
    assert instruction == "arquivo.py conteúdo"


def test_clean_removes_quotes_and_punctuation(parser):
    assert parser._clean('"teste.py",') == "teste.py"
    assert parser._clean("'teste.py';") == "teste.py"
    assert parser._clean("`teste.py`:") == "teste.py"


def test_clean_instruction_only_strips_whitespace(parser):
    assert parser._clean_instruction("  conteúdo  ") == "conteúdo"


def test_parse_cleans_target_and_instruction(parser):
    result = parser.parse('crie arquivo "teste.py",   conteúdo   ')

    assert result.action == "create"
    assert result.target == "teste.py"
    assert result.instruction == "conteúdo"


def test_parse_preserves_raw_text_after_strip(parser):
    result = parser.parse("  crie arquivo teste.py conteúdo  ")

    assert result.raw == "crie arquivo teste.py conteúdo"


def test_extract_target_delete_clears_instruction(parser):
    target, instruction = parser._extract_target_and_instruction(
        "arquivo teste.py conteúdo",
        "delete",
    )

    assert target == "teste.py"
    assert instruction == ""


def test_extract_target_fallback_delete_clears_instruction(parser):
    target, instruction = parser._extract_target_and_instruction(
        "teste.py conteúdo",
        "delete",
    )

    assert target == "teste.py"
    assert instruction == ""


def test_parse_case_insensitive_action(parser):
    result = parser.parse("CRIE arquivo teste.py conteúdo")

    assert result.action == "create"
    assert result.target == "teste.py"
    assert result.instruction == "conteúdo"


def test_parse_case_insensitive_analyze(parser):
    result = parser.parse("ANÁLISE do projeto")

    assert result.action == "analyze"
    assert result.target == ""
    assert result.instruction == "ANÁLISE do projeto"


def test_extract_target_case_insensitive_pattern(parser):
    target, instruction = parser._extract_target_and_instruction(
        "UM ARQUIVO CHAMADO teste.py conteúdo",
        "create",
    )

    assert target == "teste.py"
    assert instruction == "conteúdo"

@pytest.mark.parametrize(
    "remainder",
    [
        "um arquivo chamado teste.py conteúdo que deve ser ignorado",
        'arquivo "teste.py", conteúdo que deve ser ignorado',
        "arquivo de arquivo.py conteúdo que deve ser ignorado",
    ],
)
def test_extract_target_delete_clears_instruction_for_all_special_patterns(
    parser,
    remainder,
):
    target, instruction = parser._extract_target_and_instruction(
        remainder,
        "delete",
    )

    assert target in {"teste.py", "de"}
    assert instruction == ""


@pytest.mark.parametrize(
    "remainder, expected_target",
    [
        (
            "um arquivo chamado teste.py conteúdo que deve ser ignorado",
            "teste.py",
        ),
        (
            'arquivo "teste.py", conteúdo que deve ser ignorado',
            "teste.py",
        ),
        (
            "arquivo de arquivo.py conteúdo que deve ser ignorado",
            "de",
        ),
    ],
)
def test_extract_target_delete_clears_instruction_for_all_special_patterns(
    parser,
    remainder,
    expected_target,
):
    target, instruction = parser._extract_target_and_instruction(
        remainder,
        "delete",
    )

    assert target == expected_target
    assert instruction == ""


def test_core_main_entrypoint_calls_cli_main(monkeypatch):
    import runpy

    called = []

    def fake_main():
        called.append(True)

    import cli

    monkeypatch.setattr(cli, "main", fake_main)

    runpy.run_module("core.__main__", run_name="__main__")

    assert called == [True]
