import py_compile
import subprocess
import sys
from pathlib import Path


class TestRunner:

    def __init__(self, root="."):
        self.root = Path(root).resolve()

    def _compile_file(self, relative_path):

        target = (self.root / relative_path).resolve()

        if not target.exists():
            return {
                "success": False,
                "returncode": 1,
                "stdout": "",
                "stderr": (
                    f"Arquivo não encontrado: "
                    f"{relative_path}"
                ),
            }

        try:

            py_compile.compile(
                str(target),
                doraise=True,
            )

            return {
                "success": True,
                "returncode": 0,
                "stdout": (
                    f"Syntax OK: {relative_path}"
                ),
                "stderr": "",
            }

        except py_compile.PyCompileError as exc:

            return {
                "success": False,
                "returncode": 1,
                "stdout": "",
                "stderr": str(exc),
            }

    def _run_pytest(self, files):

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *files,
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

    def run(self, files=None):

        if not files:

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

        python_files = [
            file
            for file in files
            if str(file).endswith(".py")
        ]

        test_files = [
            file
            for file in python_files
            if (
                Path(file).name.startswith("test_")
                or Path(file).name.endswith("_test.py")
            )
        ]

        normal_files = [
            file
            for file in python_files
            if file not in test_files
        ]

        results = []

        for file in normal_files:

            results.append(
                self._compile_file(file)
            )

        if test_files:

            results.append(
                self._run_pytest(test_files)
            )

        success = all(
            result["success"]
            for result in results
        )

        stdout = "\n".join(
            result["stdout"]
            for result in results
            if result["stdout"]
        )

        stderr = "\n".join(
            result["stderr"]
            for result in results
            if result["stderr"]
        )

        return {
            "success": success,
            "returncode": (
                0 if success else 1
            ),
            "stdout": stdout,
            "stderr": stderr,
        }
