# TASK-4074: Bootstrap: install-parrot.sh --global mode (pinned uv, managed venv)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
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

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3 C14, §5 resolved by
Jesus Lara). Every section below already reflects these deltas; this list is the audit trail.

- **C14b — pre-install gate.** Global mode evaluates a `preflight` gate BEFORE any write and
  before the pinned-uv download: supported platform (the TASK-4094 wheel matrix: linux
  x86_64/aarch64, macOS arm64), a download tool (`curl` or `wget`), a checksum tool (`sha256sum`
  or `shasum`), `git`, a writable `PARROT_HOME` (nearest existing ancestor) with at least
  `MIN_FREE_KB` free, and GitHub + PyPI reachable (HEAD request; skipped under `--dry-run`). Each
  failed gate exits non-zero naming the condition and a fix, with nothing written.
- **C14b — post-install runtime check.** After the base runtime is in place the script runs
  `parrot self doctor --runtime-only` (TASK-4080) against the NEW managed runtime — pinned to it
  with `PARROT_VENV="$PARROT_HOME/venv"` so the launcher never redirects to a project venv. That
  scope checks only managed uv, Python, the runtime entry points and PATH; repository readiness,
  host configuration and optional-component checks are excluded. Only a RUNTIME failure triggers
  the EXISTING rollback (only what this run created); doctor's own suggested fixes stay on stdout.
  A successful runtime install stays installed when the invoking repo has unauthenticated `gh`,
  an uncommitted ledger or outdated SDD assets. Under `--dry-run` the call is only announced.
- **C14a — self-describing one-liner.** Global mode prints, first, a `print_plan` paragraph:
  what is downloaded (uv `0.11.28`, URL, `.sha256`), where it writes (`PARROT_HOME/{bin,venv,python}`
  + the PATH block), that the user's own uv is never touched, and the non-piped alternative. The
  docs side of C14a is TASK-4095.
- Tests: each failed gate exits before any write (fake `uname`, a PATH without `curl`/`wget`, a
  read-only `PARROT_HOME` parent); a failing `--runtime-only` check rolls back; and a fake
  `parrot` whose `self doctor --runtime-only` exits 0 while a plain `self doctor` exits 1 (repo
  readiness failures) leaves the runtime installed — all fully offline with fake
  `curl`/`uv`/`parrot` on PATH.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: pin-rationale wording only (local uv is now 0.11.29; the pin stays 0.11.28).
  `install-parrot.sh`, `test_install_posix.py` and `[project.scripts]` anchors unchanged (no commits since baseline).
- Open decisions — do not implement the affected part until resolved (spec rev 0.5 / owner):
  - `wikitoolkit mcp` now needs ai-parrot-tools (`wiki/tools.py:69-76`, `mcp_server.py:525-545, 566-574`; core
    `dependencies` lack it), so a managed venv with only `ai-parrot[...]` cannot serve it. Affected: the install
    spec in `global_install` (add `ai-parrot-tools`, same `--version` pin, or a fix on the wiki side).

---

## Scope

- Add flags `--global`, `--version <X>`, `--with <comma list>` to the arg loop; keep every
  existing flag working unchanged; `--dry-run` stays total (no network, no file writes).
- Take the `--global` branch BEFORE the system-Python guard; project mode is untouched.
- In global mode, before anything else: print the C14a plan paragraph (`print_plan`), then run the
  C14b `preflight` gate (platform, download tool, checksum tool, `git`, writable `PARROT_HOME`
  with `MIN_FREE_KB` free, GitHub/PyPI reachable — network skipped under `--dry-run`); any failed
  gate exits non-zero with the condition and a fix BEFORE any directory is created.
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
- After the base runtime is installed (shims + PATH block), run
  `PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self doctor --runtime-only` through
  `run`; a non-zero exit aborts, which fires the rollback trap (doctor's suggested fixes are
  already on stdout). Never the plain `self doctor`: repository/host/component failures must not
  roll back a healthy runtime. Only announced under `--dry-run`.
- Then run `$PARROT_HOME/bin/parrot self add <c>` for each `--with` component.
- Install an `EXIT` trap that, on failure, removes ONLY paths this run created.
- Extend `test_install_posix.py` with dry-run and arg-parsing tests for the new mode, the
  gate-exits-before-write tests, and the offline post-install-doctor rollback test.

**NOT in scope**:
- `install-parrot.ps1` (TASK-4075); CI wiring and `scripts/install/SHA256SUMS` (TASK-4076);
  user docs (TASK-4095).
- `parrot self add|update|doctor|…` itself (TASK-4079/TASK-4080) — this script only *calls*
  them; the SDD readiness checks inside doctor (C15) are TASK-4080's.
- The full dependency check list — it lives once, in `parrot self doctor` (proposal C14/C15
  decision); this script keeps only the pre-install gate above.
- Any change to project-mode behavior, the Python guard logic, or `--system-deps`.
- A `--purge` / uninstall path (spec §7: out of scope for v1; `parrot self uninstall` owns it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.sh` | MODIFY | `--global` mode, new flags, C14a plan paragraph, C14b preflight gate, pinned-uv bootstrap, shims, PATH block, post-install doctor, rollback |
| `packages/ai-parrot/tests/docs/test_install_posix.py` | MODIFY | dry-run + arg-parsing tests for `--global`; gate-before-write tests; offline doctor-rollback test |

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
- Pinned uv: `0.11.28` (brief cross-cutting decision; the pin stays `0.11.28` even though the locally
  installed uv is now `0.11.29`).
- uv release asset naming: `uv-<target>.tar.gz` + `uv-<target>.tar.gz.sha256`, targets
  `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`, `x86_64-apple-darwin`,
  `aarch64-apple-darwin`. The tarball contains a top-level `uv-<target>/` directory holding
  `uv` and `uvx` (verify on first real download; see FILL IN).

### Does NOT Exist
- ~~any uv-download code in `install-parrot.sh`~~ — the script uses `python -m venv` + pip only (spec §6).
- ~~`--global`, `--version`, `--with`, `PARROT_HOME` handling in the script~~ — all new here.
- ~~a root-level `install.sh`~~ — never create one (spec Non-Goals).
- ~~`parrot self` command (`self add`, `self doctor`, `self doctor --runtime-only`)~~ — delivered
  by TASK-4080 (`--runtime-only` is a rev-0.2 addition there: managed uv, Python, runtime entry
  points and PATH only; mutually exclusive with `--sdd`); this script calls them but must not
  depend on them in `--dry-run` (they are only announced there).
- ~~`preflight`, `print_plan`, `post_install_doctor`, `MIN_FREE_KB`, `SUPPORTED_PLATFORMS` in the
  script~~ — new here (proposal C14a/C14b).
- ~~any reachability (HEAD) check of GitHub/PyPI in either installer~~ — new here; must be skipped
  under `--dry-run` so the dry-run tests stay offline.
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
- **Gate before write (C14b)**: `preflight` runs before `trap rollback EXIT` and before
  `mkdir_tracked` — *why*: a failed gate must leave the filesystem untouched, so there is nothing
  to roll back. Gate order: platform → tools (`curl`/`wget`, `sha256sum`/`shasum`, `git`) →
  `PARROT_HOME` writable + free space → network (GitHub `https://github.com`, PyPI
  `https://pypi.org/simple/`, HEAD via `curl -fsI` / `wget -q --spider`; skipped under `--dry-run`
  with a printed notice). The writability check uses the nearest EXISTING ancestor of
  `PARROT_HOME` (`-w`) and never creates it (the dry-run test asserts `HOME` stays absent).
  Free space: `df -Pk <ancestor> | awk 'NR==2{print $4}'` ≥ `MIN_FREE_KB=2097152` (2 GiB — the
  managed CPython + venv + wheel cache; name the constant, docs cite it).
- **Every gate failure** prints `preflight: <condition> — fix: <fix>` to stderr and exits 1;
  gates never call `run` (they have no side effects) so they print nothing under `--dry-run`
  except the pass/skip summary line per gate.
- **Post-install runtime check (C14b)**: `run "verify the managed runtime (parrot self doctor
  --runtime-only)" env PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self doctor
  --runtime-only` sits after the PATH block and before `--with` components — *why*: a broken
  base runtime must roll back before components are added; doctor prints its own `fix` per
  failed check (TASK-4080), the trap then removes what this run created. `PARROT_VENV` pins the
  launcher (TASK-4071 resolution order: `PARROT_VENV` first) to the venv just built, so a project
  `.venv` in the invoking directory is never what gets checked. `--runtime-only` is mandatory:
  the plain scope adds repository readiness (`gh` auth, committed ledger, SDD asset currency —
  C15), host-config and component checks, none of which may roll back a healthy runtime. Under
  `--dry-run` `run` only announces it. Rollback's stderr line must say that the runtime check
  failed and that its suggested fixes are above.
- **Plan paragraph (C14a)**: `print_plan` is the FIRST output of global mode (before the gate),
  on stdout, one paragraph: uv version + URL + `.sha256` verification, `PARROT_HOME/{bin,venv,python}`
  + the profile PATH block, "your own uv is never used or modified", and the non-piped alternative
  (download `install-parrot.sh` + `SHA256SUMS` from the raw URL, verify, inspect, run). Printed
  under `--dry-run` too (the tests assert on it).
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
   *why*: codex S10, a clean machine never reaches the guard in global mode. `print_plan` and
   `preflight` are the first two things `global_install` does (C14a/C14b).
6. Add the post-install `parrot self doctor` step after the PATH block — *why*: C14b, a broken
   base runtime rolls back before components are added.
7. Extend the POSIX test file — *why*: spec §4 `test_install_sh_global_dry_run`, plus the C14b
   gate-before-write and doctor-rollback tests.

### `scripts/install/install-parrot.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c 'DRY_RUN=0' scripts/install/install-parrot.sh)
# AFTER — `DRY_RUN=0` (verified: scripts/install/install-parrot.sh:37)
GLOBAL=0; PARROT_VERSION=""; WITH_COMPONENTS=""; PYTHON_SET=0; UV_VERSION="0.11.28"; CREATED=()
MIN_FREE_KB=2097152   # C14b gate: 2 GiB free under PARROT_HOME (managed CPython + venv + wheel cache)
RAW_BASE="https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install"   # C14a non-piped alternative
# (also, per Steps 2-4: `--python)` arm sets PYTHON_SET=1 [anchor `      PYTHON="$2"`, :71, 1 occ];
#  new arms --global / --version / --with inserted ABOVE `    --with-wiki)` [:74, 1 occ];
#  header help lines above `#   -h, --help ...` [:23, 1 occ]; `sed -n '2,29p'` [:40, 1 occ] widened;
#  mapping block [:149-177, anchor `# Map provider keys to ai-parrot extras (spec §3 M3; see the getting-started`,
#  1 occ] moved verbatim into resolve_extras() and replaced by the call `resolve_extras`.)

# occurrences: 1 (verified: grep -c '# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any' scripts/install/install-parrot.sh)
# REPLACE — `# Python guard — refuse anything outside >=3.11,<3.14 (AC10). Runs BEFORE any`
# (verified: scripts/install/install-parrot.sh:102) with this block followed by the original line.
resolve_extras() { :; }  # FILL IN: old lines 149-177 verbatim — bounded by test_posix_script_dry_run
print_plan() {  # C14a — first output of global mode; no side effects; printed under --dry-run too
  cat <<EOF
This installer will download uv $UV_VERSION from $1 and verify it against $1.sha256,
create $PARROT_HOME/{bin,venv,python} (a uv-managed Python $PYTHON and a venv with $2),
and add $PARROT_HOME/bin to PATH via a marker block in your shell profile.
A uv already on your PATH is never used or modified. Existing $PARROT_HOME data is never touched.
Prefer not to pipe a download into bash? Fetch $RAW_BASE/install-parrot.sh and
$RAW_BASE/SHA256SUMS, run 'sha256sum -c --ignore-missing SHA256SUMS', read the script, then run it.
EOF
}
gate_fail() { echo "preflight: $1 — fix: $2" >&2; exit 1; }   # C14b — nothing has been written yet
preflight() {  # C14b — read-only checks, in order; never calls run(); never creates PARROT_HOME
  local anc free
  uv_target >/dev/null || gate_fail "unsupported platform $(uname -s)-$(uname -m)" "use a project install (no --global) on this machine; supported: linux x86_64/aarch64, macOS arm64"
  command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || gate_fail "no download tool" "install curl or wget"
  command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || gate_fail "no checksum tool" "install coreutils (sha256sum) or perl (shasum)"
  command -v git >/dev/null 2>&1 || gate_fail "git not found" "install git (the SDD flow and parrot self doctor need it)"
  anc="$PARROT_HOME"; while [ ! -e "$anc" ]; do anc="$(dirname "$anc")"; done   # nearest existing ancestor
  [ -w "$anc" ] || gate_fail "$anc is not writable" "set PARROT_HOME to a writable directory"
  free="$(df -Pk "$anc" | awk 'NR==2{print $4}')"
  [ "${free:-0}" -ge "$MIN_FREE_KB" ] || gate_fail "only ${free}KB free under $anc (need $MIN_FREE_KB)" "free disk space or set PARROT_HOME elsewhere"
  if [ "$DRY_RUN" -eq 1 ]; then echo "preflight: network checks skipped (--dry-run)"; return 0; fi
  # FILL IN: HEAD https://github.com and https://pypi.org/simple/ via `curl -fsI` or `wget -q --spider`;
  #          failure → gate_fail "<host> unreachable" "check your network/proxy" — bounded by AC "gate before write"
  echo "preflight: ok"
}
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
  echo "global install failed (exit $rc); removing only what this run created (if 'parrot self doctor --runtime-only' failed, its suggested fixes are printed above)" >&2
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
  print_plan "$url" "$spec"    # C14a — before anything else
  preflight                    # C14b — exits 1 on any failed gate; nothing written yet
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
  # C14b — runtime scope only, pinned to the venv just built; a non-zero exit under set -e fires the rollback trap
  run "verify the managed runtime (parrot self doctor --runtime-only)" \
    env PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self doctor --runtime-only
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
route side effects through `run`, so `--dry-run` writes nothing and needs no network; `print_plan`
and `preflight` are deliberately read-only and run before the trap, so a failed gate leaves no
trace (C14). The post-install doctor call is the last step of the base install, so its failure
rolls back the base runtime but never runs with half-added components. Do NOT
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


def test_global_dry_run_prints_plan_and_gate(tmp_path: Path) -> None:
    """C14a/C14b: the plan paragraph and the gate summary precede any `→` announcement."""
    result = _run_global(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "0.11.28" in result.stdout and ".sha256" in result.stdout and "SHA256SUMS" in result.stdout
    assert "never used or modified" in result.stdout
    assert result.stdout.index("preflight: network checks skipped") < result.stdout.index("→")


def _fake_bin(tmp: Path, *, drop: tuple[str, ...] = (), scripts: dict[str, str] | None = None) -> str:
    """Build a PATH dir of symlinks to the real tools minus `drop`, plus fake `scripts` (name → body)."""
    # FILL IN: symlink every tool the script needs (bash, uname, df, awk, dirname, tar, mkdir, rm, ln, mv,
    #          grep, printf, cat, sha256sum) from shutil.which(); write each fake script 0o755 — bounded by
    #          the gate tests below, which must stay offline and never touch the real HOME


def test_gate_unsupported_platform_exits_before_write(tmp_path: Path) -> None:
    """C14b: a fake `uname` reporting Linux-mips fails the platform gate; nothing is written."""
    path = _fake_bin(tmp_path, scripts={"uname": '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo mips;; esac\n'})
    env = {"HOME": str(tmp_path / "home"), "PARROT_HOME": str(tmp_path / "home" / ".parrot"), "PATH": path}
    result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1
    assert "preflight: unsupported platform" in result.stderr and "fix:" in result.stderr
    assert not (tmp_path / "home").exists()


def test_gate_missing_download_tool_exits_before_write(tmp_path: Path) -> None:
    """C14b: a PATH without curl/wget fails the tool gate before any write (and before network)."""
    path = _fake_bin(tmp_path, drop=("curl", "wget"))
    env = {"HOME": str(tmp_path / "home"), "PARROT_HOME": str(tmp_path / "home" / ".parrot"), "PATH": path}
    result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1 and "no download tool" in result.stderr
    assert not (tmp_path / "home").exists()


def test_gate_unwritable_home_exits_before_write(tmp_path: Path) -> None:
    """C14b: PARROT_HOME under a read-only parent fails the writability gate."""
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(0o555)
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PARROT_HOME": str(ro / ".parrot")}
    result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1 and "not writable" in result.stderr
    assert not (ro / ".parrot").exists()
    # FILL IN: skip when running as root (root ignores 0o555) — bounded by CI running unprivileged


def _run_offline_install(tmp_path: Path, *, fake_parrot: str) -> subprocess.CompletedProcess[str]:
    """C14b harness: a real non-dry-run `--global` with fakes — never touches the network or the real HOME."""
    # FILL IN: build a fixture tarball uv-x86_64-unknown-linux-gnu/uv (fake uv: `venv <dir>` creates
    #          <dir>/bin/{python,wikitoolkit,bookstore} stubs and writes `fake_parrot` as <dir>/bin/parrot;
    #          `pip install` is a no-op) + its .sha256; fake `curl` copies the fixture for the tarball /
    #          .sha256 URLs and exits 0 for `-I` (HEAD); fake `uname` reports Linux-x86_64; run the script
    #          with HOME/PARROT_HOME under tmp and PATH from _fake_bin — bounded by the two tests below


_PARROT_RUNTIME_BROKEN = "#!/bin/sh\necho 'uv: missing — fix: rerun the bootstrap'; exit 1\n"
_PARROT_REPO_NOT_READY = (
    "#!/bin/sh\n"
    'case "$*" in *--runtime-only*) echo "runtime: ok"; exit 0;; esac\n'
    "echo 'gh: not authenticated — fix: gh auth login'; echo 'ledger: uncommitted'; exit 1\n"
)


def test_post_install_runtime_failure_rolls_back(tmp_path: Path) -> None:
    """C14b: a failing `parrot self doctor --runtime-only` removes what the run created."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_RUNTIME_BROKEN)
    assert result.returncode != 0
    assert "self doctor --runtime-only" in result.stdout and "suggested fixes are printed above" in result.stderr
    assert not (tmp_path / "home" / ".parrot").exists()
    rc_file = tmp_path / "home" / ".bashrc"
    assert not rc_file.exists() or "# >>> parrot >>>" not in rc_file.read_text(encoding="utf-8")


def test_post_install_repo_readiness_failures_keep_runtime(tmp_path: Path) -> None:
    """C14b: unauthenticated gh / uncommitted ledger / outdated SDD assets never roll back a healthy runtime."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY)
    assert result.returncode == 0, result.stderr
    assert "--runtime-only" in result.stdout and "gh: not authenticated" not in result.stdout
    home = tmp_path / "home" / ".parrot"
    assert (home / "bin" / "parrot").exists() and (home / "venv").exists()
    assert "# >>> parrot >>>" in (tmp_path / "home" / ".bashrc").read_text(encoding="utf-8")
```
**Why**: covers spec §4 `test_install_sh_global_dry_run` and the codex S10 guard-bypass; the first
block runs in dry-run so CI needs no network, and the C14b tests stay offline by faking the few
binaries the gate and the install consult (`uname`, `curl`, `uv`, `parrot`) — never the real HOME.

### FILL IN checklist
- [ ] `install-parrot.sh::usage` — new `sed -n '2,N p'` end line; bounded by `--help` printing all options.
- [ ] `install-parrot.sh::resolve_extras` — move lines 149-177 verbatim; bounded by `test_posix_script_dry_run`.
- [ ] `install-parrot.sh::global_install` — reject `--venv`/`--with-wiki`/`--system-deps`; bounded by Key Constraints.
- [ ] `install-parrot.sh::global_install` — verify uv tarball layout and install `uv`(+`uvx`) write-then-rename; bounded by "never touch the user's uv".
- [ ] `install-parrot.sh::rollback` — strip the PATH block only if this run added it; bounded by AC rollback.
- [ ] `--with` failure semantics (warn vs fail, without rolling back the base runtime).
- [ ] `test_global_rejects_project_only_flags` — assert the exact refusal message.
- [ ] `install-parrot.sh::preflight` — the GitHub/PyPI HEAD checks (curl `-fsI` / wget `--spider`); bounded by "skipped under --dry-run".
- [ ] `test_install_posix.py::_fake_bin` — the symlink/fake-script PATH builder; bounded by the gate tests staying offline.
- [ ] `test_install_posix.py::_run_offline_install` — the fixture tarball + fake `curl`/`uv`/`parrot`; bounded by the two C14b outcomes (runtime failure rolls back; readiness failures keep the runtime).
- [ ] `test_gate_unwritable_home_exits_before_write` — root skip guard.

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
- [ ] **C14a**: `--global` (also under `--dry-run`) prints, before any `→` line, what is downloaded
      (uv `0.11.28`, URL, `.sha256`), where it writes (`PARROT_HOME/{bin,venv,python}` + the PATH
      block), that the user's own uv is never used or modified, and the non-piped alternative
      (raw-URL `install-parrot.sh` + `SHA256SUMS`, verify, inspect, run).
- [ ] **C14b gate before write**: in `--global` mode an unsupported platform, a missing download or
      checksum tool, a missing `git`, an unwritable `PARROT_HOME` ancestor, less than `MIN_FREE_KB`
      free, or an unreachable GitHub/PyPI each exit 1 with `preflight: <condition> — fix: <fix>` on
      stderr BEFORE any directory is created; `--dry-run` skips only the network gates and says so.
- [ ] **C14b post-install runtime check**: after shims + PATH block the script runs
      `PARROT_VENV="$PARROT_HOME/venv" "$PARROT_HOME/bin/parrot" self doctor --runtime-only`
      (never the plain scope); a non-zero exit triggers the existing rollback (only this run's
      paths, PATH block included) and stderr says doctor's fixes are above; `--dry-run` only
      announces the call.
- [ ] **C14b readiness never rolls back**: with a `parrot` whose `--runtime-only` passes while the
      plain `self doctor` fails (unauthenticated `gh`, uncommitted ledger, outdated SDD assets),
      the run exits 0 and `bin/`, `venv/` and the PATH block remain.
- [ ] Project mode (no `--global`) behaves exactly as before; existing tests still pass.
- [ ] `bash -n scripts/install/install-parrot.sh` passes; all tests pass, offline.

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
def test_global_dry_run_prints_plan_and_gate(tmp_path): ...    # C14a paragraph + gate summary precede "→"
def test_gate_unsupported_platform_exits_before_write(tmp_path): ...   # C14b: fake uname → exit 1, nothing written
def test_gate_missing_download_tool_exits_before_write(tmp_path): ... # C14b: PATH without curl/wget
def test_gate_unwritable_home_exits_before_write(tmp_path): ...       # C14b: read-only PARROT_HOME parent
def test_post_install_runtime_failure_rolls_back(tmp_path): ...       # C14b: offline fakes; --runtime-only exit 1 → rollback
def test_post_install_repo_readiness_failures_keep_runtime(tmp_path): ...  # C14b: --runtime-only ok, plain doctor fails → stays
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
