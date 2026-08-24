import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()

    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "test@devagent.local"],
        cwd=root,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "DevAgent Test"],
        cwd=root,
        check=True,
    )

    return root
