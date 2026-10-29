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
#   --global                 Install a managed runtime under $PARROT_HOME (default
#                            ~/.parrot): pinned uv, uv-managed Python 3.12, venv,
#                            parrot/wikitoolkit/bookstore on PATH. Needs no system
#                            Python; incompatible with --venv/--with-wiki/--system-deps
#   --version <X>            (--global) pin ai-parrot and ai-parrot-tools to <X>
#   --with <c>[,<c>...]      (--global) run `parrot self add <c>` per component
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
GLOBAL=0; PARROT_VERSION=""; WITH_COMPONENTS=""; PYTHON_SET=0; VENV_SET=0; UV_VERSION="0.11.28"; CREATED=()
PATH_BLOCK_RC=""
MIN_FREE_KB=2097152   # C14b gate: 2 GiB free under PARROT_HOME (managed CPython + venv + wheel cache)
RAW_BASE="https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install"   # C14a non-piped alternative

usage() {
  sed -n '2,35p' "$0" | sed 's/^# \{0,1\}//'
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
      VENV_SET=1
      shift 2
      ;;
    --python)
      PYTHON="$2"
      PYTHON_SET=1
      shift 2
      ;;
    --global)
      GLOBAL=1
      shift
      ;;
    --version)
      PARROT_VERSION="$2"
      shift 2
      ;;
    --with)
      WITH_COMPONENTS="$2"
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

resolve_extras() {
  # Map provider keys to ai-parrot extras (spec §3 M3; see the getting-started
  # guide §3 for the same mapping). Sets ALL_EXTRAS and CLI_PROVIDERS.
  local p extra
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
}
print_plan() {  # C14a — first output of global mode; no side effects; printed under --dry-run too
  cat <<PLAN
This installer will download uv $UV_VERSION from $1 and verify it against $1.sha256,
create $PARROT_HOME/{bin,venv,python} (a uv-managed Python $PYTHON and a venv with $2),
and add $PARROT_HOME/bin to PATH via a marker block in your shell profile.
If missing, it writes a commented-out credentials file $PARROT_HOME/env/.env (mode 0600)
and an empty navconfig $PARROT_HOME/etc/config.ini.
A uv already on your PATH is never used or modified. Existing $PARROT_HOME data is never touched.
Prefer not to pipe a download into bash? Fetch $RAW_BASE/install-parrot.sh and
$RAW_BASE/SHA256SUMS, run 'sha256sum -c --ignore-missing SHA256SUMS', read the script, then run it.
PLAN
}
gate_fail() { echo "preflight: $1 — fix: $2" >&2; exit 1; }   # C14b — nothing has been written yet
uv_target() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) echo x86_64-unknown-linux-gnu ;;  Linux-aarch64|Linux-arm64) echo aarch64-unknown-linux-gnu ;;
    Darwin-x86_64) echo x86_64-apple-darwin ;;      Darwin-arm64) echo aarch64-apple-darwin ;;
    *) echo "unsupported platform $(uname -s)-$(uname -m) for --global" >&2; return 1 ;;
  esac
}
reachable() {  # reachable <url> — HEAD request; used only by the network gate
  if command -v curl >/dev/null 2>&1; then curl -fsI "$1" >/dev/null 2>&1
  else wget -q --spider "$1" >/dev/null 2>&1; fi
}
preflight() {  # C14b — read-only checks, in order; never calls run(); never creates PARROT_HOME
  local anc free h
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64|Linux-aarch64|Linux-arm64|Darwin-arm64) ;;
    *) gate_fail "unsupported platform $(uname -s)-$(uname -m)" "use a project install (no --global) on this machine; supported: linux x86_64/aarch64, macOS arm64" ;;
  esac
  uv_target >/dev/null 2>&1 || gate_fail "unsupported platform $(uname -s)-$(uname -m)" "use a project install (no --global) on this machine; supported: linux x86_64/aarch64, macOS arm64"
  # Officially supported: Linux x86_64 (owner decision 2026-10-29). Elsewhere some dependencies publish no wheel,
  # so uv builds them from source: warn, never block — a machine with a C toolchain may still succeed.
  [ "$(uname -s)-$(uname -m)" = Linux-x86_64 ] || echo "warning: $(uname -s)-$(uname -m) is not officially supported \
(official: Linux x86_64); some dependencies have no wheel here, so the install compiles them, needs a C toolchain \
and may fail" >&2
  command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || gate_fail "no download tool" "install curl or wget"
  command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || gate_fail "no checksum tool" "install coreutils (sha256sum) or perl (shasum)"
  command -v mktemp >/dev/null 2>&1 || gate_fail "no mktemp" "install coreutils (mktemp)"
  command -v git >/dev/null 2>&1 || gate_fail "git not found" "install git (the SDD flow and parrot self doctor need it)"
  anc="$PARROT_HOME"; while [ ! -e "$anc" ]; do anc="$(dirname "$anc")"; done   # nearest existing ancestor
  [ -w "$anc" ] || gate_fail "$anc is not writable" "set PARROT_HOME to a writable directory"
  free="$(df -Pk "$anc" | awk 'NR==2{print $4}')"
  [ "${free:-0}" -ge "$MIN_FREE_KB" ] || gate_fail "only ${free}KB free under $anc (need $MIN_FREE_KB)" "free disk space or set PARROT_HOME elsewhere"
  if [ "$DRY_RUN" -eq 1 ]; then echo "preflight: network checks skipped (--dry-run)"; return 0; fi
  for h in https://github.com https://pypi.org/simple/; do
    reachable "$h" || gate_fail "$h unreachable" "check your network/proxy"
  done
  echo "preflight: ok"
}
fetch() {  # fetch <url> <dest> — the network check; failure aborts before any PATH change
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1"
  else echo "--global needs curl or wget" >&2; return 1; fi
}
verify_sha256() {  # verify_sha256 <file> <file.sha256>
  local want got; want="$(awk '{print $1}' "$2")"
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$1" | awk '{print $1}')"
  else got="$(shasum -a 256 "$1" | awk '{print $1}')"; fi
  [ "$want" = "$got" ] || { echo "checksum mismatch for $1" >&2; return 1; }
}
mkdir_tracked() { if [ ! -e "$1" ]; then mkdir -p "$1"; CREATED+=("$1"); fi; }
install_shim() {  # write-then-rename: never a half-written shim
  [ -e "$2" ] || [ -L "$2" ] || CREATED+=("$2"); ln -sfn "$1" "$2.tmp.$$" && mv -f "$2.tmp.$$" "$2"
}
install_uv_bins() {  # install_uv_bins <extract-dir> <target> <dest-bin-dir> — uv (+uvx), write-then-rename
  local src="$1/uv-$2" b
  [ -f "$src/uv" ] || src="$1"   # tolerate a flat tarball
  [ -f "$src/uv" ] || { echo "uv binary not found in the downloaded archive" >&2; return 1; }
  for b in uv uvx; do
    [ -f "$src/$b" ] || continue
    [ -e "$3/$b" ] || CREATED+=("$3/$b")
    cp "$src/$b" "$3/$b.tmp.$$" && chmod 755 "$3/$b.tmp.$$" && mv -f "$3/$b.tmp.$$" "$3/$b"
  done
}
rollback() {
  local rc=$? i tmp; [ "$rc" -eq 0 ] && return 0
  echo "global install failed (exit $rc); removing only what this run created (if 'parrot self doctor --runtime-only' failed, its suggested fixes are printed above)" >&2
  if [ -n "$PATH_BLOCK_RC" ] && [ -f "$PATH_BLOCK_RC" ]; then   # strip the PATH block only if THIS run added it
    tmp="$PATH_BLOCK_RC.parrot-rollback.$$"
    sed '/^# >>> parrot >>>$/,/^# <<< parrot <<<$/d' "$PATH_BLOCK_RC" > "$tmp" && cat "$tmp" > "$PATH_BLOCK_RC"
    rm -f -- "$tmp"
  fi
  for ((i=${#CREATED[@]}-1; i>=0; i--)); do rm -rf -- "${CREATED[$i]}"; done
  return "$rc"
}
add_path_block() {
  local rc_file="$HOME/.profile"
  case "${SHELL:-}" in */zsh) rc_file="$HOME/.zshrc" ;; */bash) rc_file="$HOME/.bashrc" ;; esac
  if [ -f "$rc_file" ] && grep -qF '# >>> parrot >>>' "$rc_file"; then return 0; fi
  [ -e "$rc_file" ] || CREATED+=("$rc_file")
  PATH_BLOCK_RC="$rc_file"
  printf '\n# >>> parrot >>>\nexport PATH="%s/bin:$PATH"\n# <<< parrot <<<\n' "$PARROT_HOME" >> "$rc_file"
  echo "Added $PARROT_HOME/bin to PATH in $rc_file — open a new shell to pick it up"
}
global_install() {
  local target asset url spec tools dl uv s c failed=0 _comps
  if [ "$VENV_SET" -eq 1 ]; then echo "--global cannot be combined with --venv: the managed venv lives at \$PARROT_HOME/venv" >&2; exit 1; fi
  if [ "$WITH_WIKI" -eq 1 ]; then echo "--global cannot be combined with --with-wiki: there is no project to build a wiki for" >&2; exit 1; fi
  if [ "$SYSTEM_DEPS" -eq 1 ]; then echo "--global cannot be combined with --system-deps: uv supplies the Python runtime" >&2; exit 1; fi
  PARROT_HOME="${PARROT_HOME:-$HOME/.parrot}"; [ "$PYTHON_SET" -eq 1 ] || PYTHON="3.12"; resolve_extras
  target="$(uv_target 2>/dev/null || true)"; asset="uv-$target.tar.gz"; uv="$PARROT_HOME/bin/uv"
  url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$asset"
  spec="ai-parrot[$ALL_EXTRAS]"; [ -z "$PARROT_VERSION" ] || spec="$spec==$PARROT_VERSION"
  # rev 0.5 C20 — ai-parrot-tools at the same version pin (wikitoolkit mcp's wiki tools live in parrot_tools.wiki)
  tools="ai-parrot-tools"; [ -z "$PARROT_VERSION" ] || tools="$tools==$PARROT_VERSION"
  dl="${TMPDIR:-/tmp}/parrot-uv.XXXXXX"   # real private dir (mktemp -d, 0700) is created below, never a predictable path
  print_plan "$url" "$spec $tools"    # C14a — before anything else
  preflight                    # C14b — exits 1 on any failed gate; nothing written yet
  if [ "$DRY_RUN" -eq 0 ]; then
    trap rollback EXIT; mkdir_tracked "$PARROT_HOME"; mkdir_tracked "$PARROT_HOME/bin"
    dl="$(mktemp -d "$dl")"; CREATED+=("$dl")
  fi
  printf '\xe2\x86\x92 create a scratch download dir: mktemp -d %s\n' "$dl"
  run "download pinned uv $UV_VERSION ($target)" fetch "$url" "$dl/$asset"
  run "download the uv checksum" fetch "$url.sha256" "$dl/$asset.sha256"
  run "verify the uv checksum" verify_sha256 "$dl/$asset" "$dl/$asset.sha256"
  run "extract uv" tar -xzf "$dl/$asset" -C "$dl"
  run "install uv into $PARROT_HOME/bin (your own uv is never touched)" install_uv_bins "$dl" "$target" "$PARROT_HOME/bin"
  export UV_PYTHON_INSTALL_DIR="$PARROT_HOME/python"
  [ "$DRY_RUN" -eq 1 ] || [ -e "$UV_PYTHON_INSTALL_DIR" ] || CREATED+=("$UV_PYTHON_INSTALL_DIR")
  if [ -d "$PARROT_HOME/venv" ]; then echo "Reusing managed venv at $PARROT_HOME/venv"
  else
    [ "$DRY_RUN" -eq 1 ] || CREATED+=("$PARROT_HOME/venv")
    run "create the managed venv (Python $PYTHON)" "$uv" venv "$PARROT_HOME/venv" --python "$PYTHON" --python-preference only-managed
  fi
  run "install $spec $tools into the managed venv" "$uv" pip install --python "$PARROT_HOME/venv/bin/python" "$spec" "$tools"
  for s in parrot wikitoolkit bookstore; do run "expose $s" install_shim "$PARROT_HOME/venv/bin/$s" "$PARROT_HOME/bin/$s"; done
  run "add $PARROT_HOME/bin to PATH" add_path_block
  # the profile edit only helps NEW shells: the doctor below runs in this one and checks PATH
  [ "$DRY_RUN" -eq 1 ] || export PATH="$PARROT_HOME/bin:$PATH"
  # C14b — runtime scope only, pinned to the venv just built; a non-zero exit under set -e fires the rollback trap
  run "verify the managed runtime (parrot self doctor --runtime-only)" \
    env PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self doctor --runtime-only
  run "remove the scratch download dir" rm -rf "$dl"
  # The base runtime is verified: a failing component must never roll it back (warn, then exit non-zero).
  trap - EXIT
  # navconfig's env/.env (credentials) and an empty etc/config.ini under PARROT_HOME (user data: never overwritten,
  # kept by uninstall).
  if ! run "create the credentials file and etc/config.ini under $PARROT_HOME (kept if present)" \
      env PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self env --init; then
    echo "warning: no credentials file was created under $PARROT_HOME/env (needs an ai-parrot release with" \
      "'parrot self env --init'; after 'parrot self update', run 'parrot self env --init')" >&2
  fi
  if [ -n "$WITH_COMPONENTS" ]; then  # guard: empty "${arr[@]}" + set -u breaks macOS bash 3.2
    IFS=',' read -ra _comps <<< "$WITH_COMPONENTS"
    for c in "${_comps[@]}"; do
      if ! run "add component $c" "$PARROT_HOME/bin/parrot" self add "$c"; then
        echo "warning: 'parrot self add $c' failed; the base runtime stays installed" >&2
        failed=1
      fi
    done
  fi
  return "$failed"
}
if [ "$GLOBAL" -eq 1 ]; then global_install; echo "Done."; exit 0; fi

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

resolve_extras

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
