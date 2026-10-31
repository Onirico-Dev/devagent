#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v node >/dev/null 2>&1; then
    echo "ERRO: Node.js não está instalado ou não está no PATH." >&2
    exit 127
fi

echo "Node.js: $(node --version)"
echo "Validando sintaxe do frontend..."

node --check web/app.js
node --check web/test_app.test.js

echo
echo "Executando testes do DevAgent Studio..."
node --test web/test_app.test.js
