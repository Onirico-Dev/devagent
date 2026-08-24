import subprocess
import sys
from pathlib import Path


class TestRunner:

    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def _check_python_syntax(self, files):

        errors = []

        for relative_path in files:

            path = (self.root / relative_path).resolve()

            if path.suffix != ".py":
                continue

            if not path.exists():
                continue

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "py_compile",
                    str(path),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:

                errors.append({
                    "file": relative_path,
                    "stderr": result.stderr,
                })

        return errors

    def run(self, files=None):

        files = files or []

        syntax_errors = self._check_python_syntax(
            files
        )

        if syntax_errors:

            return {
                "success": False,
                "returncode": 1,
                "stdout": "",
                "stderr": str(syntax_errors),
            }

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
            ],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
