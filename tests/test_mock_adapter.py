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


def test_mock_modify_addition_uses_existing_file_context():
    adapter = MockAdapter()
    instruction = (
        "modifique tests/test_worker.py adicionando "
        "def test_new():\n    pass"
    )
    context = (
        "=== ARQUIVO: tests/test_worker.py ===\n"
        "def existing_test():\n    pass\n\n"
        "=== ANÁLISE PYTHON ===\n"
    )

    result = adapter._build_modify_change(instruction, context)

    assert result["path"] == "tests/test_worker.py"
    assert result["content"] == (
        "def existing_test():\n    pass\n"
        "def test_new():\n    pass\n"
    )


def test_mock_modify_function_expression_generates_valid_function():
    adapter = MockAdapter()
    instruction = (
        "modifique modify_existing_smoke.py adicionando "
        "uma função multiplicar(a, b) que retorne a * b"
    )
    context = (
        "=== ARQUIVO: modify_existing_smoke.py ===\n"
        "def existente(): return 'ORIGINAL'\n"
        "def nova(): return 'NOVO'\n"
        "\n=== ANÁLISE PYTHON ===\n"
    )

    result = adapter._build_modify_change(instruction, context)

    assert result is not None
    assert result["path"] == "modify_existing_smoke.py"
    assert "def existente(): return 'ORIGINAL'" in result["content"]
    assert "def nova(): return 'NOVO'" in result["content"]
    assert "def multiplicar(a, b):" in result["content"]
    assert "return a * b" in result["content"]


def test_mock_modify_invalid_function_expression_does_not_overwrite_file():
    adapter = MockAdapter()
    instruction = (
        "modifique modify_existing_smoke.py adicionando "
        "uma função quebrada(a, b) que retorne isto não é Python válido"
    )
    context = (
        "=== ARQUIVO: modify_existing_smoke.py ===\n"
        "def existente(): return 'ORIGINAL'\n"
        "def nova(): return 'NOVO'\n"
        "\n=== ANÁLISE PYTHON ===\n"
    )

    result = adapter._build_modify_change(instruction, context)

    assert result is None


def test_mock_modify_addition_without_context_returns_none():
    adapter = MockAdapter()
    instruction = (
        "modifique tests/test_worker.py adicionando "
        "def test_new():\n    pass"
    )

    assert adapter._build_modify_change(instruction, "") is None


def test_mock_modify_addition_without_context_returns_none():
    adapter = MockAdapter()
    instruction = (
        "modifique tests/test_worker.py adicionando "
        "def test_new():\\n    pass"
    )

    assert adapter._build_modify_change(instruction, "") is None


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


def test_mock_feedback_syntax_error_preserves_valid_prefix():
    import ast
    import json

    feedback_context = {
        "transaction_id": "tx-feedback-invalid-suffix",
        "status": "rolled_back",
        "failure_type": "syntax_error",
        "repair_attempts": 2,
        "evidence": {
            "error": "SyntaxError: invalid syntax",
        },
        "transaction_metadata": {
            "changes": [
                {
                    "change_type": "modify",
                    "path": "modify_existing_smoke.py",
                    "content": (
                        "def existente(): return 'ORIGINAL'\n"
                        "def nova(): return 'NOVO'\n\n"
                        "def multiplicar(a, b):\n"
                        "    return a * b\n\n"
                        "def somar(a, b):\n"
                        "    return a + b\n"
                        "uma alteração inválida chamada isto não é código Python\n"
                    ),
                    "reason": "falha",
                }
            ]
        },
    }

    response = MockAdapter()._generate_feedback_response(
        "Analise a transação tx-feedback-invalid-suffix",
        "",
        feedback_context,
    )

    data = json.loads(response)
    content = data["changes"][0]["content"]

    ast.parse(content)

    assert "uma alteração inválida chamada isto não é código Python" not in content
    assert "def existente(): return 'ORIGINAL'" in content
    assert "def nova(): return 'NOVO'" in content
    assert "def multiplicar(a, b):" in content
    assert "return a * b" in content
    assert "def somar(a, b):" in content
    assert "return a + b" in content


def test_mock_extract_create_content_supports_com_o_conteudo():
    instruction = 'crie um arquivo cli_smoke.py com o conteúdo print("CLI OK")'

    assert MockAdapter._extract_create_content(instruction) == 'print("CLI OK")'


def test_mock_extract_create_content_returns_empty_when_missing():
    assert MockAdapter._extract_create_content("crie app.py") == ""


def test_mock_repair_flow_rejects_invalid_explicit_content_without_safe_evidence():
    adapter = MockAdapter()

    result = adapter.generate(
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "modifique broken.py contendo isto não é Python válido\n"
        "Erro:\n"
        "SyntaxError"
    )

    assert result == ""


def test_mock_repair_flow_rejects_syntax_error_without_repair_evidence():
    adapter = MockAdapter()

    result = adapter.generate(
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "corrija o problema\n"
        "Erro:\n"
        "SyntaxError"
    )

    assert result == ""


def test_mock_repair_flow_rejects_missing_content_without_repair_evidence():
    adapter = MockAdapter()

    result = adapter.generate(
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "corrija broken.py\n"
        "Erro:\n"
        "SyntaxError"
    )

    assert result == ""


def test_mock_extract_invalid_content_uses_default():
    assert (
        MockAdapter._extract_invalid_content("corrija broken.py")
        == "isto não é Python válido"
    )


def test_mock_repair_semantic_assertion_failure_repairs_constant_return():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\\n"
        "Objetivo original:\\n"
        "crie o arquivo core/adapters/real_repair_probe.py "
        "contendo def soma(a, b): return 4 e crie um teste pytest correspondente\\n"
        "Erro:\\n"
        "E       assert 4 == 5\\n"
        "Saída dos testes:\\n"
        "FAILED test_core/adapters/real_repair_probe.py::test_soma - assert 4 == 5"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/real_repair_probe.py"
    assert result["diagnosis"]
    assert "constante 4" in result["diagnosis"]
    assert result["content"] == "def soma(a, b):\n    return a + b"


def test_mock_repair_semantic_assertion_failure_repairs_wrong_addition():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/real_multiply_probe.py "
        "contendo def multiplicar(a, b): return a + b e crie um teste pytest correspondente que exija que multiplicar(2, 3) == 6\n"
        "Erro:\n"
        "E       assert 5 == 6\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/real_multiply_probe.py::test_multiplicar - assert 5 == 6"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/real_multiply_probe.py"
    assert "operação" in result["diagnosis"].lower()
    assert result["content"] == "def multiplicar(a, b):\n    return a * b"


def test_mock_repair_constant_return_uses_explicit_operands():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/explicit_constant_probe.py "
        "contendo def soma(a, b): return 4 e crie um teste pytest "
        "correspondente que exija que soma(2, 3) == 5\n"
        "Erro:\n"
        "E       assert 4 == 5\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/explicit_constant_probe.py::test_soma - assert 4 == 5"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/explicit_constant_probe.py"
    assert result["content"] == "def soma(a, b):\n    return a + b"


def test_mock_repair_constant_return_does_not_invent_addition_for_non_additive_expectation():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/explicit_constant_probe.py "
        "contendo def multiplicar(a, b): return 4 e crie um teste pytest "
        "correspondente que exija que multiplicar(2, 3) == 6\n"
        "Erro:\n"
        "E       assert 4 == 6\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/explicit_constant_probe.py::test_multiplicar - assert 4 == 6"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/explicit_constant_probe.py"
    assert result["content"] == "def multiplicar(a, b):\n    return a * b"

def test_mock_repair_invalid_function_definition_generates_valid_python():
    adapter = MockAdapter()

    result = json.loads(
        adapter.generate(
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            "crie o arquivo autonomy_repair_smoke.py com conteúdo def quebrada(:\n"
            "Erro:\n"
            "SyntaxError"
        )
    )

    assert result["path"] == "autonomy_repair_smoke.py"
    assert result["content"] == "def quebrada():\n    pass"


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


def test_mock_build_compound_semantic_sum_preserves_parameter_names():
    adapter = MockAdapter()
    instruction = (
        "crie o arquivo calculator.py contendo "
        "função somar(x, y) que retorna a soma dos dois valores "
        "e crie o arquivo test_calculator.py contendo "
        "teste que verifica somar(2, 3) retorna 5"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2

    changes = {change["path"]: change for change in result}

    assert changes["calculator.py"]["content"] == (
        "def somar(x, y):\n"
        "    return x + y\n"
    )
    assert changes["test_calculator.py"]["content"] == (
        "from calculator import somar\n\n"
        "def test_somar():\n"
        "    assert somar(2, 3) == 5\n"
    )


@pytest.mark.parametrize(
    "separator",
    [
        " e ",
        " e e ",
        " e e e ",
    ],
)
def test_mock_build_compound_changes_tolerates_repeated_and_separator(separator):
    adapter = MockAdapter()
    instruction = (
        f"crie arquivo_a.py{separator}"
        "crie arquivo_b.py"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2
    assert result[0]["type"] == "create"
    assert result[0]["path"] == "arquivo_a.py"
    assert result[1]["type"] == "create"
    assert result[1]["path"] == "arquivo_b.py"


def test_mock_build_compound_changes_rejects_trailing_incomplete_operation():
    adapter = MockAdapter()
    instruction = "crie arquivo_a.py e crie arquivo_b.py e crie"

    result = adapter._build_compound_create_changes(instruction)

    assert result == []


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


def test_mock_create_natural_pytest_import_and_assert():
    adapter = MockAdapter()

    instruction = (
        "crie o arquivo test_modify_existing_smoke.py com um teste pytest "
        "que importe multiplicar de modify_existing_smoke e verifique que "
        "multiplicar(3, 4) == 12"
    )

    change = adapter._build_create_change(instruction)

    assert change == {
        "type": "create",
        "path": "test_modify_existing_smoke.py",
        "content": (
            "def test_multiplicar():\n"
            "    from modify_existing_smoke import multiplicar\n"
            "    assert multiplicar(3, 4) == 12"
        ),
        "reason": instruction,
    }

def test_mock_inline_pytest_can_request_explicit_expected_result():
    adapter = MockAdapter()
    instruction = (
        "crie o arquivo core/adapters/real_multiply_probe3.py "
        "contendo def multiplicar(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que multiplicar(2, 3) == 6"
    )

    changes = adapter._build_compound_create_changes(instruction)

    assert changes
    test_change = next(
        item for item in changes
        if item["path"] == "test_core/adapters/real_multiply_probe3.py"
    )
    assert "assert multiplicar(2, 3) == 6" in test_change["content"]

def test_mock_binary_operation_repair_subtraction_to_addition():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/real_add_probe.py "
        "contendo def somar(a, b): return a - b "
        "e crie um teste pytest correspondente que exija "
        "que somar(2, 3) == 5\n"
        "Erro:\n"
        "E       assert -1 == 5\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/real_add_probe.py::test_somar - assert -1 == 5"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/real_add_probe.py"
    assert "operação" in result["diagnosis"].lower()
    assert result["content"] == "def somar(a, b):\n    return a + b"

def test_mock_binary_operation_repair_multiplication_to_division():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/real_divide_probe.py "
        "contendo def dividir(a, b): return a * b "
        "e crie um teste pytest correspondente que exija "
        "que dividir(6, 3) == 2\n"
        "Erro:\n"
        "E       assert 18 == 2\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/real_divide_probe.py::test_dividir - assert 18 == 2"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/real_divide_probe.py"
    assert "operação" in result["diagnosis"].lower()
    assert result["content"] == "def dividir(a, b):\n    return a / b"

def test_mock_binary_operation_repair_rejects_ambiguous_candidates():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/ambiguous_probe.py "
        "contendo def calcular(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que calcular(0, -20) == 0\n"
        "Erro:\n"
        "E       assert -20 == 0\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/ambiguous_probe.py::test_calcular - assert -20 == 0"
    )

    result = adapter._generate_repair_response(prompt)
    assert result == ""

def test_mock_binary_operation_repair_uses_explicit_large_operands():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/range_probe.py "
        "contendo def multiplicar(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que multiplicar(125, 125) == 15625\n"
        "Erro:\n"
        "E       assert 250 == 15625\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/range_probe.py::test_multiplicar - assert 250 == 15625"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/range_probe.py"
    assert result["content"] == "def multiplicar(a, b):\n    return a * b"


def test_mock_binary_operation_repair_preserves_explicit_operator_over_heuristic_fallback():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/explicit_operator_probe.py "
        "contendo def multiplicar(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que multiplicar(2, 4) == 8\n"
        "Erro:\n"
        "E       assert 6 == 8\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/explicit_operator_probe.py::test_multiplicar - assert 6 == 8\n"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/explicit_operator_probe.py"
    assert result["content"] == "def multiplicar(a, b):\n    return a * b"


def test_mock_binary_operation_repair_preserves_negative_explicit_operand():
    adapter = MockAdapter()
    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/negative_operand_probe.py "
        "contendo def multiplicar(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que multiplicar(-2, 4) == -8\n"
        "Erro:\n"
        "E       assert 2 == -8\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/negative_operand_probe.py::test_multiplicar - assert 2 == -8\n"
    )

    result = json.loads(adapter._generate_repair_response(prompt))

    assert result["action"] == "modify"
    assert result["path"] == "core/adapters/negative_operand_probe.py"
    assert result["content"] == "def multiplicar(a, b):\n    return a * b"

def test_binary_repair_fallback_does_not_override_explicit_ambiguity():
    def apply_operation(first, second, operation):
        if operation == "+":
            return first + second
        if operation == "-":
            return first - second
        if operation == "*":
            return first * second
        if operation == "/":
            return None if second == 0 else first / second
        return None

    operator = "+"
    first = 0
    second = -200
    actual = apply_operation(first, second, operator)
    expected = 0

    explicit_candidates = {
        candidate
        for candidate in "+-*/"
        if candidate != operator
        and apply_operation(first, second, candidate) == expected
    }

    assert explicit_candidates == {"*", "/"}

    fallback_candidates = set()

    for fallback_first in range(-100, 101):
        for fallback_second in range(-100, 101):
            if apply_operation(fallback_first, fallback_second, operator) != actual:
                continue

            for candidate in "+-*/":
                if candidate == operator:
                    continue

                if apply_operation(
                    fallback_first,
                    fallback_second,
                    candidate,
                ) == expected:
                    fallback_candidates.add(candidate)

    assert fallback_candidates == {"-"}

    assert len(explicit_candidates) >= 2
    assert len(fallback_candidates) == 1


def test_mock_binary_operation_repair_rejects_zero_division_degenerate_case():
    adapter = MockAdapter()

    instruction = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/zero_division_probe.py "
        "contendo def dividir(a, b): return a + b "
        "e crie um teste pytest correspondente que exija "
        "que dividir(6, 0) == 0\n"
        "Erro:\n"
        "E       assert 6 == 0\n"
        "Saída dos testes:\n"
        "FAILED test_core/adapters/zero_division_probe.py::test_dividir - assert 6 == 0\n"
    )

    assert adapter._generate_repair_response(instruction) == ""



def test_mock_binary_operation_repair_rejects_inconsistent_explicit_case():
    adapter = MockAdapter()

    for name in ("calcular", "multiplicar", "dividir"):
        instruction = (
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            f"crie o arquivo core/adapters/{name}_inconsistent_probe.py "
            f"contendo def {name}(a, b): return a + b "
            "e crie um teste pytest correspondente que exija "
            f"que {name}(5, 5) == 25\n"
            "Erro:\n"
            "E       assert 5 == 25\n"
        )

        assert adapter._generate_repair_response(instruction) == ""

def test_mock_binary_operation_repair_rejects_zero_result_without_semantic_name():
    adapter = MockAdapter()

    for name in ("calcular", "operacao", "processar"):
        instruction = (
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            f"crie o arquivo core/adapters/{name}_probe.py "
            f"contendo def {name}(a, b): return a + b "
            "e crie um teste pytest correspondente que exija "
            f"que {name}(6, 0) == 0\n"
            "Erro:\n"
            "E       assert 6 == 0\n"
            "Saída dos testes:\n"
            f"FAILED test_core/adapters/{name}_probe.py::test_{name} - assert 6 == 0\n"
        )

        assert adapter._generate_repair_response(instruction) == ""


def test_mock_constant_return_rejects_ambiguous_zero_case():
    adapter = MockAdapter()

    prompt = (
        "Você é o módulo de reparo automático do DevAgent.\n"
        "Objetivo original:\n"
        "crie o arquivo core/adapters/ambiguous_zero.py "
        "contendo def calcular(a, b): return 4 e crie um teste pytest "
        "correspondente que exija que calcular(0, 0) == 0\n"
        "Erro:\n"
        "E       assert 4 == 0\n"
    )

    assert adapter._generate_repair_response(prompt) == ""


def test_mock_constant_return_uses_unique_explicit_operation():
    adapter = MockAdapter()

    cases = (
        ("multiplicar", 5, 5, 25, "*"),
        ("subtrair", 5, 5, 0, "-"),
    )

    for name, first, second, expected, operation in cases:
        prompt = (
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            f"crie o arquivo core/adapters/{name}_unique.py "
            f"contendo def {name}(a, b): return 4 e crie um teste pytest "
            f"correspondente que exija que {name}({first}, {second}) == {expected}\n"
            "Erro:\n"
            f"E       assert 4 == {expected}\n"
        )

        result = json.loads(
            adapter._generate_repair_response(prompt)
        )

        assert result["action"] == "modify"
        assert result["content"] == (
            f"def {name}(a, b):\n"
            f"    return a {operation} b"
        )


def test_mock_binary_operation_without_explicit_operands_does_not_use_bruteforce_fallback():
    adapter = MockAdapter()

    cases = (
        ("somar", "-", -1, 5),
        ("dividir", "*", 18, 2),
    )

    for name, operator, actual, expected in cases:
        prompt = (
            "Você é o módulo de reparo automático do DevAgent.\n"
            "Objetivo original:\n"
            f"crie o arquivo core/adapters/{name}_no_operands_probe.py "
            f"contendo def {name}(a, b): return a {operator} b "
            "e crie um teste pytest correspondente\n"
            "Erro:\n"
            f"E       assert {actual} == {expected}\n"
        )

        result = adapter._generate_repair_response(prompt)

        assert result == ""

def test_mock_repair_semantic_operation_rejects_invalid_shape():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return a + c "
        "Erro: assert 4 == 5 "
        "e crie um teste para somar(2, 3) == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_semantic_operation_rejects_invalid_numeric_error():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return a + b "
        "Erro: assert x == 5 "
        "e crie um teste para somar(2, 3) == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_constant_numeric_conversion_failure(monkeypatch):
    import builtins
    from core.adapters.mock import MockAdapter

    original_float = builtins.float

    def fail_returned_value(value):
        if value == "4":
            raise ValueError("valor inválido")
        return original_float(value)

    monkeypatch.setattr(builtins, "float", fail_returned_value)

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return 4 "
        "Erro: assert 4 == 5"
    )

    result = MockAdapter()._generate_repair_response(prompt)

    assert result == ""


def test_mock_repair_constant_explicit_numeric_conversion_failure(monkeypatch):
    import builtins
    from core.adapters.mock import MockAdapter

    original_float = builtins.float

    def fail_explicit_value(value):
        if value == "2":
            raise ValueError("valor inválido")
        return original_float(value)

    monkeypatch.setattr(builtins, "float", fail_explicit_value)

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return 4 "
        "Erro: assert 4 == 5 "
        "e crie um teste para somar(2, 3) == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_operation_numeric_conversion_failure(monkeypatch):
    import builtins
    from core.adapters.mock import MockAdapter

    original_float = builtins.float

    def fail_actual_value(value):
        if value == "4":
            raise ValueError("valor inválido")
        return original_float(value)

    monkeypatch.setattr(builtins, "float", fail_actual_value)

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return a + b "
        "Erro: assert 4 == 5 "
        "e crie um teste para somar(2, 3) == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_operation_explicit_numeric_conversion_failure(monkeypatch):
    import builtins
    from core.adapters.mock import MockAdapter

    original_float = builtins.float

    def fail_explicit_value(value):
        if value == "2":
            raise ValueError("valor inválido")
        return original_float(value)

    monkeypatch.setattr(builtins, "float", fail_explicit_value)

    prompt = (
        "corrija reparo.py "
        "def somar(a, b): return a + b "
        "Erro: assert 4 == 5 "
        "e crie um teste para somar(2, 3) == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_rejects_unknown_semantic_operation():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py "
        "def desconhecida(a, b): return 4 "
        "Erro: assert 4 == 5"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_operation_division_by_zero_returns_none():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py "
        "def dividir(a, b): return a / b "
        "Erro: assert 1 == 2 "
        "e crie um teste para dividir(1, 0) == 1"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_extracts_natural_pytest_content():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py contendo "
        "um teste pytest chamado test_smoke que faça a asserção "
        "de que 2 + 2 é igual a 4"
    )

    result = MockAdapter()._generate_repair_response(prompt)

    assert '"action": "modify"' in result
    assert '"path": "reparo.py"' in result
    assert "def test_smoke():" in result
    assert "assert 2 + 2 == 4" in result


def test_mock_planner_accepts_direct_instruction():
    from core.adapters.mock import MockAdapter

    result = MockAdapter().generate(
        "crie o arquivo teste.py contendo def teste(): return 1"
    )

    assert result


def test_mock_planner_processes_valid_feedback_context():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-feedback",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {
            "error": "falha de execução",
        },
        "transaction_metadata": {
            "changes": [
                {
                    "path": "teste.py",
                    "content": "def teste():\n    return 1",
                    "change_type": "modify",
                }
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija a falha\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback, ensure_ascii=False)
    )

    result = MockAdapter().generate(prompt)

    parsed = json.loads(result)

    assert parsed["changes"]
    assert parsed["changes"][0]["path"] == "teste.py"


def test_mock_planner_strips_feedback_json_instruction():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-feedback-marker",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {
            "error": "falha",
        },
        "transaction_metadata": {
            "changes": [],
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija a falha\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        "Retorne SOMENTE JSON válido.\n"
        + json.dumps(feedback, ensure_ascii=False)
    )

    result = MockAdapter().generate(prompt)

    assert result
    assert json.loads(result)["changes"] == []


def test_mock_planner_ignores_invalid_feedback_json():
    from core.adapters.mock import MockAdapter

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija a falha\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        "{json inválido"
    )

    result = MockAdapter().generate(prompt)

    assert result


def test_mock_feedback_normalizes_non_dict_evidence():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-evidence",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": "inválido",
        "transaction_metadata": {"changes": []},
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"] == []


def test_mock_feedback_normalizes_non_dict_transaction_metadata():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-metadata",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": "inválido",
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"] == []


def test_mock_feedback_normalizes_non_list_changes():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-changes",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": {"changes": "inválido"},
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"] == []


def test_mock_feedback_skips_non_dict_change():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-invalid-change",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                "registro inválido",
                {
                    "path": "teste.py",
                    "content": "x = 1",
                    "change_type": "modify",
                },
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert len(result["changes"]) == 1
    assert result["changes"][0]["path"] == "teste.py"


def test_mock_feedback_skips_empty_change_path():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-empty-path",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                {
                    "path": "",
                    "content": "x = 1",
                    "change_type": "modify",
                },
                {
                    "path": "teste.py",
                    "content": "x = 1",
                    "change_type": "modify",
                },
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert len(result["changes"]) == 1
    assert result["changes"][0]["path"] == "teste.py"


def test_mock_feedback_normalizes_invalid_change_type():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-type",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                {
                    "path": "teste.py",
                    "content": "x = 1",
                    "change_type": "unsupported",
                }
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"][0]["type"] == "modify"


def test_mock_feedback_strips_content_prefix():
    import json
    from core.adapters.mock import MockAdapter

    feedback = {
        "transaction_id": "tx-content-prefix",
        "status": "failed",
        "failure_type": "execution_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                {
                    "path": "teste.py",
                    "content": "com o conteúdo def teste():\n    return 1",
                    "change_type": "modify",
                }
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"][0]["content"].startswith("def teste():")


def test_mock_repair_semantic_division_by_zero_is_ambiguous():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py contendo "
        "def dividir(a, b): return 1 "
        "Erro: assert 1 == 2 "
        "e crie um teste para dividir(1, 0) == 1"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""


def test_mock_repair_semantic_multiple_candidate_operations_are_rejected():
    from core.adapters.mock import MockAdapter

    prompt = (
        "corrija reparo.py contendo "
        "def somar(a, b): return 1 "
        "Erro: assert 1 == 2 "
        "e crie um teste para somar(1, 0) == 1"
    )

    assert MockAdapter()._generate_repair_response(prompt) == ""

def test_mock_feedback_syntax_error_without_valid_line_stops_repair(monkeypatch):
    import ast
    import json
    from core.adapters.mock import MockAdapter

    original_parse = ast.parse

    def parse_without_line(*args, **kwargs):
        error = SyntaxError("erro sintático")
        error.lineno = None
        raise error

    monkeypatch.setattr(ast, "parse", parse_without_line)

    feedback = {
        "transaction_id": "tx-no-line",
        "status": "failed",
        "failure_type": "syntax_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                {
                    "path": "arquivo.py",
                    "content": "linha inválida",
                    "change_type": "modify",
                }
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija a falha\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"][0]["content"] == "linha inválida"


def test_mock_feedback_syntax_error_exhausts_all_lines(monkeypatch):
    import ast
    import json
    from core.adapters.mock import MockAdapter

    def parse_always_fails(*args, **kwargs):
        error = SyntaxError("erro sintático")
        error.lineno = 1
        raise error

    monkeypatch.setattr(ast, "parse", parse_always_fails)

    feedback = {
        "transaction_id": "tx-exhausted",
        "status": "failed",
        "failure_type": "syntax_error",
        "evidence": {},
        "transaction_metadata": {
            "changes": [
                {
                    "path": "arquivo.py",
                    "content": "linha um\nlinha dois\nlinha três",
                    "change_type": "modify",
                }
            ]
        },
    }

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija a falha\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        + json.dumps(feedback)
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert result["changes"][0]["content"] == "\n"

def test_mock_compound_create_preserves_numeric_return():
    import json
    from core.adapters.mock import MockAdapter

    prompt = (
        "INSTRUÇÃO DO USUÁRIO: "
        "adicione uma função calcular(x) em um novo arquivo calculo.py "
        "retorne 42, e crie um teste pytest correspondente"
    )

    result = json.loads(MockAdapter().generate(prompt))

    change = next(
        item for item in result["changes"]
        if item["path"] == "calculo.py"
    )

    assert "return 42" in change["content"]


def test_mock_compound_create_repr_non_literal_return():
    import json
    from core.adapters.mock import MockAdapter

    prompt = (
        "INSTRUÇÃO DO USUÁRIO: "
        "adicione uma função calcular(x) em um novo arquivo calculo.py "
        "retorne resultado, e crie um teste pytest correspondente"
    )

    result = json.loads(MockAdapter().generate(prompt))

    change = next(
        item for item in result["changes"]
        if item["path"] == "calculo.py"
    )

    assert "return 'resultado'" in change["content"]

def test_mock_compound_create_returns_multiple_valid_changes():
    import json
    from core.adapters.mock import MockAdapter

    prompt = (
        "INSTRUÇÃO DO USUÁRIO: "
        "crie arquivo_a.py e arquivo_b.py"
    )

    result = json.loads(MockAdapter().generate(prompt))

    assert [change["path"] for change in result["changes"]] == [
        "arquivo_a.py",
        "arquivo_b.py",
    ]

def test_mock_compound_create_clears_changes_when_planner_change_fails(monkeypatch):
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()
    calls = []

    def build_change(instruction, context=""):
        calls.append(instruction)
        if instruction == "crie arquivo_b.py":
            return None
        return {
            "type": "create",
            "path": instruction,
            "content": "",
            "reason": instruction,
        }

    monkeypatch.setattr(adapter, "_build_planner_change", build_change)

    result = adapter._build_compound_create_changes(
        "crie arquivo_a.py e arquivo_b.py"
    )

    assert result == []
    assert calls == ["crie arquivo_a.py", "crie arquivo_b.py"]


def test_mock_modify_uses_regression_addition():
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()

    request = (
        "novo teste chamado test_exhausted. "
        "O teste deve criar uma transação com metadata contendo "
        "repair_cycle com remaining igual a 0, executar o Worker e "
        "verificar que a instrução não aparece em retry_instructions."
    )

    context = "=== ARQUIVO: worker.py ===\nconteudo existente\n"

    result = adapter._build_modify_change(
        "modifique worker.py " + request,
        context,
    )

    assert result is not None
    assert "def test_exhausted():" in result["content"]


def test_mock_modify_returns_none_for_unrecognized_para_transformation():
    from core.adapters.mock import MockAdapter

    result = MockAdapter()._build_modify_change(
        "modifique arquivo.py para transformar alguma coisa",
        "=== ARQUIVO: arquivo.py ===\nconteudo existente\n",
    )

    assert result is None


def test_mock_extract_repair_path_matches_explicit_arquivo_pattern():
    from core.adapters.mock import MockAdapter

    result = MockAdapter._extract_repair_path(
        "corrija o arquivo nested/modulo.py"
    )

    assert result == "nested/modulo.py"


def test_mock_extract_invalid_content_returns_marked_content():
    from core.adapters.mock import MockAdapter

    result = MockAdapter._extract_invalid_content(
        "corrija arquivo.py contendo def broken(:"
    )

    assert result == "def broken(:"

def test_mock_module_create_rejects_invalid_parameter_names():
    from core.adapters.mock import MockAdapter

    instruction = (
        "crie módulo calculo.py contendo "
        "função somar(x, 1) retorna a soma dos dois valores e "
        "crie arquivo test_calculo.py contendo "
        "teste que verifica somar(2, 3) retorna 5"
    )

    result = MockAdapter()._build_compound_create_changes(instruction)

    assert result == []

def test_mock_compound_create_skips_empty_action_part():
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()

    result = adapter._build_compound_create_changes(
        "crie arquivo_a.py e e crie arquivo_b.py"
    )

    assert len(result) == 2

def test_mock_compound_create_returns_empty_when_part_cannot_be_planned():
    from core.adapters.mock import MockAdapter

    adapter = MockAdapter()

    result = adapter._build_compound_create_changes(
        "crie arquivo_a.py e modifique"
    )

    assert result == []

def test_mock_repair_constant_return_falls_through_when_arguments_are_not_two_identifiers():
    adapter = MockAdapter()

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "corrija o erro em soma(a, b, c) que deve retornar 5 "
        "quando chamada com 2 e 3\n"
        "ERRO:\n"
        "AssertionError: esperado 5, obtido 6"
    )

    result = adapter._generate_repair_response(prompt)

    assert isinstance(result, str)


def test_mock_generate_ignores_valid_feedback_json_that_is_not_a_dict():
    adapter = MockAdapter()

    prompt = (
        "INSTRUÇÃO DO USUÁRIO:\n"
        "crie app.py contendo print('ok')\n"
        "CONTEXTO DE FEEDBACK DA TRANSAÇÃO:\n"
        "[1, 2, 3]\n"
    )

    result = json.loads(adapter.generate(prompt))

    assert result["objective"].startswith("crie app.py contendo print('ok')")
    assert "[1, 2, 3]" in result["objective"]
    assert result["changes"]


def test_mock_feedback_change_without_string_content_is_still_appended():
    adapter = MockAdapter()

    feedback_context = {
        "transaction_id": "tx-non-string-content",
        "status": "rolled_back",
        "failure_type": "runtime_error",
        "repair_attempts": 1,
        "evidence": {"error": "erro de execução"},
        "transaction_metadata": {
            "changes": [
                {
                    "change_type": "modify",
                    "path": "runtime_probe.py",
                    "content": None,
                    "reason": "falha",
                }
            ]
        },
    }

    result = json.loads(
        adapter._generate_feedback_response(
            "Analise a transação tx-non-string-content",
            "",
            feedback_context,
        )
    )

    assert result["changes"][0]["path"] == "runtime_probe.py"
    assert "content" not in result["changes"][0]


def test_mock_compound_create_falls_back_to_general_case_when_function_test_pair_is_incomplete():
    adapter = MockAdapter()

    instruction = (
        "crie arquivo calculator.py contendo uma função add(a, b) "
        "que retorna a soma dos dois valores e crie arquivo test_calculator.py "
        "contendo um teste pytest sem especificar o resultado"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2
    assert result[0]["path"] == "calculator.py"
    assert result[1]["path"] == "test_calculator.py"

def test_mock_compound_create_ignores_empty_action_parts():
    adapter = MockAdapter()

    instruction = (
        "crie first.py contendo print('a') "
        "e e "
        "crie second.py contendo print('b')"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert len(result) == 2
    assert result[0]["path"] == "first.py"
    assert result[1]["path"] == "second.py"

def test_mock_extract_create_content_skips_empty_marker_and_uses_next_marker():
    instruction = "crie app.py com conteúdo contendo print('ok')"

    result = MockAdapter._extract_create_content(instruction)

    assert result == "print('ok')"


def test_mock_extract_create_content_returns_empty_for_empty_marker():
    result = MockAdapter._extract_create_content(
        "crie app.py contendo "
    )

    assert result == ""

def test_mock_repair_constant_return_with_three_arguments_falls_through_to_operation_repair():
    adapter = MockAdapter()

    prompt = (
        "corrija o erro em soma(a, b, c) "
        "que retorna 6 quando deveria retornar 5. "
        "A chamada soma(2, 3) == 5 falhou. "
        "AssertionError: esperado 5, obtido 6"
    )

    result = adapter._generate_repair_response(prompt)

    assert isinstance(result, str)

def test_mock_repair_constant_return_with_three_parameters_falls_through():
    adapter = MockAdapter()
    prompt = (
        "corrija soma.py contendo "
        "def soma(a, b, c):\n"
        "    return 6\n"
        "assert 6 == 5\n"
        "Erro: AssertionError"
    )

    result = adapter._generate_repair_response(prompt)

    assert isinstance(result, str)

def test_mock_extract_invalid_content_empty_marker_falls_through_to_default():
    result = MockAdapter._extract_invalid_content(
        "crie arquivo.py contendo "
    )

    assert result == "isto não é Python válido"

def test_mock_compound_create_rejects_invalid_function_parameters():
    adapter = MockAdapter()

    instruction = (
        "crie arquivo calculator.py contendo "
        "função add(a, 1) que retorna a soma dos dois valores "
        "e crie arquivo test_calculator.py contendo "
        "teste que verifica add(2, 3) retorna 5"
    )

    result = adapter._build_compound_create_changes(instruction)

    assert result == []


def test_mock_extract_create_content_converts_natural_function():
    instruction = (
        'criar um arquivo hello.py contendo '
        'uma função saudacao() que retorne "Olá, mundo!"'
    )

    assert (
        MockAdapter._extract_create_content(instruction)
        == 'def saudacao():\n    return "Olá, mundo!"'
    )
