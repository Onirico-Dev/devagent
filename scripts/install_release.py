#!/usr/bin/env python3
"""Instalador seguro de releases CI do DevAgent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
import zlib
from email.parser import Parser
from pathlib import Path

DEFAULT_REPO = "Onirico-Dev/devagent"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_run_created_at(value):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None

    return parsed


def select_run(runs, commit=None):
    if commit is not None and (
        not isinstance(commit, str)
        or not COMMIT_RE.fullmatch(commit)
    ):
        raise ValueError("SHA de commit inválido.")

    candidates = []

    for run in runs:
        if not isinstance(run, dict):
            continue

        database_id = run.get("databaseId")
        if (
            isinstance(database_id, bool)
            or not isinstance(database_id, int)
            or database_id <= 0
        ):
            continue

        created_at = _parse_run_created_at(run.get("createdAt"))
        if created_at is None:
            continue

        sha = run.get("headSha")
        if (
            run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("headBranch") != "master"
            or run.get("workflowName") != "CI"
            or run.get("event") != "push"
            or not isinstance(sha, str)
            or not COMMIT_RE.fullmatch(sha)
            or (commit is not None and sha != commit)
        ):
            continue

        candidates.append((created_at, run))

    if not candidates:
        raise ValueError("Nenhuma execução CI aprovada encontrada.")

    return max(candidates, key=lambda item: item[0])[1]


def validate_artifact(artifact_dir, expected_commit):
    if not COMMIT_RE.fullmatch(expected_commit):
        raise ValueError("SHA esperado inválido.")

    root = Path(artifact_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Diretório do artefato inválido.")
    root = root.resolve(strict=True)

    report_path = root / "release-report.json"
    if report_path.is_symlink() or not report_path.is_file():
        raise ValueError("Relatório ausente ou inválido.")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Relatório JSON inválido.") from exc

    if not isinstance(report, dict):
        raise ValueError("Formato do relatório inválido.")
    if report.get("overall") != "PASS":
        raise ValueError("Release não aprovada pelo relatório.")
    if report.get("commit") != expected_commit:
        raise ValueError("Commit do relatório divergente.")

    if not isinstance(report.get("version"), str) or not report["version"].strip():
        raise ValueError("Versão inválida.")

    relative = report.get("wheel")
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Caminho do wheel inválido.")

    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or "." in relative_path.parts
    ):
        raise ValueError("Caminho do wheel inseguro.")

    wheel = root / relative_path
    if wheel.is_symlink() or not wheel.is_file():
        raise ValueError("Wheel ausente ou link simbólico.")

    wheel = wheel.resolve(strict=True)
    try:
        wheel.relative_to(root)
    except ValueError as exc:
        raise ValueError("Wheel fora do diretório autorizado.") from exc

    size = report.get("wheel_size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("Tamanho declarado inválido.")
    if wheel.stat().st_size != size:
        raise ValueError("Tamanho do wheel divergente.")

    digest = report.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("SHA-256 declarado inválido.")

    hasher = hashlib.sha256()
    with wheel.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)

    if hasher.hexdigest() != digest:
        raise ValueError("Integridade SHA-256 não confirmada.")

    return wheel


def validate_wheel_metadata(wheel, expected_version):
    wheel = Path(wheel)
    if wheel.is_symlink() or not wheel.is_file():
        raise ValueError("Wheel inválido.")

    if (
        not isinstance(expected_version, str)
        or not expected_version
        or not re.fullmatch(
            rf"devagent-{re.escape(expected_version)}-[^-]+-[^-]+-[^-]+\.whl",
            wheel.name,
        )
    ):
        raise ValueError("Nome do arquivo wheel divergente.")

    expected_dist_info = f"devagent-{expected_version}.dist-info/METADATA"

    try:
        with zipfile.ZipFile(wheel) as archive:
            if archive.testzip() is not None:
                raise ValueError("Wheel ZIP corrompido.")

            metadata_files = [
                name for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
                and len(Path(name).parts) == 2
            ]
            if len(metadata_files) != 1:
                raise ValueError("METADATA dist-info ausente ou ambíguo.")

            if metadata_files[0] != expected_dist_info:
                raise ValueError("Diretório dist-info divergente.")

            metadata = Parser().parsestr(
                archive.read(metadata_files[0]).decode("utf-8")
            )
    except (OSError, zipfile.BadZipFile, UnicodeError, zlib.error) as exc:
        raise ValueError("Wheel não é um ZIP válido.") from exc

    package_name = re.sub(
        r"[-_.]+",
        "-",
        (metadata.get("Name") or "").strip().lower(),
    )
    if package_name != "devagent":
        raise ValueError("O wheel não contém o pacote DevAgent.")
    if metadata.get("Version") != expected_version:
        raise ValueError("Versão do wheel divergente do relatório.")


def validate_install_dir(destination):
    raw = Path(destination).expanduser()

    if not str(destination).strip():
        raise ValueError("Destino não informado.")
    if raw.is_symlink() or raw.exists():
        raise ValueError("Destino já existe; nada será sobrescrito.")

    resolved = raw.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise ValueError("Não é permitido usar a raiz do sistema.")
    if resolved == Path.home().resolve():
        raise ValueError("Não é permitido usar a raiz pessoal.")
    if resolved == Path.cwd().resolve():
        raise ValueError("Não é permitido instalar no diretório atual.")

    return resolved


def cleanup_destination(destination):
    """Remove somente o destino criado por esta execução."""
    if destination is None:
        return

    try:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
    except OSError as cleanup_error:
        print(f"ERRO DE LIMPEZA: {cleanup_error}", file=sys.stderr)


def run(command, capture=True):
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Comando não encontrado: {command[0]}") from exc

    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"Comando falhou ({result.returncode}): {command[0]}\n{detail}"
        )

    return result


def find_artifact_root(download_dir):
    direct = download_dir / "release-report.json"
    if direct.is_file() and not direct.is_symlink():
        return download_dir

    matches = [
        item for item in download_dir.rglob("release-report.json")
        if item.is_file() and not item.is_symlink()
    ]
    if len(matches) != 1:
        raise ValueError("Não foi encontrado um único relatório no artefato.")

    return matches[0].parent



def validate_installed_environment(python_executable, expected_version):
    """Valida imports instalados, versão e executável da CLI."""

    python_executable = Path(python_executable)
    try:
        resolved_python = python_executable.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "Executável Python do ambiente inválido."
        ) from exc

    if (
        not resolved_python.is_file()
        or not os.access(resolved_python, os.X_OK)
    ):
        raise RuntimeError("Executável Python do ambiente inválido.")

    validation_script = r"""
import importlib
import importlib.metadata
import site
import sys
from pathlib import Path

expected_version = sys.argv[1]
distribution = importlib.metadata.distribution("devagent")

if distribution.version != expected_version:
    raise RuntimeError(
        f"Versão instalada divergente: {distribution.version}"
    )

top_level = distribution.read_text("top_level.txt")
if not top_level:
    raise RuntimeError("top_level.txt ausente ou vazio.")

site_paths = [Path(item).resolve() for item in site.getsitepackages()]
modules = [item.strip() for item in top_level.splitlines() if item.strip()]

if not modules:
    raise RuntimeError("Nenhum módulo publicado foi declarado.")

for name in modules:
    module = importlib.import_module(name)
    origin = getattr(module, "__file__", None)

    if not origin:
        raise RuntimeError(f"Módulo sem origem verificável: {name}")

    resolved = Path(origin).resolve()
    if not any(resolved.is_relative_to(root) for root in site_paths):
        raise RuntimeError(
            f"Módulo carregado fora do ambiente instalado: {name}: {resolved}"
        )

print(distribution.version)
"""

    result = run([
        str(python_executable),
        "-I",
        "-c",
        validation_script,
        expected_version,
    ])

    installed_version = result.stdout.strip()
    if installed_version != expected_version:
        raise RuntimeError("Validação de imports ou versão falhou.")

    executable = python_executable.parent / "devagent"
    if executable.is_symlink() or not executable.is_file():
        raise RuntimeError("Executável devagent ausente ou inválido.")

    version_result = run([str(executable), "--version"])
    if version_result.stdout.strip() != expected_version:
        raise RuntimeError("Versão do executável devagent divergente.")

    help_result = run([str(executable), "--help"])
    help_output = help_result.stdout or ""
    if "DevAgent" not in help_output or "Uso:" not in help_output:
        raise RuntimeError("Ajuda da CLI não apresentou a interface esperada.")

    return installed_version


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Instala uma release validada do DevAgent em venv isolado."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--commit")
    selection.add_argument("--latest", action="store_true")
    parser.add_argument("--install-dir")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args(argv)

    if not args.verify_only and not args.install_dir:
        parser.error("--install-dir é obrigatório, exceto com --verify-only")

    created_destination = None

    try:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
            raise ValueError("Identificador do repositório inválido.")
        if args.repo != DEFAULT_REPO:
            raise ValueError("Instalação permitida somente do repositório oficial.")

        destination = (
            None if args.verify_only
            else validate_install_dir(args.install_dir)
        )

        run(["gh", "auth", "status", "--hostname", "github.com"])

        listing = run([
            "gh", "run", "list",
            "--repo", args.repo,
            "--branch", "master",
            "--workflow", "CI",
            "--status", "completed",
            "--limit", "100",
            "--json",
            "databaseId,headSha,status,conclusion,headBranch,workflowName,createdAt,event",
        ])

        try:
            runs = json.loads(listing.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("JSON de execuções inválido.") from exc

        if not isinstance(runs, list):
            raise RuntimeError("Formato inesperado na resposta do GitHub.")

        selected = select_run(runs, commit=args.commit)
        commit = selected["headSha"]
        run_id = selected.get("databaseId")

        if isinstance(run_id, bool) or not isinstance(run_id, int):
            raise ValueError("ID da execução CI inválido.")

        artifact_name = f"devagent-release-{commit}"

        with tempfile.TemporaryDirectory(prefix="devagent-release-") as temporary:
            download_dir = Path(temporary) / "download"
            download_dir.mkdir()

            run([
                "gh", "run", "download", str(run_id),
                "--repo", args.repo,
                "--name", artifact_name,
                "--dir", str(download_dir),
            ])

            artifact_root = find_artifact_root(download_dir)
            wheel = validate_artifact(artifact_root, commit)

            report = json.loads(
                (artifact_root / "release-report.json").read_text(
                    encoding="utf-8"
                )
            )
            validate_wheel_metadata(wheel, report["version"])

            if args.verify_only:
                print("ARTEFATO VALIDADO")
                print(f"Repositório: {args.repo}")
                print(f"Commit: {commit}")
                print(f"Versão: {report['version']}")
                print(f"Wheel: {wheel.name}")
                print(f"SHA-256: {report['sha256']}")
                return 0

            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.mkdir(mode=0o700)
            created_destination = destination

            venv.EnvBuilder(with_pip=True, symlinks=True).create(destination)

            python_executable = destination / "bin" / "python"
            if not python_executable.is_file():
                python_executable = destination / "Scripts" / "python.exe"
            if not python_executable.is_file():
                raise RuntimeError("Executável Python do venv não encontrado.")

            run([
                str(python_executable),
                "-m", "pip", "install",
                "--disable-pip-version-check",
                str(wheel),
            ], capture=False)

            installed_version = validate_installed_environment(
                python_executable,
                report["version"],
            )

        created_destination = None

        print("INSTALAÇÃO VALIDADA")
        print(f"Repositório: {args.repo}")
        print(f"Commit: {commit}")
        print(f"Versão: {installed_version}")
        print(f"Ambiente isolado: {destination}")
        print(f"Python: {python_executable}")
        return 0

    except KeyboardInterrupt:
        cleanup_destination(created_destination)
        print("ERRO: instalação interrompida pelo usuário.", file=sys.stderr)
        return 130

    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        cleanup_destination(created_destination)
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
