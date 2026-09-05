import pytest

from core.context.python_analyzer import PythonAnalyzer


def test_python_analyzer_extracts_imports_functions_and_classes():
    source = """
import os
import json as js
from pathlib import Path
from core.example import Example

def hello():
    pass

async def run():
    pass

class Service:
    pass
"""

    result = PythonAnalyzer().analyze(source)

    assert result == {
        "imports": [
            "core.example.Example",
            "json",
            "os",
            "pathlib.Path",
        ],
        "functions": ["hello", "run"],
        "classes": ["Service"],
    }


def test_python_analyzer_handles_import_from_without_module():
    result = PythonAnalyzer().analyze(
        "from . import example\n"
    )

    assert result["imports"] == ["example"]


def test_python_analyzer_deduplicates_symbols_and_imports():
    source = """
import os
import os

def hello():
    pass

def hello():
    pass

class Service:
    pass

class Service:
    pass
"""

    result = PythonAnalyzer().analyze(source)

    assert result == {
        "imports": ["os"],
        "functions": ["hello"],
        "classes": ["Service"],
    }


@pytest.mark.parametrize(
    "value",
    [None, 123, [], {}],
)
def test_python_analyzer_rejects_non_string_source(value):
    with pytest.raises(
        ValueError,
        match="código-fonte deve ser uma string",
    ):
        PythonAnalyzer().analyze(value)


def test_python_analyzer_rejects_invalid_python():
    with pytest.raises(
        ValueError,
        match="Código Python inválido",
    ):
        PythonAnalyzer().analyze(
            "def broken(:\n"
        )
