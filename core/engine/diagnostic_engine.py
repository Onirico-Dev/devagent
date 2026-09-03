import re
from pathlib import Path


class DiagnosticEngine:
    def diagnose(self, test_result):
        if not isinstance(test_result, dict):
            raise ValueError(
                "Resultado de testes deve ser um dicionário."
            )

        stdout = test_result.get("stdout", "")
        stderr = test_result.get("stderr", "")

        if not isinstance(stdout, str):
            raise ValueError(
                "stdout do resultado de testes deve ser uma string."
            )

        if not isinstance(stderr, str):
            raise ValueError(
                "stderr do resultado de testes deve ser uma string."
            )

        output = "\n".join(
            part
            for part in [stdout, stderr]
            if part
        )

        if test_result.get("success"):
            return {
                "success": True,
                "error_type": None,
                "message": None,
                "file": None,
                "line": None,
                "raw": output,
            }

        error_type = self._extract_error_type(output)
        file_path = self._extract_file(output)
        line = self._extract_line(output)
        message = self._extract_message(output)

        return {
            "success": False,
            "error_type": error_type,
            "message": message,
            "file": file_path,
            "line": line,
            "raw": output,
        }

    def _extract_error_type(self, output):
        patterns = [
            r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                output,
            )

            if match:
                return match.group(1)

        return "UnknownError"

    def _extract_file(self, output):
        patterns = [
            r'File "([^"]+)", line \d+',
            r"([^:\s]+\.py):\d+",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                output,
            )

            if match:
                return str(
                    Path(match.group(1))
                )

        return None

    def _extract_line(self, output):
        patterns = [
            r'File "[^"]+", line (\d+)',
            r"\.py:(\d+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                output,
            )

            if match:
                return int(
                    match.group(1)
                )

        return None

    def _extract_message(self, output):
        lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip()
        ]

        for line in reversed(lines):
            if "Error:" in line:
                return line

            if "Exception:" in line:
                return line

        if lines:
            return lines[-1]

        return "Erro desconhecido."
