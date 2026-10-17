# TASK-4431: Brief-aware index discovery across the dev_loop resolvers

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec rev 0.2, §2 Overview + §3 Module 5. The per-brief index lives at
`sdd/briefs/<slug>.index.json`, but five dev_loop resolvers hardcode
`sdd/tasks/index/`, so `sdd-worker` → `parrot-sdd-coder` would fail a brief
with `feature_not_found` (verified: `engine._resolve_feature` raises at
engine.py:1536-1538). This task implements the one shared discovery rule in
`task_scheduler.py` and makes all five delegate to it:

- **per-slug lookup**: `sdd/tasks/index/<slug>.json` if it exists, else
  `sdd/briefs/<slug>.index.json` if it exists, else the `sdd/tasks/index`
  path (today's not-found behavior, unchanged);
- **enumeration**: sorted `sdd/tasks/index/*.json` minus `_orphans.json`,
  then sorted `sdd/briefs/*.index.json`.

Feature indexes always win ties, so no existing feature run changes behavior.

---

## Scope

- Add `resolve_index_path()` and `iter_index_files()` to
  `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`; make
  `TaskScheduler.from_worktree` use `resolve_index_path`.
- `sdd_coder/engine.py::_resolve_feature._read_headers` enumerates via
  `iter_index_files` (drop its own `index_dir` glob + `_orphans` skip).
- `sdd_coder/inspection.py::_resolve_index_path` and
  `sdd_coder/checkpoint.py::_index_path` delegate to `resolve_index_path`.
- `sdd_coder/background.py::_resolve_feature_id` enumerates via
  `iter_index_files` and also accepts `BRIEF-<KEY>` ids.
- New tests in
  `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py`.

**NOT in scope**: `DevelopmentNode` (TASK-4432); importing anything from
`scripts.sdd` (not importable from `parrot` — research.py:162-168);
`check_task_graph`/board tooling (briefs are intentionally invisible there).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | MODIFY | shared discovery helpers; `from_worktree` delegates |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_resolve_feature` enumerates via `iter_index_files` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py` | MODIFY | `_resolve_index_path` delegates |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` | MODIFY | `_index_path` delegates |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `_resolve_feature_id` enumerates + accepts BRIEF ids |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler   # verified: sdd_coder/inspection.py:55
from parrot.flows.dev_loop.task_scheduler import TaskScheduler            # verified: sdd_coder/checkpoint.py:67, engine.py:53
# new names this task adds to task_scheduler.py and imports in the resolvers:
from parrot.flows.dev_loop.task_scheduler import iter_index_files, resolve_index_path
```

### Existing Signatures to Use
```python
# task_scheduler.py
from typing import Dict, List, Optional, Sequence, Set                    # line 18
class TaskScheduler:                                                       # line 129
    @classmethod
    def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]      # line 164 — None on missing/malformed
    @classmethod
    def from_worktree(cls, worktree_path: str, feature_slug: str) -> Optional["TaskScheduler"]  # line 201
        # body line 213: index_path = Path(worktree_path) / "sdd" / "tasks" / "index" / f"{feature_slug}.json"

# sdd_coder/engine.py
async def _resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx   # line 1486
    #  line 1496: `        index_dir = Path(wt) / "sdd" / "tasks" / "index"`
    #  lines 1498-1510: def _read_headers() -> List[Tuple[Path, Dict[str, Any]]]  (skips _ORPHANS_INDEX_NAME)
    #  match order lines 1514-1533 — UNCHANGED by this task

# sdd_coder/inspection.py
def _resolve_index_path(worktree: Path, feature: str) -> Path              # line 103-105
def _load_scheduler(worktree: Path, feature: str) -> TaskScheduler         # line 108 — uses from_worktree (gets briefs for free)

# sdd_coder/checkpoint.py
def _index_path(worktree: Path, feature: str) -> Path                      # line 186-188
def _load_index_sync(worktree: Path, feature: str) -> Tuple[Path, bytes, dict]  # line 191
#  prepare_review_checkpoint requires non-empty feature_id/base_branch/spec     # lines 462-466

# sdd_coder/background.py
_FEATURE_ID_RE = re.compile(r"^FEAT-\d+$")                                 # line 70
@staticmethod
def _resolve_feature_id(worktree: Path, feature: str) -> str               # line 835 — glob at line 840
```

### Does NOT Exist
- ~~`TaskScheduler.from_index_path`~~ — NOT created (spec rev 0.2); `from_index_file` already exists.
- ~~any `scripts.sdd.*` import from `parrot`~~ — forbidden; the `scripts.sdd` package is not importable here (research.py:162-168). Define the brief-index constants locally in task_scheduler.py.
- ~~`_ORPHANS_INDEX_NAME` in task_scheduler.py~~ — it lives in engine.py; define a local `"_orphans.json"` constant in task_scheduler.py.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_worktree",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_index_file",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._resolve_feature",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py#_resolve_index_path",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py#_index_path"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Feature index always wins**: a slug present in both locations resolves
  to `sdd/tasks/index/<slug>.json` (AC-2) — this keeps every existing run
  byte-identical.
- Run `wikitoolkit symbols blast TaskScheduler.from_worktree` before editing
  (CLAUDE.md FEAT-498) and record the caller list in the Completion Note.
- The engine qualname in `contract_symbols` assumes the class is
  `SddCoderEngine` — verify with `wikitoolkit symbols lookup _resolve_feature`
  and correct the symbol id before implementing if it differs.
- Tests: the sdd_coder test dir has a hermetic durable-root fixture
  (`conftest.py:28`, auto-memory "sdd-coder evidence store always-on") —
  don't fight it. Run with `PYTHONPATH=packages/ai-parrot/src` from the
  worktree root (shared venv is editable-installed against the main checkout).

---

## Implementation Blueprint

### Steps (in order)
1. Run the blast-radius check — *why*: `from_worktree` is shared by the pool, inspection and tests.
2. Add the helpers to task_scheduler.py and switch `from_worktree` — *why*: one rule, one place.
3. Delegate the four sdd_coder resolvers — *why*: removes every hardcoded `sdd/tasks/index` in the coder pipeline.
4. Write the tests — *why*: AC-1..AC-5.

### `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'PARALLEL_SEMANTICS_EXCLUSIVE = "exclusive"' task_scheduler.py)
# AFTER — insert below `PARALLEL_SEMANTICS_EXCLUSIVE = "exclusive"` (verified: task_scheduler.py:29)

#: Feature task indexes (FEAT-145) and brief indexes (FEAT-698), relative to a worktree.
TASK_INDEX_DIR = Path("sdd") / "tasks" / "index"
BRIEF_INDEX_DIR = Path("sdd") / "briefs"
BRIEF_INDEX_SUFFIX = ".index.json"
_ORPHANS_INDEX = "_orphans.json"


def resolve_index_path(worktree_path: str | Path, feature_slug: str) -> Path:
    """Locate a slug's index: feature index first, then brief index.

    Returns the ``sdd/tasks/index/<slug>.json`` path when neither exists, so
    callers keep today's not-found behavior.
    """
    root = Path(worktree_path)
    feature_index = root / TASK_INDEX_DIR / f"{feature_slug}.json"
    # FILL IN: return feature_index if it exists; else the brief index if it exists; else feature_index — AC-1/AC-2
    raise NotImplementedError


def iter_index_files(worktree_path: str | Path) -> List[Path]:
    """Every index under a worktree: sorted feature indexes (minus orphans), then sorted brief indexes."""
    # FILL IN: tolerate missing dirs (return []) — AC-3
    raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c 'index_path = Path(worktree_path) / "sdd" / "tasks" / "index" / f"{feature_slug}.json"' task_scheduler.py)
# REPLACE line 213 with:
        index_path = resolve_index_path(worktree_path, feature_slug)
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        index_dir = Path(wt) / "sdd" / "tasks" / "index"' engine.py)
# FILL IN: delete line 1496 and rewrite _read_headers (lines 1498-1510) to iterate
#          `iter_index_files(wt)` (no is_dir check, no orphans skip — the helper does both),
#          keeping the json/OSError tolerance; extend the engine.py:53 import with iter_index_files — AC-4
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return worktree / "sdd" / "tasks" / "index" / f"{feature}.json"' inspection.py)
# REPLACE line 105 with (and extend the line-55 import with resolve_index_path):
    return resolve_index_path(worktree, feature)
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return worktree / "sdd" / "tasks" / "index" / f"{feature}.json"' checkpoint.py)
# REPLACE line 188 with (and extend the line-67 import with resolve_index_path):
    return resolve_index_path(worktree, feature)
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_FEATURE_ID_RE = re.compile(r"^FEAT-\\d+$")' background.py)
# REPLACE line 70 with:
_FEATURE_ID_RE = re.compile(r"^(?:FEAT-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9._-]*)$")
# FILL IN: line 840 — iterate `iter_index_files(worktree)` instead of the sdd/tasks/index glob;
#          add `from parrot.flows.dev_loop.task_scheduler import iter_index_files`;
#          update the docstring + warning text to say "FEAT-<NNN>/BRIEF-<KEY>" — AC-5
```
**Why**: widening the regex (rather than adding a second one) keeps the
early-return `if _FEATURE_ID_RE.match(feature)` path working for a caller
that already passes `BRIEF-<KEY>`.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py` (CREATE)
```python
"""Brief-aware index discovery — FEAT-698 / TASK-4431."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files, resolve_index_path


def _write(path: Path, header: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(header), encoding="utf-8")
    return path


def _brief_header(slug: str = "demo-fix", key: str = "cs-224") -> dict:
    return {
        "feature": slug, "feature_id": f"BRIEF-{key}", "spec": f"sdd/briefs/{slug}.brief.md",
        "type": "brief", "base_branch": "main", "parallel_semantics": "exclusive",
        "tasks": [{"id": f"HOTFIX-{key}-1", "status": "pending", "depends_on": [],
                   "file": f"sdd/briefs/{slug}/tasks/HOTFIX-{key}-1-x.md"}],
    }

# FILL IN: test_resolves_brief_index_when_no_feature_index (AC-1)
# FILL IN: test_feature_index_wins_over_brief_index (AC-2)
# FILL IN: test_iter_index_files_order_and_orphans_skipped, test_iter_tolerates_missing_dirs (AC-3)
# FILL IN: test_from_worktree_loads_brief_scheduler — TaskScheduler.from_worktree(wt, slug) sees HOTFIX ids (AC-1)
# FILL IN: test_engine_resolve_feature_matches_brief_by_feature_id — follow test_engine_plan_merge.py's engine
#          construction pattern; assert ctx.index_path endswith "sdd/briefs/demo-fix.index.json" (AC-4)
# FILL IN: test_background_resolve_feature_id_returns_brief_id (AC-5)
```

### FILL IN checklist
- [ ] `resolve_index_path` / `iter_index_files` bodies — AC-1..AC-3
- [ ] engine `_read_headers` rewrite — AC-4
- [ ] background enumeration + docstring — AC-5
- [ ] tests AC-1..AC-5
- [ ] Completion Note: blast-radius caller list

---

## Acceptance Criteria

- [ ] AC-1: with only `sdd/briefs/<slug>.index.json` present, `resolve_index_path` returns it and `TaskScheduler.from_worktree` loads its `HOTFIX-*` tasks.
- [ ] AC-2: with both present, the `sdd/tasks/index/<slug>.json` path wins.
- [ ] AC-3: `iter_index_files` returns feature indexes (sorted, `_orphans.json` excluded) before brief indexes (sorted); `[]` when neither dir exists.
- [ ] AC-4: `engine._resolve_feature("BRIEF-cs-224", wt)` and `("demo-fix", wt)` both resolve to the brief index.
- [ ] AC-5: `background._resolve_feature_id(wt, "demo-fix")` returns `"BRIEF-cs-224"`.
- [ ] AC-6: no `"sdd" / "tasks" / "index"` literal remains in the five modified source files except `TASK_INDEX_DIR`.
- [ ] Existing suites pass: `test_task_scheduler.py`, `test_engine_plan_merge.py`, `test_inspection_reports.py`, `test_review_checkpoint.py`.
- [ ] `ruff check` clean on all modified files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_task_scheduler.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_inspection_reports.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4431 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
