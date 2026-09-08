#!/usr/bin/env bash
# TASK-2855 (FEAT-523): editable-install proof for the PEP 420 LLM client
# extraction — a fresh venv with ONLY `ai-parrot` + ONE satellite
# (`ai-parrot-client-groq`) editable-installed must see "groq" registered
# via a real `importlib.metadata` entry point.
#
# Slow / opt-in: creates a throwaway venv from scratch. Not wired into
# the default `pytest` run — invoke directly:
#
#   bash scripts/tests/test_editable_install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT="$(mktemp -d)"
VENV_DIR="${TMP_ROOT}/editable-install-venv"

cleanup() {
    # Remove the whole scratch dir — not just VENV_DIR — since the
    # navconfig bootstrap stub below (env/, etc/) and anything the
    # verification process itself writes relative to its CWD (agents/,
    # logs/, ...) all land as siblings of the venv, under TMP_ROOT.
    rm -rf "${TMP_ROOT}"
}
trap cleanup EXIT

echo "==> Creating fresh venv at ${VENV_DIR}"
uv venv "${VENV_DIR}" --python 3.12 >/dev/null

echo "==> Editable-installing ai-parrot + ai-parrot-client-groq only"
VIRTUAL_ENV="${VENV_DIR}" uv pip install \
    --python "${VENV_DIR}/bin/python" \
    -e "${REPO_ROOT}/packages/ai-parrot" \
    -e "${REPO_ROOT}/packages/ai-parrot-client-groq"

echo "==> Scaffolding a minimal navconfig bootstrap (unrelated to this"
echo "    feature — parrot.clients.base imports 'from navconfig import"
echo "    config' at module scope, and navconfig's Kardex resolves its"
echo "    'site_root' from the venv's own sys.prefix parent, not CWD)"
mkdir -p "$(dirname "${VENV_DIR}")/env/dev" "$(dirname "${VENV_DIR}")/etc"
touch "$(dirname "${VENV_DIR}")/env/dev/.env" "$(dirname "${VENV_DIR}")/etc/config.ini"

echo "==> Verifying LLMFactory discovers 'groq' via a real entry point"
"${VENV_DIR}/bin/python" -c "
from parrot.clients.factory import LLMFactory
providers = LLMFactory.list_providers()
assert 'groq' in providers, f'groq missing from {providers!r}'
assert providers['groq'] == 'ai-parrot-client-groq', providers['groq']
print('OK: groq ->', providers['groq'])
"

echo "==> PASS"
