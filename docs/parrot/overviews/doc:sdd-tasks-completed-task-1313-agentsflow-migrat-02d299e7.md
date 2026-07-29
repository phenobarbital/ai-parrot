---
type: Wiki Overview
title: 'TASK-1313: parrot/flows/dev_loop/ consumer repointing (L5 — Module 6)'
id: doc:sdd-tasks-completed-task-1313-agentsflow-migration-devloop-repointing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 5 of the migration (external consumer repointing). The 8 files in
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
---

# TASK-1313: parrot/flows/dev_loop/ consumer repointing (L5 — Module 6)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1312
**Assigned-to**: unassigned

---

## Context

Layer 5 of the migration (external consumer repointing). The 8 files in
`parrot/flows/dev_loop/` import `AgentsFlow` and `Node` from the legacy
`parrot.bots.flow.*` paths. After TASK-1312, the canonical paths are in
`parrot.bots.flows.*`. This task updates all 8 files.

Implements §3 Module 6 of the spec.

---

## Scope

Update imports in these 8 files:

1. `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` (line 26):
   `from parrot.bots.flow import AgentsFlow`
   → `from parrot.bots.flows import AgentsFlow`

2. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` (line 21):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

3. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` (line 29):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

4. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` (line 19):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

5. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` (line 22):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

6. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py` (line 22):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

7. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (line 20):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

8. `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` (line 30):
   `from parrot.bots.flow.node import Node`
   → `from parrot.bots.flows.core.node import Node`

After updating all 8, verify that `grep -rn "parrot.bots.flow" packages/ai-parrot/src/parrot/flows/` returns zero matches.

Also update any docstring/comment references to old paths in these 8 files.

**NOT in scope**: test file updates (TASK-1314). Not modifying dev_loop logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Line ~26: `from parrot.bots.flows import AgentsFlow` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` | MODIFY | Line ~21: `from parrot.bots.flows.core.node import Node` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | Line ~29: same |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | Line ~19: same |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | MODIFY | Line ~22: same |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py` | MODIFY | Line ~22: same |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Line ~20: same |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | Line ~30: same |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Canonical paths after migration:
from parrot.bots.flows import AgentsFlow
# verified: parrot/bots/flows/__init__.py re-exports AgentsFlow

from parrot.bots.flows.core.node import Node
# verified: parrot/bots/flows/core/node.py:68
```

### Existing Signatures to Use

```python
# parrot/bots/flows/core/node.py:68
class Node(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node_id: str
    # NOTE: Frozen Pydantic — subclasses in dev_loop must respect this
```

### Does NOT Exist

- ~~`parrot.bots.flow.node.Node`~~ after this task's changes take effect
- ~~`parrot.bots.flow.AgentsFlow`~~ (via __getattr__) — still exists until TASK-1316
  but must not be used in dev_loop after this task

---

## Implementation Notes

### Key Constraints

- Read each file before editing to verify the exact line number and surrounding context
- Some files may have additional `parrot.bots.flow.*` references in docstrings —
  update those too (change to `parrot.bots.flows.*`)
- Verify exact line numbers before editing — the spec lists approximate lines;
  actual lines may differ
- After all 8 edits: `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/src/parrot/flows/`
  must return zero matches

### References in Codebase

- Exact 8 files listed in §6 of spec (Codebase Contract → dev_loop consumers)

---

## Acceptance Criteria

- [ ] All 8 files modified with updated imports
- [ ] `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/src/parrot/flows/` returns zero matches
- [ ] `from parrot.flows.dev_loop.flow import *` (or equivalent import check) succeeds without `parrot.bots.flow` errors
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/`

---

## Test Specification

```python
# Inline acceptance — no new test file needed.
# Verify via import smoke tests:

def test_devloop_flow_imports_canonical_agentsflow():
    import pathlib  # noqa: PLC0415
    src = pathlib.Path(
        "packages/ai-parrot/src/parrot/flows/dev_loop/flow.py"
    ).read_text()
    assert "parrot.bots.flow " not in src
    assert "parrot.bots.flows" in src


def test_devloop_nodes_import_canonical_node():
    import pathlib  # noqa: PLC0415
    nodes_dir = pathlib.Path("packages/ai-parrot/src/parrot/flows/dev_loop/nodes")
    for py_file in nodes_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        src = py_file.read_text()
        assert "parrot.bots.flow.node" not in src, \
            f"Legacy import found in {py_file.name}"
```

Add these to `packages/ai-parrot/tests/bots/flows/test_move_only_imports.py` or
a new `tests/flows/dev_loop/test_repointing.py`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1312 must be in `sdd/tasks/completed/`
3. **Read each of the 8 files** before editing to confirm line numbers and context
4. **Implement** the import updates
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-28
**Notes**: Updated all 8 dev_loop files with sed replacements. Also fixed docstring references
in dev_loop/flow.py that pointed to old paths. All 6 repointing tests pass.

**Deviations from spec**: none
