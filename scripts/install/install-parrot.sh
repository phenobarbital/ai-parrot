#!/usr/bin/env bash
# AI-Parrot installer — automates the AI-Parrot getting-started guide (FEAT-586).
# Never destructive; every privileged/network command is announced before it runs.
#
# Usage:
#   install-parrot.sh [OPTIONS]
#
# Options:
#   --provider <k>[,<k>...]  One or more of: anthropic|openai|google|claude-code|codex-code
#                            (default: anthropic)
#   --extras <list>          Additional ai-parrot extras, comma-separated
#                            (e.g. jev,rust)
#   --venv <dir>             Virtualenv directory (default: .venv)
#   --python <bin>           Python interpreter to use (default: python3)
#   --with-wiki              Run `wikitoolkit build` after install
#   --install-cli            npm-install the LATEST MINOR (@latest) of the
#                            claude/codex CLI for a CLI-backed provider
#                            (claude-code/codex-code). Pins no version.
#   --system-deps            Install OS packages via sudo apt-get / brew
#                            (opt-in; never run automatically)
#   --dry-run                Print every command, with its purpose, without
#                            executing anything
#   -h, --help               Show this help and exit
#
# Contract: idempotent (reuses an existing venv, never deletes one); refuses
# a Python outside >=3.11,<3.14 before installing anything; every sudo or
# network-fetching command is echoed with its purpose before it runs.
set -euo pipefail

PROVIDER="anthropic"
EXTRAS=""
VENV=".venv"
PYTHON="python3"
WITH_WIKI=0
INSTALL_CLI=0
SYSTEM_DEPS=0
DRY_RUN=0

usage() {
  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
}

# run "<purpose>" cmd...
# Announces the purpose + the exact command before running it (AC8). Under
# --dry-run it only announces — it never executes anything, and callers must
# route every side-effecting command through it so --dry-run stays total.
run() {
  local why="$1"
  shift
  printf '\xe2\x86\x92 %s: %s\n' "$why" "$*"
  if [ "$DRY_RUN" -eq 0 ]; then
    "$@"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --provider)
      PROVIDER="$2"
      shift 2
      ;;
    --extras)
      EXTRAS="$2"
      shift 2
      ;;
    --venv)
      VENV="$2"
      shift 2
      ;;
    --python)
      PYTHON="$2"
      shift 2
      ;;
    --with-wiki)
      WITH_WIKI=1
      shift
      ;;
    --install-cli)
      INSTALL_CLI=1
      shift
      ;;
    --system-deps)
      SYSTEM_DEPS=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any
# other step (including --dry-run) so an unsupported interpreter is caught
# immediately, the same way it would fail during a real install.
if ! PYVER="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"; then
  echo "unsupported Python: could not execute '$PYTHON'" >&2
  exit 1
fi
case "$PYVER" in
  3.11|3.12|3.13) ;;
  *)
    echo "unsupported Python $PYVER; AI-Parrot needs >=3.11,<3.14" >&2
    exit 1
    ;;
esac

# OS detection (Ubuntu vs macOS) — informational, plus gates --system-deps.
OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Linux) OS_KIND="ubuntu" ;;
  Darwin) OS_KIND="macos" ;;
  *) OS_KIND="unknown" ;;
esac
echo "Detected OS: $OS_NAME ($OS_KIND)"

# --system-deps: OS packages via sudo apt-get / brew. Opt-in only; never runs
# on its own, and never invoked by CI (spec §7 risk).
if [ "$SYSTEM_DEPS" -eq 1 ]; then
  if [ "$OS_KIND" = "ubuntu" ]; then
    run "refresh the apt package index" sudo apt-get update
    run "install Python, venv and git via apt" sudo apt-get install -y \
      python3.12 python3.12-venv python3-pip git
  elif [ "$OS_KIND" = "macos" ]; then
    run "install Python and git via Homebrew" brew install python@3.12 git
  else
    echo "--system-deps is not supported on $OS_NAME; skipping" >&2
  fi
fi

# venv: create-or-reuse (never delete an existing one).
if [ -d "$VENV" ]; then
  echo "Reusing existing virtualenv at $VENV"
else
  run "create the virtualenv" "$PYTHON" -m venv "$VENV"
fi
VENV_PIP="$VENV/bin/pip"
VENV_BIN="$VENV/bin"

# Map provider keys to ai-parrot extras (spec §3 M3; see the getting-started
# guide §3 for the same mapping).
ALL_EXTRAS="$EXTRAS"
IFS=',' read -ra PROVIDER_LIST <<< "$PROVIDER"
CLI_PROVIDERS=()
for p in "${PROVIDER_LIST[@]}"; do
  case "$p" in
    anthropic) extra="anthropic" ;;
    openai) extra="openai" ;;
    google) extra="google" ;;
    claude-code)
      extra="claude-agent"
      CLI_PROVIDERS+=("claude-code")
      ;;
    codex-code)
      extra="codex-agent"
      CLI_PROVIDERS+=("codex-code")
      ;;
    *)
      echo "Unknown provider '$p'; expected one of: anthropic|openai|google|claude-code|codex-code" >&2
      exit 1
      ;;
  esac
  if [ -z "$ALL_EXTRAS" ]; then
    ALL_EXTRAS="$extra"
  else
    ALL_EXTRAS="$ALL_EXTRAS,$extra"
  fi
done

# Install ai-parrot + the resolved provider/extra set.
run "install ai-parrot with extras: $ALL_EXTRAS" "$VENV_PIP" install "ai-parrot[$ALL_EXTRAS]"

# --install-cli: npm-install the LATEST MINOR (@latest) of each requested
# CLI-backed provider's CLI binary. Pins no version — see spec §6/AC18.
if [ "$INSTALL_CLI" -eq 1 ]; then
  for cli in "${CLI_PROVIDERS[@]}"; do
    case "$cli" in
      claude-code)
        run "install the latest minor of the Claude Code CLI" npm install -g @anthropic-ai/claude-code@latest
        ;;
      codex-code)
        run "install the latest minor of the Codex CLI" npm install -g @openai/codex@latest
        ;;
    esac
  done
  if [ "${#CLI_PROVIDERS[@]}" -eq 0 ]; then
    echo "--install-cli passed but no CLI-backed provider (claude-code/codex-code) was requested; nothing to do" >&2
  fi
fi

# --with-wiki: build the local codebase knowledge graph after install.
if [ "$WITH_WIKI" -eq 1 ]; then
  run "build the wikitoolkit knowledge graph" "$VENV_BIN/wikitoolkit" build
fi

echo "Done."
