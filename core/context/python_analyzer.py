import ast


class PythonAnalyzer:
    def analyze(self, source: str) -> dict:
        if not isinstance(source, str):
            raise ValueError(
                "O código-fonte deve ser uma string."
            )

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise ValueError(
                f"Código Python inválido: {exc}"
            ) from exc

        imports = []
        functions = []
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(
                    alias.name
                    for alias in node.names
                )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(
                        f"{module}.{alias.name}"
                        if module
                        else alias.name
                    )

            elif isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                functions.append(node.name)

            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)

        return {
            "imports": sorted(set(imports)),
            "functions": sorted(set(functions)),
            "classes": sorted(set(classes)),
        }
