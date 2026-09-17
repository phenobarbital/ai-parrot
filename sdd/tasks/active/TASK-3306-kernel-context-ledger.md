# TASK-3306: Test-scope kernel — attempt context and escalation ledger

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3304
**Assigned-to**: unassigned

---

## Context

Implements the persistence half of spec **Module 3** (`test_scope/context.py`):

- **Attempt context** (spec §2 Overview item 6): `parrot-test-scope.json` written by the sdd-coder engine
  into an attempt sub-worktree's **per-worktree git admin dir** (never the checkout — no untracked file;
  never the common dir — parallel attempts would collide). The guard is active only when it exists.
- **Escalation ledger** (item 2c, AC9c, R14): `parrot-test-scope-escalations.json` in the same per-worktree
  git dir, mapping `distribution → {core file → blob hash}` of the last **green** escalated run, so a
  core-change escalation is paid once per feature content.

Consumers: TASK-3308 (`plan_tests` dedupe), TASK-3309 (guard reads context), TASK-3310/3311 (record green
runs), TASK-3312/3313 (engine writes context), TASK-3314 (codex hook reads context).

---

## Scope

- Create `test_scope/context.py` with `CONTEXT_FILENAME`, `worktree_git_dir`, `write_attempt_context`,
  `read_attempt_context`, `LEDGER_FILENAME`, `read_ledger`, `record_green_escalation`, `pending_escalations`.
- Atomic writes (temp file + `os.replace`).
- Malformed/absent files read as "no context" / empty ledger — escalations then re-run, never skipped.
- Write `test_scope/test_context.py` using real temp git repos (including a linked `git worktree`).

**NOT in scope**: calling these from the engine/dispatchers/hooks (TASK-3312/3313/3314), from
`plan_tests` (TASK-3308) or from the CLI/QANode (TASK-3310/3311); editing `test_scope/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` | CREATE | Attempt context + escalation ledger I/O |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py` | CREATE | Unit tests on temp git repos/worktrees |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# test_scope/context.py — stdlib + relative only:
from .datatypes import AttemptContext, CoreHit, LedgerEntry   # test_scope/datatypes.py (TASK-3304)
# Tests:
from parrot.flows.dev_loop.test_scope import AttemptContext, CoreHit   # test_scope/__init__.py (TASK-3304)
from parrot.flows.dev_loop.test_scope import context as ctxmod
```

### Existing Signatures to Use
```python
# test_scope/datatypes.py (TASK-3304)
@dataclass(frozen=True)
class AttemptContext: tier: str; task_id: str; task_file: str; base_ref: str
@dataclass(frozen=True)
class CoreHit: path: str; module: str; fanin: int; forced: bool; distributions: tuple[str, ...]
@dataclass(frozen=True)
class LedgerEntry: distribution: str; core_blobs: dict[str, str]

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:26 — DO NOT reuse for this task:
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
    # follows `commondir` (L38-40) → returns the COMMON git dir, shared by all worktrees → wrong for per-attempt files

# git (2.43.0 installed): `git rev-parse --absolute-git-dir` prints the PER-WORKTREE admin dir
#   (e.g. <repo>/.git/worktrees/<name>) in a linked worktree and <repo>/.git in the main checkout.
# git: `git hash-object -- <path>` prints the blob hash of a working-tree file.
```

### Does NOT Exist
- ~~a per-worktree git dir helper in the repo~~ — `repository_paths` returns the common dir; this task adds `worktree_git_dir`
- ~~`AttemptContext.to_json()` / `from_json()`~~ — serialize with `dataclasses.asdict` + `json`; construct with `AttemptContext(**data)`
- ~~a ledger "clear" / "invalidate" API~~ — not needed: only green runs are recorded; changed content re-arms automatically
- ~~logging in the kernel~~ — no `self.logger`; the kernel runs under system python in the native hook

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# stdlib subprocess, never raising to callers on git failure
proc = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=worktree, capture_output=True, text=True, check=False)
```

### Key Constraints
- Stdlib only, relative imports, Google docstrings, type hints (AC3). Synchronous (called from hook/CLI;
  async callers wrap with `asyncio.to_thread`).
- Ledger JSON shape: `{"<distribution>": {"core_blobs": {"<repo-relative path>": "<blob sha>"}}}`.
- `record_green_escalation` merges into the existing ledger (other distributions untouched) and **replaces**
  the entry of each given distribution with the current blobs of `core_files`.
- `pending_escalations`: for each distribution in the union of `hit.distributions` (sorted), relevant core files
  are the `hit.path`s whose `distributions` contain it; the distribution is **skipped** iff a ledger entry exists and
  every relevant file's current blob equals the stored one. A missing file (blob unavailable) never matches.
- Any read error / JSON error / wrong shape → treat as absent (R14).

### References in Codebase
- Spec §2 Overview items 2c and 6, §3 M3 skeleton (context.py), AC9c, R14
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:26-42` — why the common dir is wrong here

---

## Implementation Blueprint

### Steps (in order)
1. Implement `worktree_git_dir` with `git rev-parse --absolute-git-dir` — *why*: per-worktree dir isolates parallel attempts.
2. Implement context write/read with atomic replace — *why*: the guard reads concurrently with the engine write.
3. Implement ledger read/record/pending — *why*: AC9c "paid once" relies on exact blob comparison.
4. Write tests with a real `git init` repo and a linked `git worktree add` — *why*: prove per-worktree ≠ common dir.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` (CREATE)
```python
"""Attempt context and escalation ledger stored in the per-worktree git dir (FEAT-563 M3)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .datatypes import AttemptContext, CoreHit, LedgerEntry

CONTEXT_FILENAME: str = "parrot-test-scope.json"
LEDGER_FILENAME: str = "parrot-test-scope-escalations.json"


def worktree_git_dir(worktree: Path) -> Path | None:
    """Per-worktree admin dir (the `gitdir:` target, NOT commondir); None outside git."""
    proc = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=worktree, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON to ``path`` via a temp file in the same directory and ``os.replace``."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _read_json(path: Path) -> object | None:
    """Parsed JSON or None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_attempt_context(worktree: Path, ctx: AttemptContext) -> Path:
    """Write ``ctx`` to ``<per-worktree git dir>/parrot-test-scope.json``.

    Raises:
        RuntimeError: when ``worktree`` is not inside a git worktree.
    """
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        raise RuntimeError(f"not a git worktree: {worktree}")
    target = git_dir / CONTEXT_FILENAME
    _atomic_write_json(target, asdict(ctx))
    return target


def read_attempt_context(worktree: Path) -> AttemptContext | None:
    """None when absent or malformed — the guard is then inactive."""
    git_dir = worktree_git_dir(worktree)
    data = _read_json(git_dir / CONTEXT_FILENAME) if git_dir else None
    # FILL IN: return AttemptContext(**data) only if data is a dict with exactly str values for
    #          tier/task_id/task_file/base_ref; otherwise None — bounded by R14 (malformed → inactive)
    return None
```
**Why this shape**: names/signatures fixed by spec §3 M3 skeleton; `RuntimeError` on write makes an engine
misconfiguration loud while reads fail closed to "inactive".

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` (CREATE, continued — ledger part)
```python
def _blob(worktree: Path, path: str) -> str | None:
    """Current git blob hash of a working-tree file, or None when unavailable."""
    proc = subprocess.run(["git", "hash-object", "--", path], cwd=worktree, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def read_ledger(worktree: Path) -> dict[str, LedgerEntry]:
    """Empty when absent or malformed (→ escalations re-run; never silently skipped)."""
    git_dir = worktree_git_dir(worktree)
    data = _read_json(git_dir / LEDGER_FILENAME) if git_dir else None
    ledger: dict[str, LedgerEntry] = {}
    # FILL IN: accept only {str: {"core_blobs": {str: str}}}; any other shape → return {} — bounded by R14
    return ledger


def record_green_escalation(worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str]) -> None:
    """Store current blob hashes of core_files for each distribution after a green run."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return
    blobs = {p: b for p in core_files if (b := _blob(worktree, p))}
    current = {d: {"core_blobs": dict(e.core_blobs)} for d, e in read_ledger(worktree).items()}
    # FILL IN: for each dist in hit_dists set current[dist] = {"core_blobs": blobs}; then
    #          _atomic_write_json(git_dir / LEDGER_FILENAME, current) — bounded by AC9c
    return None


def pending_escalations(worktree: Path, hits: Sequence[CoreHit]) -> tuple[list[str], list[str]]:
    """(distributions to run, distributions skipped because ledger blobs match current content)."""
    ledger = read_ledger(worktree)
    to_run: list[str] = []
    skipped: list[str] = []
    for dist in sorted({d for h in hits for d in h.distributions}):
        relevant = [h.path for h in hits if dist in h.distributions]
        entry = ledger.get(dist)
        # FILL IN: skipped iff entry is not None and every relevant path has _blob(...) not None and equal to
        #          entry.core_blobs.get(path); else to_run — bounded by AC9c ("any content change re-arms")
    return to_run, skipped
```
**Why this shape**: the ledger compares content, not commits, so a rebase that does not change core files keeps
the green result, while any edit re-arms the escalation (spec item 2c). Put both blocks in one `context.py`.

### FILL IN checklist
- [ ] `read_attempt_context` — strict shape validation; bounded by R14
- [ ] `read_ledger` — strict shape validation; bounded by R14
- [ ] `record_green_escalation` — merge + atomic write; bounded by AC9c
- [ ] `pending_escalations` — skip/run decision; bounded by AC9c
- [ ] Test bodies below

---

## Acceptance Criteria

- [ ] Context is written under the **per-worktree** git dir of a linked worktree (not `<repo>/.git`, not the checkout) — `test_context_in_per_worktree_gitdir`
- [ ] Absent or malformed context → `read_attempt_context` returns `None`
- [ ] Green escalation recorded; unchanged blobs → distribution listed as skipped (spec AC9c)
- [ ] Changed core file content → distribution back in `to_run` (spec AC9c)
- [ ] Malformed ledger → treated as empty (R14)
- [ ] `context.py` imports with stdlib only (existing `test_stdlib_only.py` still passes; AC3)
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py` clean

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import AttemptContext, CoreHit
from parrot.flows.dev_loop.test_scope import context as ctxmod


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    (root / "core.py").write_text("x = 1\n")
    return root


@pytest.fixture
def linked(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    (wt / "core.py").write_text("x = 1\n")
    return wt


def test_context_in_per_worktree_gitdir(repo: Path, linked: Path):
    ctx = AttemptContext(tier="task", task_id="TASK-1", task_file="sdd/tasks/active/TASK-1-x.md", base_ref="feat-x")
    path = ctxmod.write_attempt_context(linked, ctx)
    assert path.parent != repo / ".git"
    assert "worktrees" in path.parts
    assert not (linked / ctxmod.CONTEXT_FILENAME).exists()
    assert ctxmod.read_attempt_context(linked) == ctx
    assert ctxmod.read_attempt_context(repo) is None


def test_malformed_context_is_inactive(linked: Path):
    git_dir = ctxmod.worktree_git_dir(linked)
    (git_dir / ctxmod.CONTEXT_FILENAME).write_text("{not json")
    assert ctxmod.read_attempt_context(linked) is None


def test_ledger_skips_green_same_content(linked: Path):
    hit = CoreHit(path="core.py", module="core", fanin=60, forced=False, distributions=("a", "b"))
    assert ctxmod.pending_escalations(linked, [hit]) == (["a", "b"], [])
    ctxmod.record_green_escalation(linked, ["a"], ["core.py"])
    assert ctxmod.pending_escalations(linked, [hit]) == (["b"], ["a"])


def test_ledger_rearms_on_content_change_or_red(linked: Path):
    hit = CoreHit(path="core.py", module="core", fanin=60, forced=True, distributions=("a",))
    ctxmod.record_green_escalation(linked, ["a"], ["core.py"])
    (linked / "core.py").write_text("x = 2\n")
    assert ctxmod.pending_escalations(linked, [hit]) == (["a"], [])


def test_malformed_ledger_is_empty(linked: Path):
    (ctxmod.worktree_git_dir(linked) / ctxmod.LEDGER_FILENAME).write_text('{"a": 3}')
    assert ctxmod.read_ledger(linked) == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3306-kernel-context-ledger.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
