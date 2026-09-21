# TASK-3586: Write scripts/install/install-parrot.sh and its tests

**Feature**: FEAT-586 — Public Install & Getting-Started Guide for AI-Parrot
**Spec**: `sdd/specs/parrot-install-guide.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3: the POSIX installer that automates the guide's steps
on Ubuntu 24.04.4 LTS+ and macOS 14+. **No dependency on TASK-3584**: the script
derives its steps from the spec (§3 M3), not by reading the getting-started guide
at runtime, and it shares no files with any other task. It runs concurrently with
the guide and the PowerShell installer.

---

## Scope

- Create `scripts/install/install-parrot.sh` exposing the spec flags:
  `--provider`, `--extras`, `--venv`, `--python`, `--with-wiki`, `--install-cli`,
  `--system-deps`, `--dry-run`, `-h|--help`.
- Behavior: detect OS (Ubuntu vs macOS); refuse Python outside `>=3.11,<3.14`
  BEFORE installing; create or reuse (never delete) the venv; `uv pip`/`pip`
  install `ai-parrot` + chosen provider/extras; optional `wikitoolkit build`;
  echo every command with its purpose; `sudo`/`brew`/`apt` only under
  `--system-deps`; `--install-cli` npm-installs the LATEST MINOR (`@latest`) of
  the claude/codex CLI for a CLI-backed provider (pins no version); `--dry-run`
  prints the full plan and touches nothing.
- Create `packages/ai-parrot/tests/docs/test_install_posix.py` with
  `test_posix_script_syntax`, `test_posix_script_dry_run`,
  `test_script_rejects_unsupported_python`.

**NOT in scope**: the PowerShell script (TASK-3587); handling interactive auth;
CI wiring (TASK-3588); the guide text.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/install/install-parrot.sh` | CREATE | POSIX installer (Ubuntu/macOS), flag-driven, idempotent, `--dry-run` |
| `packages/ai-parrot/tests/docs/test_install_posix.py` | CREATE | Syntax, dry-run and Python-guard tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified facts
- Supported Python: `>=3.11,<3.14` — `packages/ai-parrot/pyproject.toml:18`.
- Console script `wikitoolkit` exists after install — pyproject.toml:204.
- CLI-backed providers install the CLI binary + the satellite extra:
  `claude` (npm `@anthropic-ai/claude-code`) + `ai-parrot[claude-agent]`;
  `codex` (npm `@openai/codex`) + `ai-parrot[codex-agent]`.
- No `claude`/`codex` CLI **binary** version floor exists in the tree — install
  `@latest`, pin nothing (spec §6, AC18).

### Existing patterns to follow
- `scripts/run_in_venv.sh` — an existing repo shell script; match its shebang and style.

### Does NOT Exist
- ~~an RTK step~~ — out of scope (spec AC15).
- ~~`ai-parrot[rtk]`~~ — no such extra; the in-framework analogue is `ai-parrot[rust]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "scripts/install/install-parrot.sh", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/docs/test_install_posix.py", "action": "CREATE" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `set -euo pipefail`; POSIX-friendly bash. No `sudo` unless `--system-deps`.
- Idempotent: reuse an existing venv; never delete one.
- Every privileged/network command is echoed with its purpose BEFORE it runs
  (spec AC8) — this is the security-transparency contract, not decoration.
- `--dry-run` must reach every branch and execute nothing.

### References in Codebase
- `docs/wiki-claude-code.md` — the `wikitoolkit build` step it automates
- `packages/ai-parrot/pyproject.toml` — provider extras and the Python range

---

## Implementation Blueprint

### Steps (in order)
1. Parse flags into variables with a `--help` usage block — *why*: predictable UX.
2. Add a `run()` wrapper that echoes "→ <purpose>: <cmd>" then executes (or, under
   `--dry-run`, only echoes) — *why*: satisfies AC8 in one place and makes
   `--dry-run` total.
3. Detect OS + guard the Python version before any install — *why*: fail fast on
   an unsupported interpreter (AC10).
4. venv → package+extras → optional CLI → optional wiki build — *why*: the guide's
   order.

### `scripts/install/install-parrot.sh` (CREATE)
```bash
#!/usr/bin/env bash
# AI-Parrot installer — automates the AI-Parrot getting-started guide (FEAT-586).
# Never destructive; every privileged/network command is announced before it runs.
set -euo pipefail

PROVIDER="anthropic"; EXTRAS=""; VENV=".venv"; PYTHON="python3"
WITH_WIKI=0; INSTALL_CLI=0; SYSTEM_DEPS=0; DRY_RUN=0

usage() { sed -n '2,40p' "$0"; }   # FILL IN: or a here-doc usage block listing every flag

run() {  # run "<purpose>" cmd...
  local why="$1"; shift
  printf '→ %s: %s\n' "$why" "$*"
  [ "$DRY_RUN" -eq 1 ] || "$@"
}

# FILL IN: arg parse loop over --provider/--extras/--venv/--python/--with-wiki/
#          --install-cli/--system-deps/--dry-run/-h — bounded by spec §3 M3.

# Python guard — refuse anything outside >=3.11,<3.14 (AC10):
PYVER="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
case "$PYVER" in 3.11|3.12|3.13) ;; *)
  echo "unsupported Python $PYVER; AI-Parrot needs >=3.11,<3.14" >&2; exit 1;; esac

# FILL IN: OS detect (uname); optional --system-deps (apt-get/brew, each via run());
#          venv create-or-reuse; run "install ai-parrot" uv pip/pip install
#          "ai-parrot[<provider,extras>]"; optional --install-cli (@latest npm);
#          optional --with-wiki (wikitoolkit build) — every branch through run().
```
**Why this shape**: the `run()` wrapper is the mechanism that makes AC8 (announce
before executing) and `--dry-run` totality both true with no per-call effort.
Keep it; route EVERY side-effecting command through it.

### `packages/ai-parrot/tests/docs/test_install_posix.py` (CREATE)
```python
"""Tests for scripts/install/install-parrot.sh (FEAT-586, TASK-3586)."""
from __future__ import annotations
import shutil, subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.sh"


def test_posix_script_syntax() -> None:
    """`bash -n` parses the script."""
    assert SCRIPT.is_file()
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_posix_script_dry_run() -> None:
    """--dry-run prints a plan and creates no venv."""
    # FILL IN: run `bash SCRIPT --dry-run --provider anthropic --venv <tmp>`;
    #          assert exit 0, stdout has '→', and the tmp venv was NOT created —
    #          bounded by AC9.
    raise NotImplementedError


def test_script_rejects_unsupported_python() -> None:
    """A 3.10/3.14 interpreter is refused before install."""
    # FILL IN: invoke with --python pointing at a stub that reports 3.10; assert
    #          non-zero exit and an 'unsupported Python' message — bounded by AC10.
    raise NotImplementedError
```
**Why this shape**: syntax is checkable everywhere; the dry-run and Python-guard
tests are `FILL IN` because each needs a small harness (tmp dir / stub python)
bounded by the cited AC.

### FILL IN checklist
- [ ] script arg-parse loop + usage block; bounded by spec §3 M3
- [ ] OS detect + `--system-deps` (apt/brew) via `run()`; bounded by AC8
- [ ] venv create-or-reuse + package/extras/CLI/wiki steps; bounded by AC9
- [ ] `test_posix_script_dry_run` body; bounded by AC9
- [ ] `test_script_rejects_unsupported_python` body; bounded by AC10
- [ ] `chmod +x` the script

---

## Acceptance Criteria
- [ ] Script exposes the documented flags and is idempotent (spec AC9)
- [ ] `--dry-run` prints the full plan and touches nothing (spec AC9)
- [ ] Refuses Python outside `>=3.11,<3.14` before installing (spec AC10)
- [ ] Every sudo/network command announced before running (spec AC8)
- [ ] No RTK / host-wiring / `/sdd-*` content (spec AC15)
- [ ] `bash -n` clean; tests pass

## Validation Commands
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py::test_posix_script_syntax -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py::test_posix_script_dry_run -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py::test_script_rejects_unsupported_python -q`

---

## Test Specification
```python
def test_posix_script_syntax(): ...
def test_posix_script_dry_run(): ...
def test_script_rejects_unsupported_python(): ...
```

---

## Agent Instructions
1. Read the spec (§3 M3, §7) for the flag contract and risks.
2. Verify the Python range and provider extras in `pyproject.toml`.
3. Index status → in-progress.
4. Implement from the blueprint; complete every `# FILL IN`; `chmod +x`.
5. Run the Validation Commands.
6. Move to `sdd/tasks/completed/`, index → done, fill the note.

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe
