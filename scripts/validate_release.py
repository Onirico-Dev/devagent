#!/usr/bin/env python3
"""Validação integral e local da distribuição DevAgent."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile

from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_RELATIVE = "scripts/validate_release.py"
EXPECTED_BRANCH = "master"
REQUIRED_ASSETS = {
    "devagent_studio/__init__.py",
    "devagent_studio/index.html",
    "devagent_studio/app.js",
    "devagent_studio/styles.css",
    "api.py",
    "agent.py",
    "main.py",
}
STATIC_ROUTES = {
    "/": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}

RESULTS = {}
ARTIFACT_DIR = None
WORK_DIR = None


def execute(command, *, cwd=ROOT, capture=False):
    print("\n+", " ".join(map(str, command)), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def record(name, function):
    print(f"\n{'=' * 18} {name} {'=' * 18}", flush=True)
    function()
    RESULTS[name] = "PASS"
    print(f"RESULTADO: {name}: PASS", flush=True)


def git_preflight():
    branch = execute(
        ["git", "branch", "--show-current"], capture=True
    ).stdout.strip()

    assert branch == EXPECTED_BRANCH, (
        f"Branch incorreta: {branch!r}; esperada: {EXPECTED_BRANCH}"
    )

    head = execute(
        ["git", "rev-parse", "HEAD"], capture=True
    ).stdout.strip()

    remote = execute(
        ["git", "rev-parse", "origin/master"], capture=True
    ).stdout.strip()

    assert head == remote, "HEAD não está sincronizado com origin/master"

    status = execute(
        ["git", "status", "--porcelain"], capture=True
    ).stdout.splitlines()

    unexpected = [
        line for line in status
        if line[3:] != SCRIPT_RELATIVE
        or not line.startswith("?? ")
    ]

    assert not unexpected, (
        "Working tree contém alterações além do script inicial: "
        + repr(unexpected)
    )

    print("Branch:", branch)
    print("Commit:", head)
    print("Sincronização remota: OK")
    print("Working tree: limpa (ou apenas este script ainda não versionado)")

    return head


def compile_sources():
    sources = [
        ROOT / "api.py",
        ROOT / "agent.py",
        ROOT / "main.py",
    ]
    sources.extend(sorted((ROOT / "core").rglob("*.py")))

    missing = [str(path) for path in sources if not path.is_file()]
    assert not missing, f"Fontes ausentes: {missing}"

    execute([
        sys.executable,
        "-m",
        "py_compile",
        *map(str, sources),
    ])

    print("Fontes compiladas:", len(sources))


def frontend_tests():
    execute(["bash", "scripts/test_frontend.sh"])


def python_tests():
    execute([
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=core",
        "--cov=api",
        "--cov=agent",
        "--cov-report=term-missing",
        "--cov-fail-under=100",
    ])


def configure_artifact_dirs(artifact_dir=None):
    """Configura a saída distribuível e o workspace temporário."""
    global ARTIFACT_DIR, WORK_DIR

    if artifact_dir is None:
        ARTIFACT_DIR = Path(
            tempfile.mkdtemp(prefix="devagent-release-")
        ).resolve()
    else:
        ARTIFACT_DIR = Path(artifact_dir).expanduser().resolve()
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    assert ARTIFACT_DIR.is_dir(), (
        f"Diretório de artefatos inválido: {ARTIFACT_DIR}"
    )

    WORK_DIR = Path(
        tempfile.mkdtemp(prefix="devagent-validation-")
    ).resolve()

    wheel_dir = ARTIFACT_DIR / "wheel"
    wheel_dir.mkdir(parents=True, exist_ok=True)

    existing_wheels = list(wheel_dir.glob("devagent-*.whl"))
    assert not existing_wheels, (
        "O diretório de saída contém wheels antigos: "
        + repr(existing_wheels)
    )

    assert WORK_DIR != ARTIFACT_DIR
    assert ARTIFACT_DIR not in WORK_DIR.parents
    assert WORK_DIR not in ARTIFACT_DIR.parents

    print("Diretório de artefatos:", ARTIFACT_DIR)
    print("Workspace temporário:", WORK_DIR)

    return wheel_dir


def build_wheel(artifact_dir=None):
    wheel_dir = configure_artifact_dirs(artifact_dir)

    execute([
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(ROOT),
    ])

    wheels = list(wheel_dir.glob("devagent-*.whl"))
    assert len(wheels) == 1, (
        f"Esperado exatamente um wheel; encontrados: {wheels}"
    )

    return wheels[0]


def audit_wheel(wheel):
    with open(ROOT / "pyproject.toml", "rb") as file:
        project = tomllib.load(file)

    expected_version = project["project"]["version"]

    with zipfile.ZipFile(wheel) as archive:
        corrupt = archive.testzip()
        assert corrupt is None, f"Arquivo corrompido no wheel: {corrupt}"

        names = set(archive.namelist())

        missing = REQUIRED_ASSETS - names
        assert not missing, (
            f"Arquivos obrigatórios ausentes: {sorted(missing)}"
        )

        metadata_files = [
            name for name in names
            if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_files) == 1, "METADATA ausente ou duplicado"

        metadata = archive.read(metadata_files[0]).decode("utf-8")
        assert f"Version: {expected_version}" in metadata, (
            "Versão do METADATA diverge do pyproject.toml"
        )

        forbidden = [
            name for name in names
            if "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
            or ".devagent_backups/" in name
        ]
        assert not forbidden, (
            f"Arquivos indevidos no wheel: {forbidden}"
        )

    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

    print("Versão:", expected_version)
    print("Arquivos:", len(names))
    print("Tamanho:", wheel.stat().st_size, "bytes")
    print("SHA-256:", digest)

    return expected_version, digest


def isolated_install_and_http(wheel):
    assert ARTIFACT_DIR is not None
    assert WORK_DIR is not None

    environment = WORK_DIR / "venv"
    venv.create(environment, with_pip=True)

    installed_python = environment / "bin" / "python"
    installed_pip = environment / "bin" / "pip"

    execute([
        str(installed_pip),
        "install",
        str(wheel),
    ])

    import_check = r'''
import api
import agent
import core
import devagent_studio
import sys
from pathlib import Path

prefix = Path(sys.prefix).resolve()

for module in (api, agent, core, devagent_studio):
    origin = Path(module.__file__).resolve()
    assert prefix in origin.parents, (
        f"Import fora do ambiente isolado: {module.__name__}: {origin}"
    )
    print(f"IMPORT OK: {module.__name__}: {origin}")

root = Path(api.WEB_ROOT).resolve()
assert root.is_dir()

for name in ("index.html", "app.js", "styles.css"):
    path = root / name
    assert path.is_file() and path.stat().st_size > 0
    print(f"ASSET OK: {name}: {path.stat().st_size} bytes")
'''

    execute([
        str(installed_python),
        "-I",
        "-c",
        import_check,
    ], cwd=WORK_DIR)

    server_code = r'''
import api
from http.server import HTTPServer

server = HTTPServer(("127.0.0.1", 0), api.APIHandler)
print(server.server_port, flush=True)
server.serve_forever()
'''

    server = subprocess.Popen(
        [str(installed_python), "-I", "-c", server_code],
        cwd=WORK_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        port_line = server.stdout.readline().strip()

        assert port_line.isdigit(), (
            "Servidor não iniciou. stderr: "
            + server.stderr.read()
        )

        port = int(port_line)

        for route, filename in STATIC_ROUTES.items():
            connection = HTTPConnection(
                "127.0.0.1", port, timeout=10
            )
            connection.request("GET", route)
            response = connection.getresponse()
            body = response.read()
            headers = response.headers

            assert response.status == 200, (
                f"{route}: HTTP {response.status}"
            )

            assert headers.get_content_type() == (
                "text/html" if route == "/"
                else "application/javascript" if route == "/app.js"
                else "text/css"
            ), f"{route}: Content-Type incorreto"

            assert headers.get("X-Content-Type-Options") == "nosniff"
            assert headers.get("Cache-Control") == "no-cache"
            assert int(headers["Content-Length"]) == len(body)

            installed_file = environment / "lib"

            candidates = list(
                installed_file.glob(
                    f"python*/site-packages/devagent_studio/{filename}"
                )
            )
            assert len(candidates) == 1, (
                f"Asset instalado não localizado: {filename}"
            )
            assert body == candidates[0].read_bytes(), (
                f"{route}: resposta difere do asset instalado"
            )

            print(
                f"HTTP PASS: {route} -> {response.status}, "
                f"{len(body)} bytes"
            )
            connection.close()

    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    print("Imports isolados e integração HTTP: aprovados")


def main():
    parser = argparse.ArgumentParser(
        description="Validação integral da distribuição DevAgent."
    )
    parser.add_argument(
        "--skip-git-preflight",
        action="store_true",
        help="Ignora as verificações locais de branch e sincronização remota.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help=(
            "Diretório dos artefatos distribuíveis. "
            "Por padrão, usa um diretório temporário."
        ),
    )
    args = parser.parse_args()

    print("DEVAGENT RELEASE VALIDATOR")
    print("Repositório:", ROOT)

    commit_holder = {}

    def preflight():
        commit_holder["commit"] = git_preflight()

    if args.skip_git_preflight:
        commit = execute(
            ["git", "rev-parse", "HEAD"], capture=True
        ).stdout.strip()
        RESULTS["GIT PREFLIGHT"] = "SKIPPED (CI mode)"
        print("GIT PREFLIGHT: SKIPPED (CI mode)")
    else:
        record("GIT PREFLIGHT", preflight)
        commit = commit_holder["commit"]

    with open(ROOT / "pyproject.toml", "rb") as file:
        version = tomllib.load(file)["project"]["version"]

    record("COMPILAÇÃO", compile_sources)
    record("TESTES FRONTEND", frontend_tests)
    record("TESTES PYTHON E COBERTURA", python_tests)

    wheel = None

    def build():
        nonlocal wheel
        wheel = build_wheel(args.artifact_dir)

    record("BUILD WHEEL", build)

    audit_result = {}

    def audit():
        expected_version, digest = audit_wheel(wheel)
        audit_result["version"] = expected_version
        audit_result["sha256"] = digest

    record("AUDITORIA DO WHEEL", audit)
    record(
        "INSTALAÇÃO ISOLADA E HTTP",
        lambda: isolated_install_and_http(wheel),
    )

    assert audit_result["version"] == version

    report = {
        "project": "devagent",
        "version": version,
        "commit": commit,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "wheel": wheel.relative_to(ARTIFACT_DIR).as_posix(),
        "wheel_size": wheel.stat().st_size,
        "sha256": audit_result["sha256"],
        "results": RESULTS,
        "overall": "PASS",
    }

    report_path = ARTIFACT_DIR / "release-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 55)
    print("VALIDAÇÃO INTEGRAL DO RELEASE: APROVADA")
    print("Versão:", version)
    print("Commit:", commit)
    print("SHA-256:", audit_result["sha256"])
    print("Wheel:", wheel)
    print("Relatório:", report_path)
    print("Artefatos preservados em:", ARTIFACT_DIR)
    print("=" * 55)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"\nVALIDAÇÃO FALHOU: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        if ARTIFACT_DIR:
            print(
                "Artefatos de diagnóstico preservados em:",
                ARTIFACT_DIR,
                file=sys.stderr,
            )
        raise
