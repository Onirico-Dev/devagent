"""Validação real do frontend pelo mesmo pytest usado nos planos do Studio."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_studio_frontend_node_suite(capsys):
    root = Path(__file__).resolve().parent.parent
    node = shutil.which("node")
    assert node is not None, "Node.js é necessário para validar o Studio."
    env = os.environ.copy()
    env["PYTHON"] = sys.executable
    for filename in ("devagent_studio/app.js", "web/test_app.test.js", "web/test_plan_preview.test.js"):
        syntax = subprocess.run(
            [node, "--check", str(root / filename)], cwd=root, env=env,
            capture_output=True, text=True, timeout=20,
        )
        assert syntax.returncode == 0, syntax.stdout + syntax.stderr
    result = subprocess.run(
        [node, "--test", str(root / "web/test_app.test.js")],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = [line for line in result.stdout.splitlines() if line.lstrip().startswith(
        ("ℹ tests", "ℹ pass", "ℹ fail", "# tests", "# pass", "# fail")
    )]
    with capsys.disabled():
        print("Frontend Node validado:\n" + "\n".join(summary), flush=True)
