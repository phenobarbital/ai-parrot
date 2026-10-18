# TASK-4438: Integration tests — brief scaffold and sdd-coder checkpoint over a brief index

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4425, TASK-4427, TASK-4431
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. Unit tests prove each piece; these prove the
seams: (1) the scripts layer can scaffold a complete brief in a real git
worktree — `BriefMeta` → `ensure_worktree --brief-key` → brief + task file
+ index → `check_task_graph` clean; (2) the sdd-coder pipeline accepts that
index end to end — engine resolution and checkpoint header validation with
`feature_id: "BRIEF-<KEY>"` (S2).

---

## Scope

- `tests/sdd_scripts/test_brief_scaffold_integration.py`: in a temp clone
  with `origin` (reuse the `tmp_git_repo` shape from
  `test_ensure_worktree.py` — copy the fixture locally, don't import a test
  module), run `main(["--slug", …, "--brief-key", …, "--base-branch", "dev",
  "--json"])`, write the brief via `emit_brief_frontmatter` + template body,
  one task file, `write_brief_index`; assert: no upstream on the branch,
  `parse_brief` round-trips, `python -m scripts.sdd.check_task_graph <index>`
  exits 0.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_checkpoint.py`:
  build a brief index in a temp worktree; assert
  `checkpoint._load_index_sync(wt, slug)` reads it and the header passes the
  non-empty `feature_id`/`base_branch`/`spec` check; assert
  `TaskScheduler.from_worktree(wt, slug)` yields the `HOTFIX-*` tasks.

**NOT in scope**: any source change — if a seam fails, record it in the
Completion Note and mark the task `done-with-issues`; do not patch other
tasks' files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_brief_scaffold_integration.py` | CREATE | scripts-layer seam |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_checkpoint.py` | CREATE | coder-pipeline seam |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.ensure_worktree import main                                       # verified: ensure_worktree.py:225
from scripts.sdd.brief_meta import BriefMeta, emit_brief_frontmatter, parse_brief, write_brief_index  # TASK-4425
from parrot.flows.dev_loop.task_scheduler import TaskScheduler                     # verified: task_scheduler.py:129
from parrot.flows.dev_loop.sdd_coder import checkpoint                             # module: sdd_coder/checkpoint.py
```

### Existing Signatures to Use
```python
# sdd_coder/checkpoint.py
def _load_index_sync(worktree: Path, feature: str) -> Tuple[Path, bytes, dict]   # line 191 (delegates to resolve_index_path after TASK-4431)
# header requirement: feature_id, base_branch, spec all non-empty                  # lines 462-466
# tests/sdd_scripts/test_ensure_worktree.py::tmp_git_repo                          # lines 18-53 (copy, don't import)
# sdd_coder/conftest.py::_hermetic_durable_root (autouse)                          # line 28
```
- `python -m scripts.sdd.check_task_graph <index.json>` — exit 1 on errors (used by `/sdd-task` §4b).

### Does NOT Exist
- ~~a public `load_index` in checkpoint.py~~ — `_load_index_sync` is private; testing it directly is acceptable here (it is the exact seam S2 names).
- ~~`prepare_review_checkpoint` without a settled execution~~ — it needs a durable settlement; do NOT call it, test the header seam only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/sdd_scripts/test_brief_scaffold_integration.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_checkpoint.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/ensure_worktree.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py#_load_index_sync",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_worktree"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the scripts-layer test — *why*: proves `/sdd-brief`'s mechanical steps compose.
2. Write the coder-pipeline test — *why*: proves S2 + TASK-4431 hold together.
3. Run both — *why*: AC-1/AC-2.

### `tests/sdd_scripts/test_brief_scaffold_integration.py` (CREATE)
```python
"""End-to-end brief scaffold in a real worktree — FEAT-698 / TASK-4438."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.sdd.brief_meta import BriefMeta, emit_brief_frontmatter, parse_brief, write_brief_index
from scripts.sdd.ensure_worktree import main

# FILL IN: local tmp_git_repo fixture (copy of test_ensure_worktree.py:18-53)
# FILL IN: test_brief_scaffold_round_trip — AC-1 (worktree, no upstream, parse_brief, check_task_graph rc 0
#          via subprocess.run([sys.executable, "-m", "scripts.sdd.check_task_graph", str(index)], cwd=<repo root>))
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_checkpoint.py` (CREATE)
```python
"""sdd-coder checkpoint + scheduler accept a BRIEF-<KEY> index — FEAT-698 / TASK-4438."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder import checkpoint
from parrot.flows.dev_loop.task_scheduler import TaskScheduler

# FILL IN: test_checkpoint_reads_brief_index_header — AC-2
# FILL IN: test_scheduler_from_worktree_sees_hotfix_tasks — AC-2
```

### FILL IN checklist
- [ ] local fixture + scaffold test — AC-1
- [ ] checkpoint + scheduler tests — AC-2

---

## Acceptance Criteria

- [ ] AC-1: the scaffold test creates a `fix-<KEY>-<slug>` worktree with no upstream, writes a brief that `parse_brief` accepts, and `check_task_graph` exits 0 on its index.
- [ ] AC-2: `_load_index_sync` returns the brief index with non-empty `feature_id` (`BRIEF-…`), `base_branch`, `spec`; `TaskScheduler.from_worktree` lists the `HOTFIX-*` tasks.
- [ ] AC-3: no source file is modified by this task.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_brief_scaffold_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_checkpoint.py -q`

---

## Test Specification

See the CREATE blocks above.

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
7. **Verify** all acceptance criteria — run the Validation Commands (`PYTHONPATH=packages/ai-parrot/src` for the package test)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4438 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
