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


def test_mock_legacy_create_content_extracts_marker_content():
    adapter = MockAdapter()

    assert (
        adapter._extract_legacy_create_content(
            "crie app.py contendo print('ok')"
        )
        == "print('ok')"
    )


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
        "crie o arquivo app.py com conteúdo print('ok')",
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



def test_mock_modify_addition_preserves_existing_context():
    adapter = MockAdapter()

    context = (
        "=== CONTEXTO DO PROJETO ===\n"
        "=== ARQUIVO: target.py ===\n"
        "def target():\n"
        "    return 'old'\n"
        "=== ANÁLISE PYTHON ===\n"
        "IMPORTS: []\n"
        "FUNÇÕES: ['target']\n"
        "CLASSES: []\n"
    )

    result = adapter._build_planner_change(
        "modifique target.py adicionando print('ok')",
        context,
    )

    assert result == {
        "type": "modify",
        "path": "target.py",
        "content": (
            "def target():\n"
            "    return 'old'\n"
            "print('ok')\n"
        ),
        "reason": (
            "modifique target.py adicionando print('ok')"
        ),
    }


def test_mock_modify_add_function_preserves_existing_context():
    adapter = MockAdapter()

    context = (
        "=== CONTEXTO DO PROJETO ===\n"
        "=== ARQUIVO: self_evolution_smoke.py ===\n"
        "def hello():\n"
        '    return "HELLO DEVAGENT"\n'
        "=== ANÁLISE PYTHON ===\n"
        "IMPORTS: []\n"
        "FUNÇÕES: ['hello']\n"
        "CLASSES: []\n"
    )

    result = adapter._build_planner_change(
        'modifique self_evolution_smoke.py para adicionar uma função goodbye() '
        'que retorne "GOODBYE DEVAGENT"',
        context,
    )

    assert result["type"] == "modify"
    assert result["path"] == "self_evolution_smoke.py"
    assert result["content"] == (
        "def hello():\n"
        '    return "HELLO DEVAGENT"\n'
        "\n"
        "def goodbye():\n"
        '    return "GOODBYE DEVAGENT"\n'
    )


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



def test_mock_legacy_create_content_returns_empty_for_unknown_instruction():
    adapter = MockAdapter()
    assert (
        adapter._extract_legacy_create_content(
            "faça qualquer coisa"
        )
        == ""
    )

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


def test_mock_feedback_corrects_syntax_error_from_transaction_metadata():
    import json

    feedback_context = {
        "transaction_id": "tx-feedback-syntax",
        "status": "rolled_back",
        "failure_type": "syntax_error",
        "repair_attempts": 2,
        "evidence": {
            "tests": {
                "success": False,
                "returncode": 1,
                "stderr": "SyntaxError: invalid syntax",
            },
            "repair": {
                "attempts": 2,
            },
        },
        "transaction_metadata": {
            "changes": [
                {
                    "change_type": "create",
                    "path": "feedback_smoke.py",
                    "content": "def broken(:",
                    "reason": "criação do arquivo",
                }
            ]
        },
    }

    response = MockAdapter()._generate_feedback_response(
        "Analise a transação tx-feedback-syntax",
        "",
        feedback_context,
    )

    data = json.loads(response)
    change = data["changes"][0]

    assert change["type"] == "create"
    assert change["path"] == "feedback_smoke.py"
    assert change["content"] == "def broken():\n    pass\n"


def test_mock_extract_create_content_supports_com_o_conteudo():
    instruction = 'crie um arquivo cli_smoke.py com o conteúdo print("CLI OK")'

    assert MockAdapter._extract_create_content(instruction) == 'print("CLI OK")'


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


def test_mock_generate_legacy_repair_request_route_returns_empty():
    adapter = MockAdapter()

    assert adapter.generate(
        "REPAIR REQUEST: corrija broken.py"
    ) == ""


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


def test_extract_create_content_natural_test_smoke():
    instruction = (
        "o arquivo deve conter um teste pytest chamado "
        "test_smoke que faça a asserção de que 2 + 2 é igual a 4"
    )

    assert MockAdapter._extract_create_content(instruction) == (
        "def test_smoke():\n"
        "    assert 2 + 2 == 4"
    )


def test_mock_modify_content_marker_is_extracted():
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()

    cases = (
        'modifique app.py com conteúdo print("ok")',
        'modifique app.py com conteudo print("ok")',
        'modifique app.py contendo print("ok")',
    )

    for instruction in cases:
        change = adapter._build_modify_change(instruction)

        assert change["type"] == "modify"
        assert change["path"] == "app.py"
        assert change["content"] == 'print("ok")'

def test_mock_adapter_creates_multiple_files_from_compound_instruction():
    from core.adapters.mock import MockAdapter

    instruction = (
        "crie um módulo calculator.py contendo uma função add(a, b) "
        "que retorna a soma dos dois valores e crie test_calculator.py "
        "contendo um teste pytest que verifica que add(2, 3) retorna 5"
    )

    result = MockAdapter().generate(
        "INSTRUÇÃO DO USUÁRIO:\n"
        f"{instruction}\n"
        "CONTEXTO DO PROJETO:\n"
    )

    import json

    payload = json.loads(result)

    assert len(payload["changes"]) == 2

    changes = {change["path"]: change for change in payload["changes"]}

    assert changes["calculator.py"]["type"] == "create"
    assert "def add(a, b)" in changes["calculator.py"]["content"]
    assert "return a + b" in changes["calculator.py"]["content"]

    assert changes["test_calculator.py"]["type"] == "create"
    assert "def test" in changes["test_calculator.py"]["content"]
    assert "add(2, 3)" in changes["test_calculator.py"]["content"]


def test_mock_build_compound_changes_supports_function_and_pytest():
    adapter = MockAdapter()
    instruction = (
        'adicione uma função hello() em um novo arquivo '
        'self_evolution_smoke.py que retorne "HELLO DEVAGENT" '
        'e crie um teste pytest correspondente'
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2

    changes = {change["path"]: change for change in result}

    assert changes["self_evolution_smoke.py"]["type"] == "create"
    assert 'def hello():' in changes["self_evolution_smoke.py"]["content"]
    assert 'return "HELLO DEVAGENT"' in changes["self_evolution_smoke.py"]["content"]

    assert changes["test_self_evolution_smoke.py"]["type"] == "create"
    assert "from self_evolution_smoke import hello" in changes["test_self_evolution_smoke.py"]["content"]
    assert "def test_hello():" in changes["test_self_evolution_smoke.py"]["content"]
    assert 'assert hello() == "HELLO DEVAGENT"' in changes["test_self_evolution_smoke.py"]["content"]


def test_mock_build_compound_changes_supports_multiple_operations():
    adapter = MockAdapter()

    instruction = (
        "crie app.py contendo print('APP') "
        "e crie test_app.py contendo def test_app():\n"
        "    assert True "
        "e remova old.py"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 3
    assert result[0]["type"] == "create"
    assert result[0]["path"] == "app.py"
    assert result[1]["type"] == "create"
    assert result[1]["path"] == "test_app.py"
    assert result[2]["type"] == "delete"
    assert result[2]["path"] == "old.py"


def test_mock_build_compound_changes_supports_create_and_modify():
    adapter = MockAdapter()

    instruction = (
        "crie app.py contendo print('APP') "
        "e modifique config.py com conteúdo VALUE = 42"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2
    assert result[0]["type"] == "create"
    assert result[0]["path"] == "app.py"
    assert result[1]["type"] == "modify"
    assert result[1]["path"] == "config.py"
    assert result[1]["content"] == "VALUE = 42"


@pytest.mark.parametrize(
    "failure_type",
    [
        "test_failure",
        "execution_error",
        "rollback_error",
        "repair_limit_reached",
        "unknown",
    ],
)
def test_mock_feedback_does_not_apply_syntax_fix_for_other_failure_types(
    failure_type,
):
    import json

    feedback_context = {
        "transaction_id": f"tx-{failure_type}",
        "status": "failed",
        "failure_type": failure_type,
        "repair_attempts": 2,
        "evidence": {
            "error": "SyntaxError: invalid syntax",
            "tests": {
                "success": False,
                "stderr": "SyntaxError: invalid syntax",
            },
        },
        "transaction_metadata": {
            "changes": [
                {
                    "change_type": "create",
                    "path": "broken.py",
                    "content": "def broken(:",
                    "reason": "criação do arquivo",
                }
            ]
        },
    }

    response = MockAdapter()._generate_feedback_response(
        f"Analise a transação tx-{failure_type}",
        "",
        feedback_context,
    )

    data = json.loads(response)
    change = data["changes"][0]

    assert change["content"] == "def broken(:"


def test_mock_adapter_cli_style_function_and_pytest_compound():
    instruction = (
        "crie o arquivo cli_compound_smoke.py contendo "
        "def somar(a, b): return a + b "
        "e crie um teste pytest correspondente"
    )

    result = MockAdapter().generate(
        "INSTRUÇÃO DO USUÁRIO:\n"
        f"{instruction}\n"
        "CONTEXTO DO PROJETO:\n"
    )

    payload = json.loads(result)
    assert len(payload["changes"]) == 2

    changes = {change["path"]: change for change in payload["changes"]}

    assert changes["cli_compound_smoke.py"]["type"] == "create"
    assert "def somar(a, b):" in changes["cli_compound_smoke.py"]["content"]
    assert "return a + b" in changes["cli_compound_smoke.py"]["content"]

    assert changes["test_cli_compound_smoke.py"]["type"] == "create"
    assert "from cli_compound_smoke import somar" in changes[
        "test_cli_compound_smoke.py"
    ]["content"]
    assert "assert somar(2, 3) == 5" in changes[
        "test_cli_compound_smoke.py"
    ]["content"]


def test_mock_adapter_repair_preserves_compound_create_content():
    instruction = (
        "crie o arquivo cli_compound_smoke.py contendo "
        "def somar(a, b): return a + b "
        "e crie um teste pytest correspondente"
    )

    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        f"Objetivo original: {instruction}\n"
        "Erro: SyntaxError"
    )

    result = MockAdapter().generate(prompt)
    payload = json.loads(result)

    assert payload["path"] == "cli_compound_smoke.py"
    assert payload["content"] == (
        "def somar(a, b):\n"
        "    return a + b\n"
    )
    assert "e crie um teste pytest correspondente" not in payload["content"]


def test_feedback_response_repairs_syntax_error():
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()

    feedback_context = {
        "transaction_id": "tx-syntax",
        "status": "rolled_back",
        "failure_type": "syntax_error",
        "evidence": {
            "error": "SyntaxError: invalid syntax",
        },
        "transaction_metadata": {
            "instruction": "criar arquivo cli_recovery_smoke.py com conteúdo def broken(:",
            "changes": [
                {
                    "change_type": "create",
                    "path": "cli_recovery_smoke.py",
                    "content": "def broken(:",
                    "reason": "falha",
                }
            ],
        },
    }

    response = adapter._generate_feedback_response(
        "corrigir",
        "",
        feedback_context,
    )

    import json

    parsed = json.loads(response)
    changes = parsed["changes"]

    assert len(changes) == 1
    assert changes[0]["path"] == "cli_recovery_smoke.py"
    assert changes[0]["content"] == "def broken():\n    pass\n"
    assert changes[0]["content"] != "def broken(:"
