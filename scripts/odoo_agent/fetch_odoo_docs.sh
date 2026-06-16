#!/usr/bin/env bash
# =============================================================================
# fetch_odoo_docs.sh — Generate Odoo documentation PDFs from the official repo
# =============================================================================
#
# PURPOSE
#   Checks out the official Odoo documentation repository for each supported
#   version (16.0, 18.0, 19.0), builds the PDF via `make latexpdf`, and copies
#   the resulting PDF to the agent's documentation directory.
#
# PREREQUISITES
#   - git          (to clone / checkout the Odoo docs repo)
#   - make         (to drive the Sphinx build)
#   - A TeX distribution (TeX Live, MacTeX, etc.) for pdflatex / latexmk.
#     On Debian/Ubuntu: sudo apt-get install texlive-full
#     On macOS:         brew install --cask mactex
#   - Python ≥ 3.8 with Sphinx and the Odoo Sphinx extensions; typically
#     installed via `pip install -r requirements.txt` inside the docs repo.
#
# USAGE
#   ./scripts/odoo_agent/fetch_odoo_docs.sh [OPTIONS]
#
# OPTIONS
#   --force      Rebuild even if the PDF already exists for a version.
#   --versions   Comma-separated list of versions to build (default: 16.0,18.0,19.0).
#   --out-dir    Output directory (default: agents/odoo_agent/documentation).
#   --cache-dir  Cache directory for the cloned repo (default: scripts/odoo_agent/.cache).
#   --help       Show this help text and exit.
#
# EXAMPLE
#   # Build all versions (skip those already present)
#   ./scripts/odoo_agent/fetch_odoo_docs.sh
#
#   # Force rebuild of version 18.0 only
#   ./scripts/odoo_agent/fetch_odoo_docs.sh --versions 18.0 --force
#
# NOTE ON LARGE PDFs
#   The generated PDFs can be several hundred megabytes each.  Committing them
#   directly is not recommended; consider Git LFS or keeping them out of source
#   control and regenerating on demand.  The `agents/odoo_agent/documentation/`
#   directory ships with only a `.gitkeep` placeholder in source control.
#
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
ODOO_DOCS_REPO="https://github.com/odoo/documentation.git"
DEFAULT_VERSIONS="16.0 18.0 19.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEFAULT_OUT_DIR="${REPO_ROOT}/agents/odoo_agent/documentation"
DEFAULT_CACHE_DIR="${SCRIPT_DIR}/.cache"

FORCE=false
VERSIONS="${DEFAULT_VERSIONS}"
OUT_DIR="${DEFAULT_OUT_DIR}"
CACHE_DIR="${DEFAULT_CACHE_DIR}"

# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -40
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)      usage ;;
        --force)        FORCE=true; shift ;;
        --versions)     VERSIONS="${2//,/ }"; shift 2 ;;
        --out-dir)      OUT_DIR="$2"; shift 2 ;;
        --cache-dir)    CACHE_DIR="$2"; shift 2 ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

# --------------------------------------------------------------------------- #
# Prerequisite checks
# --------------------------------------------------------------------------- #
check_prerequisite() {
    local cmd="$1"
    local hint="$2"
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: '${cmd}' is not available." >&2
        echo "       ${hint}" >&2
        exit 1
    fi
}

echo "==> Checking prerequisites..."
check_prerequisite git  "Install git: https://git-scm.com"
check_prerequisite make "Install make (build-essential on Debian/Ubuntu)"
check_prerequisite pdflatex \
    "Install a TeX distribution (e.g. texlive-full on Debian/Ubuntu, MacTeX on macOS)"

echo "    git:      $(git --version)"
echo "    make:     $(make --version | head -1)"
echo "    pdflatex: $(pdflatex --version | head -1)"

# --------------------------------------------------------------------------- #
# Clone / update the documentation repository
# --------------------------------------------------------------------------- #
DOCS_REPO_DIR="${CACHE_DIR}/documentation"

echo ""
echo "==> Setting up Odoo documentation repository at ${DOCS_REPO_DIR}"
mkdir -p "${CACHE_DIR}"

if [[ -d "${DOCS_REPO_DIR}/.git" ]]; then
    echo "    Cache hit — reusing existing clone."
    git -C "${DOCS_REPO_DIR}" fetch --quiet origin
else
    echo "    Cloning ${ODOO_DOCS_REPO} ..."
    git clone --quiet "${ODOO_DOCS_REPO}" "${DOCS_REPO_DIR}"
fi

# --------------------------------------------------------------------------- #
# Build loop
# --------------------------------------------------------------------------- #
mkdir -p "${OUT_DIR}"

for VERSION in ${VERSIONS}; do
    PDF_OUT="${OUT_DIR}/${VERSION}"
    mkdir -p "${PDF_OUT}"

    EXISTING_PDF=$(find "${PDF_OUT}" -maxdepth 1 -name "*.pdf" 2>/dev/null | head -1)

    if [[ -n "${EXISTING_PDF}" && "${FORCE}" == "false" ]]; then
        echo ""
        echo "==> [${VERSION}] PDF already exists at ${EXISTING_PDF} — skipping."
        echo "    Run with --force to rebuild."
        continue
    fi

    echo ""
    echo "==> [${VERSION}] Building documentation PDF..."

    # ── Checkout the version branch ────────────────────────────────────────
    echo "    Checking out branch ${VERSION}..."
    git -C "${DOCS_REPO_DIR}" checkout --quiet "${VERSION}"
    git -C "${DOCS_REPO_DIR}" reset --hard --quiet "origin/${VERSION}" || true

    # ── Install Python dependencies if requirements.txt exists ─────────────
    if [[ -f "${DOCS_REPO_DIR}/requirements.txt" ]]; then
        echo "    Installing Python dependencies..."
        if command -v pip3 &>/dev/null; then
            pip3 install --quiet -r "${DOCS_REPO_DIR}/requirements.txt" || {
                echo "WARNING: pip install of requirements.txt failed — build may fail." >&2
            }
        else
            echo "WARNING: pip3 not found — skipping requirements.txt install." >&2
        fi
    fi

    # ── Run make latexpdf ──────────────────────────────────────────────────
    echo "    Running make latexpdf in ${DOCS_REPO_DIR}..."
    (
        cd "${DOCS_REPO_DIR}"
        # Some versions need SPHINXOPTS; try plain first, then with -P
        if ! make latexpdf 2>&1; then
            echo "    make latexpdf failed — retrying with SPHINXOPTS='-P'" >&2
            make latexpdf SPHINXOPTS="-P" 2>&1
        fi
    ) || {
        echo "ERROR: make latexpdf failed for version ${VERSION}." >&2
        echo "       Check the LaTeX toolchain and the Odoo docs build dependencies." >&2
        exit 1
    }

    # ── Locate generated PDF ───────────────────────────────────────────────
    # The output path varies by Sphinx version: _build/latex/, build/latex/, etc.
    GENERATED_PDF=$(find "${DOCS_REPO_DIR}" -name "*.pdf" \
        \( -path "*/latex/*" -o -path "*/_build/*" \) \
        2>/dev/null | sort | tail -1)

    if [[ -z "${GENERATED_PDF}" ]]; then
        # Fallback: search entire repo for any new PDF
        GENERATED_PDF=$(find "${DOCS_REPO_DIR}" -name "*.pdf" 2>/dev/null | sort | tail -1)
    fi

    if [[ -z "${GENERATED_PDF}" ]]; then
        echo "ERROR: No PDF found after make latexpdf for version ${VERSION}." >&2
        echo "       Expected a *.pdf under ${DOCS_REPO_DIR}/_build/ or similar." >&2
        exit 1
    fi

    # ── Copy to output directory ───────────────────────────────────────────
    DEST="${PDF_OUT}/odoo_${VERSION//./_}_docs.pdf"
    echo "    Copying ${GENERATED_PDF} → ${DEST}"
    cp "${GENERATED_PDF}" "${DEST}"
    echo "    [${VERSION}] Done. PDF at: ${DEST}"
done

echo ""
echo "==> All requested versions processed."
echo "    Output directory: ${OUT_DIR}"
