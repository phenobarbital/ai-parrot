# TASK-4074: Bootstrap: install-parrot.sh --global mode (pinned uv, managed venv)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4072
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (POSIX leg). The FEAT-586 installer `scripts/install/install-parrot.sh` builds a
*project* venv with the system Python and pip. FEAT-633 adds a `--global` mode that installs a
**managed runtime** under `$PARROT_HOME` (default `~/.parrot`): a pinned, checksum-verified `uv`,
a uv-managed CPython 3.12, `~/.parrot/venv` with ai-parrot installed, and the three
launcher-fronted console scripts (`parrot`, `wikitoolkit`, `bookstore` — names fixed by TASK-4072's
`[project.scripts]` repoint) exposed from `~/.parrot/bin` on PATH.

Codex design review S10 (spec §9, CONFIRMED): the `--global` branch must be taken **before** the
existing system-Python guard (`install-parrot.sh:102-115`) — a clean machine has no Python, and the
whole point of global mode is that uv provides one. Project mode must stay byte-for-byte unchanged.

`~/.parrot` is a live data directory (wikis.json, library/, skills/, brains/, parrot.db, services/,
cli/ — spec §7): the bootstrap may only add `bin/`, `venv/`, `python/`, and rollback must remove
only what *this run* created.

---

## Scope

- Add flags `--global`, `--version <X>`, `--with <comma list>` to the arg loop; keep every
  existing flag working unchanged; `--dry-run` stays total (no network, no file writes).
- Take the `--global` branch BEFORE the system-Python guard; project mode is untouched.
- In global mode: honour `PARROT_HOME` (default `$HOME/.parrot`); download pinned uv `0.11.28`
  from `https://github.com/astral-sh/uv/releases/download/0.11.28/uv-<target>.tar.gz` plus its
  `.sha256`, verify with `sha256sum` or `shasum -a 256`, and extract the `uv` binary to
  `$PARROT_HOME/bin/uv` (never touch a uv already on the user's PATH).
- Run `uv venv "$PARROT_HOME/venv" --python <py>` with `UV_PYTHON_INSTALL_DIR="$PARROT_HOME/python"`
  (managed CPython lives under the home), default `<py>` = `3.12`.
- Install `ai-parrot[<extras>]` (`==<version>` when `--version` is given) with
  `uv pip install --python "$PARROT_HOME/venv/bin/python"`; extras come from the existing
  `--provider`/`--extras` mapping.
- Expose `$PARROT_HOME/bin/{parrot,wikitoolkit,bookstore}` as symlinks to the venv scripts,
  created write-then-rename (`ln -s` to a temp name + `mv -f`).
- Add `$PARROT_HOME/bin` to PATH via a marker block (`# >>> parrot >>>` … `# <<< parrot <<<`) in
  `~/.zshrc` / `~/.bashrc` / `~/.profile` chosen from `$SHELL`; idempotent.
- After install, run `$PARROT_HOME/bin/parrot self add <c>` for each `--with` component.
- Install an `EXIT` trap that, on failure, removes ONLY paths this run created.
- Extend `test_install_posix.py` with dry-run and arg-parsing tests for the new mode.

**NOT in scope**:
- `install-parrot.ps1` (TASK-4075); CI wiring and `scripts/install/SHA256SUMS` (TASK-4076);
  user docs (TASK-4095).
- `parrot self add|update|…` itself (TASK-4079/TASK-4080) — this script only *calls* it.
- Any change to project-mode behavior, the Python guard logic, or `--system-deps`.
- A `--purge` / uninstall path (spec §7: out of scope for v1; `parrot self uninstall` owns it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.sh` | MODIFY | `--global` mode, new flags, pinned-uv bootstrap, shims, PATH block, rollback |
| `packages/ai-parrot/tests/docs/test_install_posix.py` | MODIFY | dry-run + arg-parsing tests for `--global` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test file only (stdlib); same imports the existing test already uses
import os                    # verified: packages/ai-parrot/tests/docs/test_install_posix.py:5
import stat                  # verified: packages/ai-parrot/tests/docs/test_install_posix.py:6
import subprocess            # verified: packages/ai-parrot/tests/docs/test_install_posix.py:7
import tempfile              # verified: packages/ai-parrot/tests/docs/test_install_posix.py:8
from pathlib import Path     # verified: packages/ai-parrot/tests/docs/test_install_posix.py:9
```

### Existing Signatures to Use
```bash
# scripts/install/install-parrot.sh
set -euo pipefail                         # line 28
PYTHON="python3"                          # line 33  (interpreter BINARY in project mode)
DRY_RUN=0                                 # line 37
usage() { sed -n '2,29p' "$0" | ... }     # lines 39-41 — prints the header comment block 2..29
run() { local why="$1"; shift; printf '\xe2\x86\x92 %s: %s\n' "$why" "$*"; [ "$DRY_RUN" -eq 0 ] && "$@"; }  # lines 47-54
while [ $# -gt 0 ]; do case "$1" in ... esac; done   # arg loop lines 56-100
    --python) PYTHON="$2"; shift 2 ;;     # lines 70-73
    --with-wiki) WITH_WIKI=1; shift ;;    # lines 74-77
# Python guard (AC10)                     # lines 102-115 — executes "$PYTHON"; exits 1 on failure
# Map provider keys to ai-parrot extras   # lines 149-177 — builds ALL_EXTRAS + CLI_PROVIDERS
run "install ai-parrot ..." "$VENV_PIP" install "ai-parrot[$ALL_EXTRAS]"   # line 180
```
```python
# packages/ai-parrot/tests/docs/test_install_posix.py
REPO_ROOT = Path(__file__).resolve().parents[4]      # line 11
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.sh"   # line 12
def test_posix_script_syntax() -> None:              # line 15
def test_posix_script_dry_run() -> None:             # line 21 — asserts "→" in stdout
def test_script_rejects_unsupported_python() -> None:  # line 36 — stub python printing 3.10
```
```python
# packages/ai-parrot/pyproject.toml — console scripts the shims point at (repointed to
# parrot.launcher wrappers by TASK-4072; the NAMES are what this task relies on)
[project.scripts]          # line 199
parrot = ...               # line 200
wikitoolkit = ...          # line 204
bookstore = ...            # line 206
```
- Pinned uv: `0.11.28` (brief cross-cutting decision; matches the locally installed `uv 0.11.28`).
- uv release asset naming: `uv-<target>.tar.gz` + `uv-<target>.tar.gz.sha256`, targets
  `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`, `x86_64-apple-darwin`,
  `aarch64-apple-darwin`. The tarball contains a top-level `uv-<target>/` directory holding
  `uv` and `uvx` (verify on first real download; see FILL IN).

### Does NOT Exist
- ~~any uv-download code in `install-parrot.sh`~~ — the script uses `python -m venv` + pip only (spec §6).
- ~~`--global`, `--version`, `--with`, `PARROT_HOME` handling in the script~~ — all new here.
- ~~a root-level `install.sh`~~ — never create one (spec Non-Goals).
- ~~`parrot self` command~~ — delivered by TASK-4080; this script calls it but must not depend on
  it in `--dry-run` (it is only announced there).
- ~~`$PARROT_HOME/bin` existing before this feature~~ — `~/.parrot` exists on dev machines with
  data, but never with `bin/` or `venv/` from FEAT-586.
- ~~`PARROT_VENV` / `PARROT_PROJECT` being set by this script~~ — launcher env vars (TASK-4071);
  the bootstrap never exports them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/install/install-parrot.sh",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_install_posix.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#test_posix_script_syntax",
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#test_posix_script_dry_run",
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#test_script_rejects_unsupported_python"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```bash
# Every side-effecting command goes through run() (install-parrot.sh:47-54) so --dry-run stays
# total. Compound steps (download → verify → extract) are wrapped in small functions that are
# THEMSELVES invoked via run, e.g.:
run "download pinned uv $UV_VERSION ($UV_TARGET)" fetch "$UV_URL" "$DL_DIR/$UV_ASSET"
```

### Key Constraints
- `set -euo pipefail` is active: every new variable must have a default before first use
  (`GLOBAL=0`, `PARROT_VERSION=""`, `WITH_COMPONENTS=""`, `PYTHON_SET=0`).
- In global mode `--python` is a **uv Python request** (`3.12`, `3.13`, or a path) forwarded
  verbatim to `uv venv --python`, NOT an interpreter that the script executes — that is what lets
  `--global --python /nonexistent --dry-run` succeed (the guard never runs). Default when not
  passed: `3.12` (spec `MANAGED_PYTHON`).
- Use `--python-preference only-managed` on `uv venv` — *why*: a system 3.12 must not be picked
  up; the runtime must be the uv-managed CPython under `$PARROT_HOME/python`.
- Reject `--venv`, `--with-wiki` and `--system-deps` together with `--global` (exit 1 with a
  message) — *why*: the managed venv path is fixed, there is no project to build a wiki for, and
  uv supplies Python so OS packages are not needed.
- Network/checksum failure must abort BEFORE any shim or PATH change (download+verify are the first
  side effects after directory creation).
- Rollback: record each path in `CREATED=()` only when this run created it (test `-e` first);
  the `EXIT` trap removes them in reverse order only when the exit status is non-zero. Never
  `rm -rf "$PARROT_HOME"` unless `$PARROT_HOME` itself was created by this run.
- Re-runs are upgrades: an existing `$PARROT_HOME/venv` is reused (not recreated), existing uv
  is replaced via write-then-rename, the PATH block is skipped when the marker is present.
- macOS ships bash 3.2: no `declare -A`, no `mapfile`, and never expand a possibly-empty array
  as `"${arr[@]}"` under `set -u` without a guard (the rollback loop uses `${#CREATED[@]}`, which
  is safe).
- All diagnostics/errors to stderr (`>&2`); announcements via `run`/`echo` to stdout as today.

### References in Codebase
- `scripts/install/install-parrot.sh:47-54` — `run()` contract.
- `scripts/install/install-parrot.sh:149-177` — provider→extras mapping to reuse.
- `packages/ai-parrot/tests/docs/test_install_posix.py:21-33` — dry-run test pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Add the new globals after `DRY_RUN=0` — *why*: `set -u` needs defaults before the arg loop.
2. Add the new case arms and set `PYTHON_SET=1` in the `--python)` arm — *why*: global mode must
   know whether `--python` was explicitly given to choose the `3.12` default.
3. Document the new flags in the header comment and widen `usage()`'s `sed -n` range to the new
   last header line — *why*: `--help` prints lines 2..N of the file.
4. Turn the provider→extras block into a `resolve_extras` function defined before the guard, and
   call it at its old location — *why*: both modes need `ALL_EXTRAS` and global mode exits before
   the original block runs.
5. Insert the global-mode functions + dispatch immediately before the Python guard comment —
   *why*: codex S10, a clean machine never reaches the guard in global mode.
6. Extend the POSIX test file — *why*: spec §4 `test_install_sh_global_dry_run`.

### `scripts/install/install-parrot.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c 'DRY_RUN=0' scripts/install/install-parrot.sh)
# AFTER — `DRY_RUN=0` (verified: scripts/install/install-parrot.sh:37)
GLOBAL=0; PARROT_VERSION=""; WITH_COMPONENTS=""; PYTHON_SET=0; UV_VERSION="0.11.28"; CREATED=()
# (also, per Steps 2-4: `--python)` arm sets PYTHON_SET=1 [anchor `      PYTHON="$2"`, :71, 1 occ];
#  new arms --global / --version / --with inserted ABOVE `    --with-wiki)` [:74, 1 occ];
#  header help lines above `#   -h, --help ...` [:23, 1 occ]; `sed -n '2,29p'` [:40, 1 occ] widened;
#  mapping block [:149-177, anchor `# Map provider keys to ai-parrot extras (spec §3 M3; see the getting-started`,
#  1 occ] moved verbatim into resolve_extras() and replaced by the call `resolve_extras`.)

# occurrences: 1 (verified: grep -c '# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any' scripts/install/install-parrot.sh)
# REPLACE — `# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any`
# (verified: scripts/install/install-parrot.sh:102) with this block followed by the original line.
resolve_extras() { :; }  # FILL IN: old lines 149-177 verbatim — bounded by test_posix_script_dry_run
uv_target() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) echo x86_64-unknown-linux-gnu ;;  Linux-aarch64|Linux-arm64) echo aarch64-unknown-linux-gnu ;;
    Darwin-x86_64) echo x86_64-apple-darwin ;;      Darwin-arm64) echo aarch64-apple-darwin ;;
    *) echo "unsupported platform $(uname -s)-$(uname -m) for --global" >&2; return 1 ;;
  esac
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
rollback() {
  local rc=$? i; [ "$rc" -eq 0 ] && return 0
  echo "global install failed (exit $rc); removing only what this run created" >&2
  for ((i=${#CREATED[@]}-1; i>=0; i--)); do rm -rf -- "${CREATED[$i]}"; done
  return "$rc"  # FILL IN: strip the PATH block only if THIS run added it — bounded by AC rollback
}
add_path_block() {
  local rc_file="$HOME/.profile"
  case "${SHELL:-}" in */zsh) rc_file="$HOME/.zshrc" ;; */bash) rc_file="$HOME/.bashrc" ;; esac
  if [ -f "$rc_file" ] && grep -qF '# >>> parrot >>>' "$rc_file"; then return 0; fi
  printf '\n# >>> parrot >>>\nexport PATH="%s/bin:$PATH"\n# <<< parrot <<<\n' "$PARROT_HOME" >> "$rc_file"
  echo "Added $PARROT_HOME/bin to PATH in $rc_file — open a new shell to pick it up"
}
global_install() {
  # FILL IN: refuse --venv/--with-wiki/--system-deps with --global (exit 1) — bounded by Key Constraints
  PARROT_HOME="${PARROT_HOME:-$HOME/.parrot}"; [ "$PYTHON_SET" -eq 1 ] || PYTHON="3.12"; resolve_extras
  local target asset url spec dl uv s c
  target="$(uv_target)"; asset="uv-$target.tar.gz"; uv="$PARROT_HOME/bin/uv"
  url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$asset"
  spec="ai-parrot[$ALL_EXTRAS]"; [ -z "$PARROT_VERSION" ] || spec="$spec==$PARROT_VERSION"
  dl="${TMPDIR:-/tmp}/parrot-uv.$$"
  if [ "$DRY_RUN" -eq 0 ]; then trap rollback EXIT; mkdir_tracked "$PARROT_HOME"; mkdir_tracked "$PARROT_HOME/bin"; fi
  run "create a scratch download dir" mkdir -p "$dl"
  run "download pinned uv $UV_VERSION ($target)" fetch "$url" "$dl/$asset"
  run "download the uv checksum" fetch "$url.sha256" "$dl/$asset.sha256"
  run "verify the uv checksum" verify_sha256 "$dl/$asset" "$dl/$asset.sha256"
  run "extract uv" tar -xzf "$dl/$asset" -C "$dl"
  # FILL IN: confirm layout uv-<target>/uv; install uv (+uvx) to $PARROT_HOME/bin write-then-rename,
  #          tracking new files in CREATED — bounded by "never touch the user's own uv"
  export UV_PYTHON_INSTALL_DIR="$PARROT_HOME/python"
  [ "$DRY_RUN" -eq 1 ] || [ -e "$UV_PYTHON_INSTALL_DIR" ] || CREATED+=("$UV_PYTHON_INSTALL_DIR")
  if [ -d "$PARROT_HOME/venv" ]; then echo "Reusing managed venv at $PARROT_HOME/venv"
  else
    [ "$DRY_RUN" -eq 1 ] || CREATED+=("$PARROT_HOME/venv")
    run "create the managed venv (Python $PYTHON)" "$uv" venv "$PARROT_HOME/venv" --python "$PYTHON" --python-preference only-managed
  fi
  run "install $spec into the managed venv" "$uv" pip install --python "$PARROT_HOME/venv/bin/python" "$spec"
  for s in parrot wikitoolkit bookstore; do run "expose $s" install_shim "$PARROT_HOME/venv/bin/$s" "$PARROT_HOME/bin/$s"; done
  run "add $PARROT_HOME/bin to PATH" add_path_block
  if [ -n "$WITH_COMPONENTS" ]; then  # guard: empty "${arr[@]}" + set -u breaks macOS bash 3.2
    IFS=',' read -ra _comps <<< "$WITH_COMPONENTS"
    for c in "${_comps[@]}"; do run "add component $c" "$PARROT_HOME/bin/parrot" self add "$c"; done
  fi
  run "remove the scratch download dir" rm -rf "$dl"
}
if [ "$GLOBAL" -eq 1 ]; then global_install; echo "Done."; exit 0; fi

# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any
```
**Why this shape**: the dispatch sits above the guard (codex S10) and calls only functions that
route side effects through `run`, so `--dry-run` writes nothing and needs no network. Do NOT
change the project-mode path, the guard, or `run()`'s output format (`→ why: cmd`) — existing
tests and CI grep it. Note `--with` component failures after a successful base install should
not roll back the base runtime: FILL IN whether `self add` failures are warnings (recommended:
warn on stderr and exit non-zero AFTER clearing the trap) — bounded by AC "rollback".

### `packages/ai-parrot/tests/docs/test_install_posix.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_script_rejects_unsupported_python() -> None:' packages/ai-parrot/tests/docs/test_install_posix.py)
# AFTER — end of file (after `test_script_rejects_unsupported_python`, :36-55); append:


def _run_global(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the installer in --global --dry-run with HOME and PARROT_HOME sandboxed under tmp."""
    env = {**os.environ, "HOME": str(tmp / "home"), "PARROT_HOME": str(tmp / "home" / ".parrot"), "SHELL": "/bin/bash"}
    return subprocess.run(
        ["bash", str(SCRIPT), "--global", "--dry-run", *extra],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_global_dry_run_bypasses_python_guard(tmp_path: Path) -> None:
    """--global runs before the system-Python guard: a nonexistent --python is never executed."""
    result = _run_global(tmp_path, "--python", "/nonexistent")
    assert result.returncode == 0, result.stderr
    assert "unsupported Python" not in result.stderr
    assert "0.11.28" in result.stdout
    assert "uv venv" in result.stdout or "venv" in result.stdout


def test_global_dry_run_writes_nothing(tmp_path: Path) -> None:
    """--global --dry-run creates no file under HOME / PARROT_HOME."""
    result = _run_global(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home").exists()


def test_global_flags_parse(tmp_path: Path) -> None:
    """--version pins the spec; --with announces one `parrot self add` per component."""
    result = _run_global(tmp_path, "--version", "9.9.9", "--with", "sdd,scraping")
    assert result.returncode == 0, result.stderr
    assert "==9.9.9" in result.stdout
    assert "self add sdd" in result.stdout
    assert "self add scraping" in result.stdout


def test_global_rejects_project_only_flags(tmp_path: Path) -> None:
    """--venv is meaningless with --global and is refused."""
    result = _run_global(tmp_path, "--venv", str(tmp_path / "v"))
    assert result.returncode != 0
    # FILL IN: assert the refusal message — bounded by the message chosen in global_install
```
**Why**: covers spec §4 `test_install_sh_global_dry_run` and the codex S10 guard-bypass; all run
in dry-run so CI needs no network.

### FILL IN checklist
- [ ] `install-parrot.sh::usage` — new `sed -n '2,N p'` end line; bounded by `--help` printing all options.
- [ ] `install-parrot.sh::resolve_extras` — move lines 149-177 verbatim; bounded by `test_posix_script_dry_run`.
- [ ] `install-parrot.sh::global_install` — reject `--venv`/`--with-wiki`/`--system-deps`; bounded by Key Constraints.
- [ ] `install-parrot.sh::global_install` — verify uv tarball layout and install `uv`(+`uvx`) write-then-rename; bounded by "never touch the user's uv".
- [ ] `install-parrot.sh::rollback` — strip the PATH block only if this run added it; bounded by AC rollback.
- [ ] `--with` failure semantics (warn vs fail, without rolling back the base runtime).
- [ ] `test_global_rejects_project_only_flags` — assert the exact refusal message.

---

## Acceptance Criteria

- [ ] `bash scripts/install/install-parrot.sh --global --dry-run --python /nonexistent` exits 0
      without "unsupported Python" (guard bypassed — codex S10).
- [ ] `--global --dry-run` writes nothing under a sandboxed `HOME`/`PARROT_HOME` and performs no
      network access.
- [ ] Global mode installs into `$PARROT_HOME` (default `~/.parrot`): `bin/uv` from the pinned
      `0.11.28` release, checksum-verified; `venv/` built by uv with Python 3.12 from
      `$PARROT_HOME/python`; shims `bin/{parrot,wikitoolkit,bookstore}` created write-then-rename
      (spec §5 bootstrap AC).
- [ ] A user-installed `uv` on PATH is never modified or used.
- [ ] On failure, only paths this run created are removed; pre-existing `~/.parrot` content
      (wikis.json, library/, skills/, brains/, parrot.db) is untouched.
- [ ] PATH marker block added once (idempotent re-run); download/checksum failure aborts before
      any PATH change.
- [ ] Project mode (no `--global`) behaves exactly as before; existing tests still pass.
- [ ] `bash -n scripts/install/install-parrot.sh` passes; all tests pass.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_install_posix.py (additions — see blueprint)
def test_global_dry_run_bypasses_python_guard(tmp_path): ...   # rc 0, no "unsupported Python"
def test_global_dry_run_writes_nothing(tmp_path): ...          # sandboxed HOME stays absent
def test_global_flags_parse(tmp_path): ...                     # ==<version>, one self add per component
def test_global_rejects_project_only_flags(tmp_path): ...      # --venv + --global refused
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4074 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
