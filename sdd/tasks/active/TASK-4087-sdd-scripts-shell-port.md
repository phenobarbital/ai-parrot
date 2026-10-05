# TASK-4087: SDD helpers move B2: port close_task.sh / heal_orphans.sh to Python

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4086
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 requires that "`close_task.sh`/`heal_orphans.sh` logic ports to Python
modules with the `.sh` files wrapping them". Spec §9 S9 (CONFIRM) flags shell-only
helpers and `jq` as tooling a target machine may lack. Both scripts depend on `bash` and
`jq`, so neither works on Windows or on a machine without `jq`. Spike S5 (TASK-4070) has
the inventory.

This task **ports** the logic (it is not a `git mv`) to
`parrot.sdd.scripts.close_task` and `parrot.sdd.scripts.heal_orphans`, with **identical
CLI and observable behaviour**:

- same positional arguments;
- same stdout/stderr lines, character for character, emoji included;
- same exit codes;
- same file moves, same `git` commands, same index mutation.

The two `.sh` files become thin wrappers that exec the Python modules. Every existing
`scripts/sdd/close_task.sh TASK-… <slug> verified` invocation in docs, agents and
`finalize_task.py:394/423` keeps working until TASK-4089 rewrites the references.

`close_task.sh` is load-bearing. `finalize_task` (moved by TASK-4086) runs it under an
**isolated `GIT_INDEX_FILE`** (`finalize_task.py:415-424`), and its internal
`git add -u sdd/tasks/active` must keep honouring that environment variable. The port
must therefore inherit `os.environ` unchanged for every `git` call.

---

## Scope

- Create `parrot/sdd/scripts/close_task.py`, a line-by-line port of `close_task.sh`
  (contract steps C1–C12 below) that needs no `jq`.
- Create `parrot/sdd/scripts/heal_orphans.py`, a line-by-line port of
  `heal_orphans.sh` (steps H1–H8 below) that needs no `jq`.
- Rewrite `scripts/sdd/close_task.sh` and `scripts/sdd/heal_orphans.sh` as `exec`
  wrappers. Keep both executable (git mode `100755`).
- Add `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py`. It uses a temporary
  git repo with a per-spec index and an active task file, and covers both modules and
  both wrappers.

- Add the foreign-repo fallback to the MOVED `parrot/sdd/scripts/finalize_task.py`
  (created by TASK-4086, a declared dependency): when `repo_root/scripts/sdd/close_task.sh`
  does not exist, run `[sys.executable, "-m", "parrot.sdd.scripts.close_task", *args]`
  with the SAME inherited environment (the isolated `GIT_INDEX_FILE` must flow through).
  In the monorepo the `.sh` wrapper still exists and is preferred, so behavior there is
  unchanged — without this fallback, closing a task in an installed foreign repo raises
  `OperationError("close_task.sh not found …")` and the spec's `test_sdd_flow_in_foreign_repo`
  acceptance cannot hold.

**NOT in scope**:
- The LEGACY `scripts/sdd/finalize_task.py` shim (TASK-4086 owns it; it aliases the moved
  module, so the fallback lands there automatically).
- Rewriting markdown references to `scripts/sdd/close_task.sh` (TASK-4089).
- Changing the remediation hint strings in `check_task_state.py:196-197`.
- Any new flag, option or message. A port that "improves" output breaks the parity ACs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | CREATE | Python port of `close_task.sh` (identical CLI/behaviour, no jq) |
| `packages/ai-parrot/src/parrot/sdd/scripts/heal_orphans.py` | CREATE | Python port of `heal_orphans.sh` (identical CLI/behaviour, no jq) |
| `scripts/sdd/close_task.sh` | MODIFY | Becomes `exec python -m parrot.sdd.scripts.close_task "$@"` wrapper |
| `scripts/sdd/heal_orphans.sh` | MODIFY | Becomes `exec python -m parrot.sdd.scripts.heal_orphans "$@"` wrapper |
| `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py` | CREATE | tmp-git-repo behaviour + exit-code tests for both ports and wrappers |
| `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` | MODIFY | Foreign-repo fallback: missing `scripts/sdd/close_task.sh` ⇒ run `python -m parrot.sdd.scripts.close_task` (file created by TASK-4086 — this task depends on it) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Used ONLY lazily inside close_task's ledger-emission helper (exactly what the heredoc imports today,
# scripts/sdd/close_task.sh:135-137):
from parrot.knowledge.wiki.ledger.events import LedgerEvent   # ledger/events.py:103 (fields kind, subject, actor, ts, payload)
from parrot.knowledge.wiki.ledger.log import LedgerLog        # ledger/log.py:10; __init__(self, path: str) :13; append(event) :21
from parrot.knowledge.wiki.project import find_shared_root    # project.py:1398  def find_shared_root(start: Path | None = None) -> Path | None
# Everything else: stdlib (argparse not required — positional parsing mirrors bash), json, os, shutil, subprocess, sys,
# datetime, pathlib. No third-party import at module level.
```

### Existing Signatures to Use

**`scripts/sdd/close_task.sh` (152 lines, mode 100755): every step the port must reproduce**
```text
C1  :31     set -euo pipefail
C2  :33-35  TASK_ID=$1, FEATURE_SLUG=$2, VERIFICATION=${3:-verified}; extra args ignored; VERIFICATION NOT validated.
C3  :37-40  if TASK_ID or FEATURE_SLUG empty → stderr "usage: $0 <TASK-ID> <feature-slug> [verified|partial|forced]" → exit 1
            (checked BEFORE any git call; verified: no-arg run → exit 1)
C4  :42-43  REPO_ROOT=$(git rev-parse --show-toplevel); cd "$REPO_ROOT"
            outside a repo: git prints "fatal: …" to stderr and set -e exits **128** (verified 2026-10-05 — the header's
            "1 usage error" comment does not cover this case; the port must return 128, git stderr passed through)
C5  :45-48  ACTIVE_DIR=sdd/tasks/active, COMPLETED_DIR=sdd/tasks/completed, INDEX=sdd/tasks/index/<slug>.json,
            NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)   (seconds precision, literal "+00:00")
C6  :50     mkdir -p completed/   — happens BEFORE the not-found check (so exit 2 still leaves completed/ created)
C7  :53-64  active_matches = glob active/<TASK_ID>-*.md, completed_matches = glob completed/<TASK_ID>-*.md (sorted)
            no active & ≥1 completed → stdout "ℹ️  <TASK_ID>: already in completed/ (no active copy) — nothing to move."
            no active & no completed → stderr "✗ <TASK_ID>: no file in active/ and no twin in completed/." → exit 2
C8  :66-81  for each active src (basename_md := basename(src); dest = completed/<basename_md>):
              dest exists → `git rm -q --ignore-unmatch <src>` (stdout+stderr discarded, failure ignored); rm -f <src>;
                            stdout "✓ <TASK_ID>: removed orphan active copy (twin already in completed/)."
              else        → `git mv <src> <dest>` (stderr discarded); on failure plain `mv`;
                            stdout "✓ <TASK_ID>: moved active → completed/<basename_md>"
C9  :84-86  no active match → basename_md = basename(completed_matches[0])
C10 :89-100 if INDEX is a file: rewrite it (jq, 2-space indent, trailing newline, via mktemp + mv):
              for task with .id == TASK_ID: status="done", completed_at=NOW, verification=VERIFICATION,
                                            file="sdd/tasks/completed/<basename_md>"
              if ALL tasks have status == "done": top-level completed_at = NOW
              then `git add <INDEX>` (failure aborts under set -e with git's exit code)
            jq failure (invalid JSON / .tasks not iterable) aborts under set -e with jq's exit code 5
            missing INDEX → silently skipped
C11 :103-104 `git add completed/<basename_md>` and `git add -u sdd/tasks/active` (both: output discarded, failure ignored)
C12 :107-113 survivors = glob active/<TASK_ID>-*.md; any → stderr "✗ <TASK_ID>: active copy STILL present after close: <space-joined>" → exit 3
C13 :115    stdout "✅ <TASK_ID> closed (verification=<VERIFICATION>). active/ is clean."
C14 :124-152 best-effort ledger emission AFTER C12/C13 (failures never change the exit code):
              start_dir = cwd (= repo root, captured BEFORE importing parrot — navconfig chdirs on import)
              shared_root = find_shared_root(start_dir) or start_dir; ledger_dir = shared_root/.parrot/ledger; mkdir -p
              LedgerEvent(kind="task.closed", subject=f"task:{task_id}", actor="agent:close_task.sh",
                          payload={"feature": feature_slug, "verification": verification})
              LedgerLog(str(ledger_dir / "events.jsonl")).append(event)
              except Exception → stderr "⚠️  task.closed ledger emission skipped: <exc>"
            exit 0
Python today: the heredoc runs `python3 -` (bare python3, :124).
```

**`scripts/sdd/heal_orphans.sh` (85 lines, mode 100755): every step the port must reproduce**
```text
H1 :23     set -euo pipefail
H2 :25-30  if $1 == "--dry-run" → DRY_RUN=1, shift. FEATURE_SLUG=${1:-}. Only the FIRST position is checked
           ("heal_orphans.sh slug --dry-run" is NOT a dry run — slug=slug, flag ignored). Extra args ignored.
H3 :32-33  REPO_ROOT=$(git rev-parse --show-toplevel); cd — outside a repo → exit 128 (verified), git stderr passed through
H4 :35-45  indices = [index/<slug>.json] if slug else sorted glob index/*.json
H5 :48-53  done_ids = sort -u of `.tasks[]? | select(.status=="done") | .id` over indices that are files;
           unreadable/invalid JSON or non-iterable .tasks → contributes nothing (errors suppressed)
H6 :55-82  for tid in done_ids:
             active = glob active/<tid>-*.md; none → continue
             completed = glob completed/<tid>-*.md; none → stdout "⚠️  <tid>: done but NO completed/ twin — leaving active
                                                       file (manual review)."; kept += 1; continue   (one line, see :65)
             for f in active (relative path "sdd/tasks/active/<file>"):
               dry → stdout "would reap: <f>"
               else → `git rm -q --ignore-unmatch <f>` (output discarded, failure ignored); rm -f <f>; stdout "reaped orphan: <f>"
               reaped += 1   (counted per FILE; kept counted per TASK-ID)
H7 :84     stdout "── heal_orphans: <reaped> orphan(s) <would be reaped|reaped>, <kept> kept for review."
H8 :85     exit 0
No Python call in heal_orphans.sh.
```

**Callers that must keep working (verified):**
```python
# packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py (moved by TASK-4086; was scripts/sdd/finalize_task.py)
close_script = repo_root / "scripts" / "sdd" / "close_task.sh"          # :394
subprocess.run(["bash", str(close_script), task_id, feature_slug, _VERIFICATION], cwd=repo_root,
               env={**os.environ, "GIT_INDEX_FILE": str(tmp_index_path)}, capture_output=True, text=True)  # :422-428
# tests/sdd/test_close_task_ledger.py:18 runs ["bash", str(REPO_ROOT/"scripts/sdd/close_task.sh"), ...] with
#   PYTHONPATH=<repo>/packages/ai-parrot/src prepended (:54-68); asserts exit codes 0/2 and events.jsonl contents.
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py:33,110-113 copies the real
#   scripts/sdd/close_task.sh into a tmp repo's scripts/sdd/ and runs finalize_task against it.
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.close_task` / `parrot.sdd.scripts.heal_orphans`~~ — created
  here.
- ~~A Python `jq` dependency~~ — use `json` from the stdlib.
- ~~`argparse`-style flags on close_task (`--verification`, `--help` semantics)~~ —
  close_task has positional args only. Do not add argparse. With bash, `close_task.sh --help`
  treats `--help` as TASK_ID and fails with exit 128 (outside a repo) or 1 (when SLUG is
  missing). Mirror that.
- ~~`set -e` "abort" helpers in the codebase~~ — implement the abort points (C4, C10)
  explicitly by returning the git/jq-equivalent exit code.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/close_task.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/heal_orphans.py", "action": "CREATE"},
    {"path": "scripts/sdd/close_task.sh", "action": "MODIFY"},
    {"path": "scripts/sdd/heal_orphans.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_shell_port.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# finalize_task.py:108-112 — the repo's git-runner idiom (inherits env so GIT_INDEX_FILE flows through):
def _run_git(args, *, cwd, env=None, check=True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)
```

### Key Constraints
- **Inherit the environment.** Every `git` call passes no `env=` (or `env=None`), so
  `GIT_INDEX_FILE` set by `finalize_task` is honoured exactly as in bash.
- **Byte-identical messages.** Copy the strings from the contract above. They contain
  `ℹ️`, `✓`, `✗`, `✅`, `⚠️`, `──` and `→`, and some have **two spaces** after an emoji
  (`ℹ️  `, `⚠️  `). Write stdout with `sys.stdout.write(line + "\n")` and stderr with
  `sys.stderr.write`. These are CLI scripts, but the repo bans `print` in library code.
- **Index JSON format.** Use `json.dumps(data, indent=2, ensure_ascii=False) + "\n"`,
  written to a temp file in the same directory and then `os.replace`d. This mirrors jq's
  pretty print and the `mktemp` + `mv`. Preserve key order. The comparison must be on
  parsed JSON plus format, not on a raw-byte golden file.
- **Ledger emission in-process, last, lazy, never fatal.** Capture
  `repo_root = Path(git toplevel)` and compute every path as absolute BEFORE importing
  `parrot.knowledge.wiki.*`. That import pulls in navconfig, which `os.chdir`s (see the
  heredoc comment at `close_task.sh:129-132`). Wrap the whole helper in
  `except Exception`. Keep `actor="agent:close_task.sh"` verbatim, because ledger
  consumers key on it.
- **Exit 128** when not in a git repo. Return `proc.returncode` from the failed
  `git rev-parse` and forward its stderr. Do not raise.
- **Wrapper interpreter.** `close_task.sh` uses bare `python3` today (`:124`), and
  `heal_orphans.sh` calls no Python. Both wrappers use `${PYTHON:-python3}`, which
  defaults to the same interpreter and allows an override.
- **Wrapper `PYTHONPATH` (decision).** Each wrapper prepends its own checkout's
  `packages/ai-parrot/src` (resolved from `${BASH_SOURCE[0]}`) when that directory
  exists. *Why*: the shared venv is editable-installed against the MAIN checkout. Inside
  a worktree (including this feature's own worktree before merge), a bare `python3`
  would import a `parrot` that lacks `parrot.sdd.scripts.close_task`, and closing a task
  would break. The `.sh` previously always ran its own checkout's logic, so this keeps
  that semantics. `tests/sdd/test_close_task_ledger.py` already prepends the same
  directory. Wrappers exist only in the monorepo, so deriving the path from the
  wrapper's location is legitimate.

### References in Codebase
- `scripts/sdd/close_task.sh`, `scripts/sdd/heal_orphans.sh` — the sources being ported.
- `parrot/sdd/scripts/finalize_task.py:375-460` — the isolated-index caller.

---

## Implementation Blueprint

### Steps (in order)
1. Write `close_task.py` following C1–C14 in order. *Why*: a step-for-step port can be
   checked against the bash line by line.
2. Write `heal_orphans.py` following H1–H8. *Why*: same reason.
3. Write the tests (Test Specification) and run them against the **new modules**
   directly (`python -m`). *Why*: this proves the port before the wrappers switch over.
4. Replace both `.sh` bodies with the wrappers, then check
   `git ls-files -s scripts/sdd/close_task.sh scripts/sdd/heal_orphans.sh` still shows
   `100755`. *Why*: `finalize_task` runs `bash <path>`, while docs run the file directly.
5. Run every Validation Command, including the existing `test_close_task_ledger.py` and
   `test_finalize_task.py`, which now go through the wrapper. *Why*: these are the parity
   gates for live callers.

### `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` (CREATE)
```python
"""Deterministically close a single SDD task (Python port of ``scripts/sdd/close_task.sh``, FEAT-633).

Moves ``sdd/tasks/active/<TASK-ID>-*.md`` to ``sdd/tasks/completed/``, marks it "done" in its per-spec index,
stages the change, then HARD-VERIFIES that no active copy survives. Usage (identical to the shell script):

    python -m parrot.sdd.scripts.close_task <TASK-ID> <feature-slug> [verified|partial|forced]

Exit codes: 0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed ·
5 index not valid JSON / no task list (jq parity) · 128 not a git repository (git parity).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_DIR = "sdd/tasks/active"
COMPLETED_DIR = "sdd/tasks/completed"
INDEX_DIR = "sdd/tasks/index"
USAGE = "usage: {prog} <TASK-ID> <feature-slug> [verified|partial|forced]\n"


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git in ``cwd`` inheriting os.environ (GIT_INDEX_FILE must flow through); output captured (= discarded)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def _now() -> str:
    """C5: ``date -u +%Y-%m-%dT%H:%M:%S+00:00``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None:
    """C10: mark ``task_id`` done in the per-spec index; stamp top-level completed_at when every task is done.

    Raises:
        ValueError: when the index is not valid JSON or ``tasks`` is not a list (caller returns 5, jq parity).
    """
    # FILL IN: load JSON, mutate matching task(s) (status/completed_at/verification/file), all-done stamp,
    #          write json.dumps(indent=2, ensure_ascii=False)+"\n" to a NamedTemporaryFile(dir=index.parent) + os.replace
    #          — bounded by C10 (key order preserved; missing task id ⇒ only the all-done check applies)
    raise NotImplementedError


def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
    """C14: best-effort ``task.closed`` ledger event; never raises, never changes the exit code."""
    try:
        from parrot.knowledge.wiki.ledger.events import LedgerEvent  # lazy: navconfig chdirs on import
        from parrot.knowledge.wiki.ledger.log import LedgerLog
        from parrot.knowledge.wiki.project import find_shared_root

        shared_root = find_shared_root(start_dir) or start_dir
        ledger_dir = shared_root / ".parrot" / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        event = LedgerEvent(
            kind="task.closed",
            subject=f"task:{task_id}",
            actor="agent:close_task.sh",
            payload={"feature": feature_slug, "verification": verification},
        )
        LedgerLog(str(ledger_dir / "events.jsonl")).append(event)
    except Exception as exc:  # noqa: BLE001 — ledger emission never blocks closure
        _err(f"⚠️  task.closed ledger emission skipped: {exc}")


def main(argv: Sequence[str] | None = None) -> int:
    """Port of close_task.sh C1–C14 (positional args only; extra args ignored, verification not validated)."""
    args = list(sys.argv[1:] if argv is None else argv)
    task_id = args[0] if len(args) > 0 else ""
    feature_slug = args[1] if len(args) > 1 else ""
    verification = args[2] if len(args) > 2 and args[2] else "verified"
    if not task_id or not feature_slug:
        sys.stderr.write(USAGE.format(prog="python -m parrot.sdd.scripts.close_task"))
        return 1
    top = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    if top.returncode != 0:
        sys.stderr.write(top.stderr)
        return top.returncode
    repo_root = Path(top.stdout.strip()).resolve()
    # FILL IN: C5–C13 in order (mkdir completed/, sorted globs, orphan-remove vs git mv→mv fallback with the exact
    #          messages, basename fallback, update_index + `git add <INDEX>` (ValueError → return 5; git add failure →
    #          return its code), quiet `git add` of completed file and `git add -u sdd/tasks/active`, survivor check → 3,
    #          ✅ line) — bounded by the C-step contract; all git paths repo-relative with cwd=repo_root
    raise NotImplementedError
    _emit_task_closed(repo_root, task_id, feature_slug, verification)  # C14 — after the ✅ line
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: `main` mirrors the bash top-to-bottom. `update_index` is separate so
it can be unit-tested and so the jq-parity exit code 5 is explicit. In C3, `$0` printed
the script path. The port prints its `-m` form. That text goes to stderr only, and the
exit code (1) is unchanged.

### `packages/ai-parrot/src/parrot/sdd/scripts/heal_orphans.py` (CREATE)
```python
"""Self-healing sweep for stalled SDD task files (Python port of ``scripts/sdd/heal_orphans.sh``, FEAT-633).

Reaps an ``sdd/tasks/active/<TASK-ID>-*.md`` only when a per-spec index marks it "done" AND a completed/ twin
exists. Usage (identical to the shell script; ``--dry-run`` is honoured only as the FIRST argument):

    python -m parrot.sdd.scripts.heal_orphans [--dry-run] [feature-slug]

Exit codes: 0 swept · 128 not a git repository (git parity).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

ACTIVE_DIR = "sdd/tasks/active"
COMPLETED_DIR = "sdd/tasks/completed"
INDEX_DIR = "sdd/tasks/index"


def done_task_ids(indices: Iterable[Path]) -> list[str]:
    """H5: sorted unique ids with status "done" across ``indices``; unreadable/invalid files contribute nothing."""
    # FILL IN: tolerate missing file, bad JSON, non-list "tasks", non-dict entries, non-str ids — bounded by H5
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Port of heal_orphans.sh H1–H8."""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = bool(args) and args[0] == "--dry-run"
    if dry_run:
        args = args[1:]
    feature_slug = args[0] if args else ""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if top.returncode != 0:
        sys.stderr.write(top.stderr)
        return top.returncode
    repo_root = Path(top.stdout.strip()).resolve()
    # FILL IN: H4 index selection, H6 loop with exact messages + counters (reaped per file, kept per id),
    #          quiet `git rm -q --ignore-unmatch <rel>` then unlink(missing_ok=True), H7 summary line — bounded by H4–H7
    raise NotImplementedError
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### `scripts/sdd/close_task.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c '# close_task.sh — Deterministically close a single SDD task.' scripts/sdd/close_task.sh)
# REPLACE — whole file (152 lines); header anchor `# close_task.sh — Deterministically close a single SDD task.`
#           (verified: scripts/sdd/close_task.sh:3). Keep mode 100755.
#!/usr/bin/env bash
#
# close_task.sh — Deterministically close a single SDD task.
#
# Compatibility wrapper (FEAT-633): the logic lives in parrot.sdd.scripts.close_task.
# Usage and exit codes are unchanged:
#   scripts/sdd/close_task.sh <TASK-ID> <feature-slug> [verified|partial|forced]
#   0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed
set -euo pipefail

_src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../packages/ai-parrot/src" 2>/dev/null && pwd || true)"
if [[ -n "$_src" ]]; then
  export PYTHONPATH="${_src}${PYTHONPATH:+:${PYTHONPATH}}"
fi
exec "${PYTHON:-python3}" -m parrot.sdd.scripts.close_task "$@"
```

### `scripts/sdd/heal_orphans.sh` (MODIFY)
```bash
# occurrences: 1 (verified: grep -c '# heal_orphans.sh — Self-healing sweep for stalled SDD task files.' scripts/sdd/heal_orphans.sh)
# REPLACE — whole file (85 lines); header anchor `# heal_orphans.sh — Self-healing sweep for stalled SDD task files.`
#           (verified: scripts/sdd/heal_orphans.sh:3). Keep mode 100755.
#!/usr/bin/env bash
#
# heal_orphans.sh — Self-healing sweep for stalled SDD task files.
#
# Compatibility wrapper (FEAT-633): the logic lives in parrot.sdd.scripts.heal_orphans.
# Usage and exit codes are unchanged:
#   scripts/sdd/heal_orphans.sh [--dry-run] [feature-slug]
set -euo pipefail

_src="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../packages/ai-parrot/src" 2>/dev/null && pwd || true)"
if [[ -n "$_src" ]]; then
  export PYTHONPATH="${_src}${PYTHONPATH:+:${PYTHONPATH}}"
fi
exec "${PYTHON:-python3}" -m parrot.sdd.scripts.heal_orphans "$@"
```

### `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py` (CREATE)
See **Test Specification**. That block is the starting file.

### `packages/ai-parrot/src/parrot/sdd/scripts/finalize_task.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'close_script = repo_root / "scripts" / "sdd" / "close_task.sh"' scripts/sdd/finalize_task.py — re-run against the MOVED file once TASK-4086 lands; the move changes only imports, so the anchor survives)
# REPLACE — the two lines below the anchor `close_script = repo_root / "scripts" / "sdd" / "close_task.sh"` (verified today at scripts/sdd/finalize_task.py:394-396)
    close_script = repo_root / "scripts" / "sdd" / "close_task.sh"
    if close_script.is_file():
        close_argv = ["bash", str(close_script)]
    else:
        # Foreign repo (installed flow): the repo-local wrapper does not exist.
        close_argv = [sys.executable, "-m", "parrot.sdd.scripts.close_task"]
```
**Why**: in the monorepo the wrapper is preferred (byte-identical behavior, existing tests
copy the real `.sh` into tmp repos — test_finalize_task.py:33,110-113 keep passing); in a
foreign repo the module port is the only thing installed. Thread `close_argv` into the
existing subprocess call at finalize_task.py:415-424 in place of the hardcoded
`["bash", str(close_script)]` form — verify the exact call shape there and keep the
inherited env untouched. Check `sys` is already imported (it is — verify).

### FILL IN checklist
- [ ] `close_task.py::update_index`: JSON rewrite. Bounded by C10 and jq-format parity.
- [ ] `close_task.py::main`: C5–C13 body. Bounded by the C-step contract (exact
  messages, exit codes 2/3/5/128).
- [ ] `heal_orphans.py::done_task_ids`: tolerant collection. Bounded by H5.
- [ ] `heal_orphans.py::main`: H4–H7. Bounded by the H-step contract.
- [ ] Remove the unreachable `raise NotImplementedError` lines once each body is written
  (the blueprint keeps the trailing call/return only to show order).

---

## Acceptance Criteria

- [ ] AC-1: In a temporary git repo with `sdd/tasks/index/demo.json` (task `in-progress`)
  and `sdd/tasks/active/TASK-9001-demo.md`, `python -m parrot.sdd.scripts.close_task TASK-9001 demo verified`
  exits 0. The file is in `completed/`. The index entry has
  `status=="done"`, `verification=="verified"`,
  `file=="sdd/tasks/completed/TASK-9001-demo.md"` and a `completed_at` matching
  `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$`. The top-level `completed_at` is set (all
  tasks are done). `git diff --cached --name-only` lists the completed file, the index,
  and the active deletion (or a rename).
- [ ] AC-2: Exit codes: missing args → 1; nothing to close → 2 (and `completed/` exists
  afterwards); not a git repo → 128; index `{"tasks": null}` → 5. A second close of an
  already-closed task → 0 with the `ℹ️  … already in completed/` line.
- [ ] AC-3: An active copy with an existing completed twin is removed, with the
  `✓ … removed orphan active copy` line.
- [ ] AC-4: `heal_orphans`: `--dry-run` prints `would reap: sdd/tasks/active/<file>` and
  deletes nothing. A real run deletes and prints `reaped orphan: …`. A done task with no
  twin prints the `⚠️  … manual review` line. The summary line matches H7 exactly.
  `slug --dry-run` is NOT a dry run.
- [ ] AC-5: `bash scripts/sdd/close_task.sh …` and `bash scripts/sdd/heal_orphans.sh …`
  (the wrappers) produce the same results as AC-1/AC-4. Both files keep git mode `100755`.
- [ ] AC-6: Neither port shells out to `jq` or `bash`
  (`grep -E '"jq"|"bash"' parrot/sdd/scripts/{close_task,heal_orphans}.py` is empty).
- [ ] AC-7: The existing callers pass unmodified: `tests/sdd/test_close_task_ledger.py`
  (ledger emission and failure tolerance) and `test_finalize_task.py` (isolated
  `GIT_INDEX_FILE`).
- [ ] AC-8: `ruff check packages/ai-parrot/src/parrot/sdd/scripts packages/ai-parrot/tests/sdd`
  is clean.
- [ ] Spec §5: "`scripts/sdd/` wrappers keep the monorepo's existing invocations working".

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_scripts_shell_port.py -q`
- `pytest tests/sdd/test_close_task_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py -q`
- `pytest tests/sdd_scripts/test_check_task_state.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_scripts_shell_port.py
"""FEAT-633: Python ports of close_task.sh / heal_orphans.sh keep CLI + behaviour identical."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for sub in ("active", "completed", "index"):
        (root / "sdd" / "tasks" / sub).mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "sdd/tasks/active/TASK-9001-demo.md").write_text("# TASK-9001\n", encoding="utf-8")
    index = {"feature": "demo", "tasks": [{"id": "TASK-9001", "status": "in-progress", "completed_at": None,
                                           "file": "sdd/tasks/active/TASK-9001-demo.md"}]}
    (root / "sdd/tasks/index/demo.json").write_text(json.dumps(index), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), env.get("PYTHONPATH", "")])
    return env


def _module(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", f"parrot.sdd.scripts.{name}", *args],
                          cwd=cwd, env=_env(), capture_output=True, text=True)


def _wrapper(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(REPO_ROOT / "scripts" / "sdd" / f"{name}.sh"), *args],
                          cwd=cwd, env={**_env(), "PYTHON": sys.executable}, capture_output=True, text=True)


@pytest.mark.parametrize("runner", [_module, _wrapper])
def test_close_moves_marks_done_and_stages(repo: Path, runner) -> None:
    proc = runner("close_task", repo, "TASK-9001", "demo", "verified")
    assert proc.returncode == 0, proc.stderr
    assert "✅ TASK-9001 closed (verification=verified). active/ is clean." in proc.stdout
    assert (repo / "sdd/tasks/completed/TASK-9001-demo.md").is_file()
    data = json.loads((repo / "sdd/tasks/index/demo.json").read_text(encoding="utf-8"))
    task = data["tasks"][0]
    assert (task["status"], task["verification"], task["file"]) == ("done", "verified", "sdd/tasks/completed/TASK-9001-demo.md")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", task["completed_at"])
    assert data["completed_at"] == task["completed_at"]
    assert "sdd/tasks/index/demo.json" in _git(repo, "diff", "--cached", "--name-only")


def test_close_exit_codes(repo: Path, tmp_path: Path) -> None:
    assert _module("close_task", repo).returncode == 1
    assert _module("close_task", repo, "TASK-404", "demo").returncode == 2
    outside = tmp_path / "plain"
    outside.mkdir()
    assert _module("close_task", outside, "TASK-9001", "demo").returncode == 128
    assert _module("close_task", repo, "TASK-9001", "demo").returncode == 0
    second = _module("close_task", repo, "TASK-9001", "demo")
    assert second.returncode == 0 and "already in completed/" in second.stdout


def test_close_invalid_index_exits_5(repo: Path) -> None:
    (repo / "sdd/tasks/index/demo.json").write_text('{"tasks": null}', encoding="utf-8")
    assert _module("close_task", repo, "TASK-9001", "demo").returncode == 5


@pytest.mark.parametrize("runner", [_module, _wrapper])
def test_heal_orphans_dry_run_then_reap(repo: Path, runner) -> None:
    # FILL IN: mark TASK-9001 done in the index + create a completed/ twin while the active copy stays;
    #          assert dry-run output/no deletion, then real reap + exact H7 summary line; and "demo --dry-run" reaps
    raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`.
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/parrot-installer.json`.
4. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
5. **Update status** in `sdd/tasks/index/parrot-installer.json` to `"in-progress"` (set
   `started_at`) and commit only that index file.
6. **Implement**. Start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
7. **Verify** that all acceptance criteria are met by running the Validation Commands.
8. **Commit the code**. Stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4087 parrot-installer verified`.
   It moves this file to `sdd/tasks/completed/` and marks it `"done"` in the index. Never
   move or copy the file by hand. This task closes itself through the new wrapper; if
   that fails, the port is broken.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
