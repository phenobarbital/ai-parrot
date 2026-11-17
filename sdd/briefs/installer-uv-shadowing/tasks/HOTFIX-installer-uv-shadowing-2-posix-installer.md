# HOTFIX-installer-uv-shadowing-2: POSIX installer — use a compatible system uv, keep the pinned uv off PATH, migrate legacy installs

**Feature**: installer-uv-shadowing (the `--global` installer's pinned uv shadows the user's uv on PATH)
**Spec**: `sdd/briefs/installer-uv-shadowing.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-installer-uv-shadowing-1
**Assigned-to**: unassigned

---

## Context

`install-parrot.sh --global` always downloads uv and uvx into `$PARROT_HOME/bin`, the directory it prepends to
PATH (`install-parrot.sh:302`, `:275`). This shadows the user's own uv. This task makes the POSIX installer
follow the layout task 1 taught the runtime (brief decisions 1-4 and 6, assumptions A and C):

- A uv already on PATH (outside `$PARROT_HOME`) inside `>=0.11.28,<0.12`: download nothing and record its path in
  `$PARROT_HOME/libexec/uv-path`.
- Otherwise: download the pinned uv `0.11.28` to `$PARROT_HOME/libexec/uv` (never `bin`, no uvx).
- Never touch the user's uv.
- Version-skew guard: if the installed ai-parrot cannot `import parrot.self_.uv` (a release from before this fix,
  or `--version <old>`), also place the pinned uv in `bin` so the old doctor passes, and warn.
- Remove a legacy `bin/uv` / `bin/uvx` only after the runtime doctor has passed.

---

## Scope

- Add `UV_MIN="0.11.28"; UV_MAX="0.12"` next to `UV_VERSION`, with a parity test against `parrot.self_.uv`.
- Add the read-only helpers `uv_ver`, `ver_lt`, `uv_in_range`, `same_dir`, `find_system_uv` and `choose_uv`.
  `choose_uv` runs before `print_plan`, so the plan states the real decision.
- Rewrite the uv part of `global_install`: per-mode download, record or reuse; the `libexec` layout; the
  version-skew guard; legacy cleanup after the doctor.
- Rewrite `print_plan` per mode. The new promise is "Your own uv is never modified, moved or removed".
- Update the `--global` lines of the header comment **in place, keeping its line count**. `usage()` prints lines
  2-37 (`install-parrot.sh:54`), and `test_help_stops_at_the_contract` checks the last line.
- Tests in `tests/docs/test_install_posix.py`. `_run_global` gets a deterministic PATH, the offline harness gains
  system-uv, legacy and old-ai-parrot variants, and the assertions tied to the old layout are updated.
- Regenerate `scripts/install/SHA256SUMS` (both files are listed, so the `.ps1` line stays as is).
- Update the POSIX part of `docs/getting-started.md` (the `--global` description and its Downloads / Writes
  paragraphs, around lines 136-160).

**NOT in scope**: `install-parrot.ps1` and the Windows docs (task 3); the Python runtime (task 1, already done);
pinning the uv checksum (`issue:6e31d9355edc`); the project mode (non-`--global`) path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.sh` | MODIFY | Range constants, system-uv detection, libexec layout, skew guard, legacy cleanup, plan text |
| `packages/ai-parrot/tests/docs/test_install_posix.py` | MODIFY | Parity test, deterministic dry-run PATH, new harness variants, updated assertions |
| `scripts/install/SHA256SUMS` | MODIFY | Regenerated |
| `docs/getting-started.md` | MODIFY | POSIX `--global` description |

---

## Codebase Contract (Anti-Hallucination)

Verified against `origin/main` on 2026-11-08. Line numbers drift once you edit; re-grep the verbatim anchors.

### Verified Imports
```python
from parrot.self_ import uv as uv_mod  # created by HOTFIX-installer-uv-shadowing-1 (PINNED_UV_VERSION, UV_MIN_VERSION, UV_MAX_VERSION)
```

### Existing Signatures to Use
```bash
# scripts/install/install-parrot.sh
GLOBAL=0; PARROT_VERSION=""; ...; UV_VERSION="0.11.28"; CREATED=()   # line 48
RAW_BASE="https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install"   # line 51
usage() { sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; }   # lines 53-55 — header line count is load-bearing
run "<purpose>" cmd...                     # line 57+; announces, and under --dry-run only announces
print_plan() {  # line 162; called as print_plan "$url" "$spec $tools"; line 169 = the "never used or modified" sentence
preflight() {   # line 202; read-only, must stay before any write
fetch <url> <dest>                         # line 233
verify_sha256 <file> <file.sha256>         # line 238
mkdir_tracked <dir>                        # line 244; mkdir -p + CREATED+=
install_shim <src> <dst>                   # line 245
install_uv_bins <extract-dir> <target> <dest-bin-dir>   # line 248; loops `for b in uv uvx`
rollback()                                 # trap EXIT; removes CREATED in reverse; strips the PATH block it added
add_path_block()                           # line 269; prints export PATH="%s/bin:$PATH" at line 275 (unchanged)
global_install() {                         # line 278
  # line 285: target=...; asset=...; uv="$PARROT_HOME/bin/uv"
  # lines 296-302: download / checksum / extract / install_uv_bins into $PARROT_HOME/bin
  # line 307: "$uv" venv ... ; line 309: "$uv" pip install --python "$PARROT_HOME/venv/bin/python" "$spec" "$tools"
  # the runtime doctor: env PARROT_VENV=... "$PARROT_HOME/bin/parrot" self doctor --runtime-only
  # then: run "remove the scratch download dir" rm -rf "$dl"; trap - EXIT; self env --init; --with components
```
```python
# packages/ai-parrot/tests/docs/test_install_posix.py
def _run_global(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:  # line 63; env={**os.environ, ...} ← host PATH
_TOOLS = (...)                                   # line 166
def _fake_bin(tmp: Path, *, drop=(), scripts=None) -> str:   # line 172; creates tmp/"fakebin" (mkdir exist_ok, no parents)
_FAKE_CURL = """..."""                           # line 224; records the dl dir mode in $FIXTURES/dlmode
_FAKE_UV = """..."""                             # line 236; handles `venv` (writes bin/python as an empty sh) and `pip`
def _run_offline_install(tmp_path, *, fake_parrot: str) -> subprocess.CompletedProcess[str]:  # line 247
def test_global_dry_run_prints_plan_and_gate(tmp_path) -> None:   # line 157; asserts "never used or modified" at 162
def test_post_install_repo_readiness_failures_keep_runtime(tmp_path) -> None:  # line 299; asserts bin/uv at 306
def test_help_stops_at_the_contract() -> None:   # line 142
def test_known_components_match_the_packaged_templates() -> None:  # line 107 — parity-test pattern to copy
```

### Does NOT Exist
- ~~`UV_MIN` / `UV_MAX` / `choose_uv` / `find_system_uv` in the installer~~: added by this task.
- ~~`sort -V`~~: do not use it (BSD `sort` on macOS); compare versions in pure bash.
- ~~a `--recreate` / `--force-uv` flag~~: none exists and none is added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/install/install-parrot.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/docs/test_install_posix.py", "action": "MODIFY"},
    {"path": "scripts/install/SHA256SUMS", "action": "MODIFY"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#_run_global",
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#_fake_bin",
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#_run_offline_install",
    "sym:packages/ai-parrot/tests/docs/test_install_posix.py#test_post_install_repo_readiness_failures_keep_runtime"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The user's uv is never written, moved or deleted.** The only `rm` targets are `$PARROT_HOME/bin/uv` and
  `$PARROT_HOME/bin/uvx`. Use `rm -f --`, never `rm -rf`, for them.
- **Read-only before the plan:** `choose_uv` only runs `<uv> --version` and tests files, and it works under
  `--dry-run`.
- **Record the path absolute but not symlink-resolved** (`pwd`, not `pwd -P`, for a relative PATH entry; an
  absolute entry is used as is). Homebrew's `bin/uv` points into a versioned Cellar directory.
- Use `pwd -P` **only** in `same_dir`, to compare PATH entries with `$PARROT_HOME/bin` and `libexec`.
- Keep bash 3.2 compatibility (macOS): no `declare -A`, no `${var,,}`, no `mapfile`; guard empty arrays under `set -u`.
- Every side effect goes through `run` (dry-run stays total). Every new file or directory is added to `CREATED`
  (rollback).
- Legacy cleanup comes after `trap - EXIT` and is warn-only, because the rollback cannot restore deleted files.
- Header comment: edit lines 23-27 in place; the total header (lines 2-37) keeps exactly 36 lines.

---

## Implementation Blueprint

### Steps (in order)
1. Add the constants and helpers. *Why*: decision 1 (range) and a read-only detection that can run before the plan.
2. Call `choose_uv` in `global_install` before `print_plan`, and make `print_plan` mode-aware. *Why*: the plan is
   the installer's contract (C14a) and must state what will happen.
3. Branch the uv step per mode, retarget `install_uv_bins` to `libexec`, use `"$UV_BIN"` for `venv` / `pip`.
   *Why*: decisions 2-3.
4. Add the version-skew guard after `pip install`, and the legacy cleanup after the doctor. *Why*: assumptions A and C.
5. Tests, then `SHA256SUMS`, then docs.

### `scripts/install/install-parrot.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c '^PATH_BLOCK_RC=""' install-parrot.sh)
# AFTER — insert below line 48 (`GLOBAL=0; ...; UV_VERSION="0.11.28"; CREATED=()`), before `PATH_BLOCK_RC=""`
UV_MIN="0.11.28"; UV_MAX="0.12"   # compatible uv: UV_MIN <= v < UV_MAX (kept equal to parrot.self_.uv by tests)
UV_MODE=""; UV_BIN=""; SYS_UV=""; SYS_UV_VER=""; UV_LEGACY_COMPAT=0
```
```bash
# AFTER — insert below verify_sha256() (ends at line 243), before mkdir_tracked()
uv_ver() {  # uv_ver <exe> — "0.11.28" from `<exe> --version`; prints nothing when it cannot run
  local out tok
  out="$("$1" --version 2>/dev/null)" || return 0
  for tok in $out; do
    case "$tok" in [0-9]*) printf '%s' "${tok%%[!0-9.]*}"; return 0 ;; esac
  done
}
ver_lt() {  # ver_lt <a> <b> — true iff dotted-numeric a < b (missing parts = 0); pure bash, no sort -V
  local IFS=. i x y
  local -a A B
  read -ra A <<< "$1"; read -ra B <<< "$2"
  for ((i = 0; i < ${#A[@]} || i < ${#B[@]}; i++)); do
    x="${A[i]:-0}"; y="${B[i]:-0}"
    ((10#$x < 10#$y)) && return 0
    ((10#$x > 10#$y)) && return 1
  done
  return 1
}
uv_in_range() { [ -n "$1" ] && ! ver_lt "$1" "$UV_MIN" && ver_lt "$1" "$UV_MAX"; }
same_dir() {  # same_dir <a> <b> — both exist and are the same physical directory
  [ -d "$1" ] && [ -d "$2" ] && [ "$(cd "$1" && pwd -P)" = "$(cd "$2" && pwd -P)" ]
}
find_system_uv() {  # first `uv` on PATH outside $PARROT_HOME/{bin,libexec}; absolute path, symlinks kept
  local d IFS=:
  for d in $PATH; do
    [ -n "$d" ] || continue
    same_dir "$d" "$PARROT_HOME/bin" && continue
    same_dir "$d" "$PARROT_HOME/libexec" && continue
    if [ -f "$d/uv" ] && [ -x "$d/uv" ]; then
      case "$d" in /*) printf '%s/uv\n' "${d%/}" ;; *) printf '%s/uv\n' "$(cd "$d" && pwd)" ;; esac
      return 0
    fi
  done
  return 1
}
choose_uv() {  # read-only: UV_MODE=managed|system|download, UV_BIN, SYS_UV, SYS_UV_VER
  local managed="$PARROT_HOME/libexec/uv"
  SYS_UV="$(find_system_uv || true)"; SYS_UV_VER=""
  [ -z "$SYS_UV" ] || SYS_UV_VER="$(uv_ver "$SYS_UV")"
  if [ -f "$managed" ] && [ -x "$managed" ] && uv_in_range "$(uv_ver "$managed")"; then UV_MODE=managed; UV_BIN="$managed"
  elif [ -n "$SYS_UV" ] && uv_in_range "$SYS_UV_VER"; then UV_MODE=system; UV_BIN="$SYS_UV"
  else UV_MODE=download; UV_BIN="$managed"; fi
}
record_uv_path() {  # record_uv_path <uv> — write-then-rename $PARROT_HOME/libexec/uv-path
  local f="$PARROT_HOME/libexec/uv-path"
  [ -e "$f" ] || CREATED+=("$f")
  printf '%s\n' "$1" > "$f.tmp.$$" && mv -f "$f.tmp.$$" "$f"
}
```
```bash
# REPLACE install_uv_bins (line 248): install `uv` only (the runtime never calls uvx); same write-then-rename,
# same flat-tarball tolerance; dest is now $PARROT_HOME/libexec (or $PARROT_HOME/bin for the skew guard)
```
```bash
# REPLACE print_plan body (lines 162-172). Keep the C14a role (first output, no side effects) and the SHA256SUMS
# lines. FILL IN: three variants on $UV_MODE —
#  download: "This installer will download uv $UV_VERSION from $1 and verify it against $1.sha256 into
#            $PARROT_HOME/libexec (never on PATH)"; when $SYS_UV is set add "your uv $SYS_UV_VER at $SYS_UV is
#            outside >=$UV_MIN,<$UV_MAX and is left as is"
#  system:   "This installer will use your uv $SYS_UV_VER at $SYS_UV (inside >=$UV_MIN,<$UV_MAX) and record its
#            path in $PARROT_HOME/libexec/uv-path; no uv is downloaded"
#  managed:  "This installer will reuse uv at $PARROT_HOME/libexec/uv"
# then the venv/credentials/PATH lines as today (PATH block still adds $PARROT_HOME/bin: shims only), and replace the
# "never used or modified" sentence with: "Your own uv is never modified, moved or removed; uv/uvx that an older
# parrot installer left in $PARROT_HOME/bin are removed after a successful install."
```
```bash
# In global_install:
#  - after check_components, before print_plan:      choose_uv
#  - line 285: uv="$PARROT_HOME/bin/uv"  →  uv="$UV_BIN"
#  - lines 289-302 (scratch dir + download/verify/extract/install): only when UV_MODE=download; create
#    $PARROT_HOME/libexec with mkdir_tracked; install with
#      run "install uv $UV_VERSION into $PARROT_HOME/libexec (not on PATH; your own uv is never touched)" \
#        install_uv_bins "$dl" "$target" "$PARROT_HOME/libexec"
#    UV_MODE=system:  mkdir_tracked libexec (non-dry-run) then
#      run "record your uv $SYS_UV_VER ($SYS_UV) in $PARROT_HOME/libexec/uv-path" record_uv_path "$SYS_UV"
#    UV_MODE=managed: echo "Reusing uv at $UV_BIN"
#  - the "remove the scratch download dir" step only when a scratch dir was created
```
```bash
# AFTER the `"$uv" pip install ...` step, before the shims — version-skew guard (assumption A)
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '\xe2\x86\x92 check that the installed ai-parrot knows the libexec uv layout (import parrot.self_.uv)\n'
  elif ! "$PARROT_HOME/venv/bin/python" -c 'import parrot.self_.uv' >/dev/null 2>&1; then
    UV_LEGACY_COMPAT=1
    echo "warning: this ai-parrot release predates the libexec uv layout: its doctor needs uv $UV_VERSION in" \
      "$PARROT_HOME/bin, which shadows any uv on your PATH. Once a newer release is installed, 'parrot self update'" \
      "(run it twice from this release) or re-running this installer moves it off PATH." >&2
    run "place uv $UV_VERSION in $PARROT_HOME/bin for this older ai-parrot" legacy_compat_uv
  fi
```
```bash
# FILL IN legacy_compat_uv(): if $PARROT_HOME/libexec/uv exists and uv_ver says exactly $UV_VERSION, copy it to
# $PARROT_HOME/bin/uv write-then-rename (CREATED+= when new); otherwise download + verify + extract the pinned
# archive (create the private scratch dir with mktemp -d if this run has none yet) and install_uv_bins into
# $PARROT_HOME/bin. Bounded by: never copies the user's uv (it may not be exactly $UV_VERSION, which the old doctor requires).
```
```bash
# AFTER `trap - EXIT` — legacy cleanup (assumption C), warn-only
  if [ "$UV_LEGACY_COMPAT" -eq 0 ]; then
    for b in uv uvx; do
      [ -e "$PARROT_HOME/bin/$b" ] || continue
      run "remove the legacy $PARROT_HOME/bin/$b (an older installer put it on PATH, shadowing your uv)" \
        rm -f -- "$PARROT_HOME/bin/$b" || echo "warning: could not remove $PARROT_HOME/bin/$b" >&2
    done
  fi
```
**Why this shape**: `choose_uv` is the only decision point, and it is read-only, so the plan and the actions cannot
disagree. Legacy cleanup is the last uv step, so a failed install never leaves an older runtime without its uv.

### `packages/ai-parrot/tests/docs/test_install_posix.py` (MODIFY)
```python
# REPLACE _run_global (line 63): deterministic PATH — the host's own uv must not decide the dry-run output
def _run_global(tmp: Path, *extra: str, system_uv: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the installer in --global --dry-run with HOME, PARROT_HOME and PATH sandboxed under tmp."""
    sandbox = tmp / "dry-run-path"
    sandbox.mkdir(exist_ok=True)
    scripts = {"uv": f'#!/bin/sh\necho "uv {system_uv} (fake 2026-01-01)"\n'} if system_uv else None
    env = {"HOME": str(tmp / "home"), "PARROT_HOME": str(tmp / "home" / ".parrot"), "SHELL": "/bin/bash",
           "PATH": _fake_bin(sandbox, scripts=scripts)}
    return subprocess.run(["bash", str(SCRIPT), "--global", "--dry-run", *extra],
                          capture_output=True, text=True, check=False, env=env)
```
`_fake_bin` is defined below `_run_global`. That is fine at call time, but keep `_TOOLS` covering every command the
dry-run needs (add `pwd` / `cd` only if the shell lacks them as builtins — they are builtins in bash).

### FILL IN checklist
- [ ] `test_uv_constants_match_runtime`: parse `UV_VERSION="…"`, `UV_MIN="…"` and `UV_MAX="…"` from the script
      text with a regex. Assert they equal `uv_mod.PINNED_UV_VERSION`, `UV_MIN_VERSION` and `UV_MAX_VERSION`.
- [ ] `_FAKE_UV`: also answer `--version` with `uv 0.11.28`.
- [ ] `_run_offline_install(..., system_uv: str | None = None, legacy: bool = False, old_ai_parrot: bool = False)`:
      `system_uv` adds a fake `uv` to the `_fake_bin` scripts. It answers `--version`, `venv` and `pip` like
      `_FAKE_UV`. `legacy` pre-creates `home/.parrot/bin/uv` and `bin/uvx` before the run. `old_ai_parrot` makes
      the fake venv's `python` exit 1 (for example by having the fake `uv venv` read the python body from a
      fixtures file).
- [ ] Replace `test_global_dry_run_prints_plan_and_gate`'s "never used or modified" assertion with the new sentence.
- [ ] Replace the assertion at line 306 with `(home / "libexec" / "uv").exists()` and
      `not (home / "bin" / "uv").exists()`.
- [ ] Add the tests listed in the Test Specification.

---

## Acceptance Criteria

- [ ] No uv on PATH: `libexec/uv` is installed, `bin/uv` and `bin/uvx` do not exist, and there is no `uv-path`.
- [ ] Compatible system uv: nothing is downloaded (the fake curl never writes `dlmode`), `libexec/uv-path` holds the
      system uv's path, and the system uv's bytes and mtime are unchanged.
- [ ] Out-of-range system uv: the pinned uv lands in `libexec/uv`, the system uv is unchanged, and the plan says it
      is left as is.
- [ ] Legacy `bin/uv` and `bin/uvx` are removed after a successful install, and kept when the runtime doctor fails
      (rollback path).
- [ ] An old ai-parrot (venv `python -c 'import parrot.self_.uv'` fails) gets `bin/uv` plus a stderr warning, and
      the install succeeds.
- [ ] `--help` output is unchanged in length and still ends with the contract line. The dry-run output does not
      depend on the host's uv.
- [ ] `SHA256SUMS` matches both installers (`test_ci_install_wiring.py`).
- [ ] All Validation Commands pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`
- `pytest packages/ai-parrot/tests/docs/test_ci_install_wiring.py -q`
- `pytest packages/ai-parrot/tests/self_/test_uv.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_install_posix.py — new tests (helpers per the FILL IN checklist)
import re

from parrot.self_ import uv as uv_mod


def test_uv_constants_match_runtime() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    found = {k: re.search(rf'\b{k}="([^"]+)"', text).group(1) for k in ("UV_VERSION", "UV_MIN", "UV_MAX")}
    assert found == {"UV_VERSION": uv_mod.PINNED_UV_VERSION, "UV_MIN": uv_mod.UV_MIN_VERSION,
                     "UV_MAX": uv_mod.UV_MAX_VERSION}


def test_dry_run_uses_a_compatible_system_uv(tmp_path: Path) -> None:
    result = _run_global(tmp_path, system_uv="0.11.30")
    assert result.returncode == 0, result.stderr
    assert "use your uv 0.11.30" in result.stdout and "download pinned uv" not in result.stdout


def test_dry_run_downloads_when_system_uv_is_out_of_range(tmp_path: Path) -> None:
    result = _run_global(tmp_path, system_uv="0.13.0")
    assert result.returncode == 0, result.stderr
    assert "download pinned uv 0.11.28" in result.stdout and "libexec" in result.stdout and "left as is" in result.stdout


def test_offline_install_records_a_compatible_system_uv(tmp_path: Path) -> None:
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY, system_uv="0.11.30")
    assert result.returncode == 0, result.stderr
    home = tmp_path / "home" / ".parrot"
    system = Path((home / "libexec" / "uv-path").read_text(encoding="utf-8").strip())
    assert system.name == "uv" and not (home / "libexec" / "uv").exists() and not (home / "bin" / "uv").exists()
    assert not (tmp_path / "fixtures" / "dlmode").exists()  # nothing was downloaded


def test_offline_install_out_of_range_system_uv_is_untouched(tmp_path: Path) -> None:
    # FILL IN: capture the fake system uv's bytes + mtime before; after the run assert libexec/uv exists and the
    # system uv is byte-identical with the same mtime.
    ...


def test_offline_install_removes_legacy_uv_after_success(tmp_path: Path) -> None:
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY, legacy=True)
    assert result.returncode == 0, result.stderr
    home = tmp_path / "home" / ".parrot"
    assert not (home / "bin" / "uv").exists() and not (home / "bin" / "uvx").exists()


def test_offline_install_failure_keeps_legacy_uv(tmp_path: Path) -> None:
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_RUNTIME_BROKEN, legacy=True)
    assert result.returncode != 0
    assert (tmp_path / "home" / ".parrot" / "bin" / "uv").exists()


def test_offline_install_old_ai_parrot_keeps_legacy_layout(tmp_path: Path) -> None:
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY, old_ai_parrot=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home" / ".parrot" / "bin" / "uv").exists() and "predates the libexec" in result.stderr
```

---

## Agent Instructions

1. Work in the brief's worktree (`hotfix-installer-uv-shadowing-installer-uv-shadowing` under the worktree root),
   never on `main`. HOTFIX-installer-uv-shadowing-1 must be `done` in `sdd/briefs/installer-uv-shadowing.index.json`.
2. Read the brief, in particular Decisions 1-4 and 6 and Assumptions A and C.
3. Re-grep every verbatim anchor above before editing (line numbers drift).
4. Touch only the four listed files.
5. After the last installer edit: `cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS`.
6. Run every Validation Command with `PYTHONPATH=packages/ai-parrot/src`. Run `ruff check` on the test file.
7. Commit code: `fix(install): HOTFIX-installer-uv-shadowing-2 — POSIX installer keeps uv off PATH, reuses a compatible uv`.
8. Close with `parrot sdd task close HOTFIX-installer-uv-shadowing-2 installer-uv-shadowing verified`, fill in the
   Completion Note, and commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-terra, backend codex, 1 attempt, 417s)
**Date**: 2026-11-10
**Notes**: POSIX installer now picks a managed/system/downloaded uv (range >=0.11.28,<0.12), keeps the pinned uv in libexec off PATH, records system uv in libexec/uv-path, falls back to the legacy bin layout when the installed ai-parrot lacks parrot.self_.uv, and removes legacy bin/uv|uvx after the doctor passes. Plan text, tests, SHA256SUMS and docs/getting-started.md updated. Merge-tier validation: 44 passed. No review corrections.

**Deviations from spec**: none
