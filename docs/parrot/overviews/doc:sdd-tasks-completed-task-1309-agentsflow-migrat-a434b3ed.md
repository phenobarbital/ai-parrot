---
type: Wiki Overview
title: 'TASK-1309: Move-only relocations — 5 files (L1 — Module 2)'
id: doc:sdd-tasks-completed-task-1309-agentsflow-migration-move-only-files-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 1 of the migration (continued). After TASK-1308 converts `flows/flow.py`
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.persistence
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.actions
  rel: mentions
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: mentions
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.loader
  rel: mentions
- concept: mod:parrot.bots.flows.flow.svelteflow
  rel: mentions
---

# TASK-1309: Move-only relocations — 5 files (L1 — Module 2)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1308
**Assigned-to**: unassigned

---

## Context

Layer 1 of the migration (continued). After TASK-1308 converts `flows/flow.py`
into the `flows/flow/` subpackage, this task moves the five self-contained
primitive files from `parrot/bots/flow/` (singular) into the new
`parrot/bots/flows/flow/` subpackage.

These are "move-only" files — no behavioural changes. Internal imports inside
each moved file are updated from `parrot.bots.flow.*` siblings to relative
imports or `parrot.bots.flows.core.*` paths where applicable.

Implements §3 Module 2 of the spec.

---

## Scope

Move (with import updates) these 5 files from `parrot/bots/flow/` → `parrot/bots/flows/flow/`:

1. `actions.py` — `ACTION_REGISTRY`, `BaseAction`, `LogAction`, `NotifyAction`,
   `WebhookAction`, `MetricAction`, `SetContextAction`, `ValidateAction`,
   `TransformAction`, `register_action`, `create_action`
2. `cel_evaluator.py` — `CELPredicateEvaluator`
3. `definition.py` — `FlowDefinition`, `FlowMetadata`, `NodeDefinition`,
   `NodePosition`, `EdgeDefinition`, `ActionDefinition`, and all `*ActionDef` types
4. `loader.py` — `FlowLoader`, `REDIS_KEY_PREFIX`
5. `svelteflow.py` — `from_svelteflow`, `to_svelteflow`

For each moved file:
- Copy content to `packages/ai-parrot/src/parrot/bots/flows/flow/<filename>.py`
- Update internal imports: replace `from parrot.bots.flow.X import Y` with
  `from .X import Y` (relative) or `from parrot.bots.flows.core.X import Y`
  where the target has already moved to `flows/core/`
- Do NOT delete the originals yet — they are removed in TASK-1316 (Module 9)
- Update `parrot/bots/flows/flow/__init__.py` to re-export symbols needed by the
  `flows/flow/flow.py` AgentsFlow class from these new locations

**NOT in scope**: changing `decision_node.py`, `interactive_node.py`,
`node.py`, `storage/`, or `tools.py`. Not updating external consumers (L4/L5
tasks cover that). Not deleting originals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/actions.py` | CREATE | Copy + import-update of `bots/flow/actions.py` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/cel_evaluator.py` | CREATE | Copy + import-update of `bots/flow/cel_evaluator.py` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` | CREATE | Copy + import-update of `bots/flow/definition.py` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/loader.py` | CREATE | Copy + import-update of `bots/flow/loader.py` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/svelteflow.py` | CREATE | Copy + import-update of `bots/flow/svelteflow.py` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py` | MODIFY | Add re-exports for moved symbols used by flow.py |
| `packages/ai-parrot/tests/bots/flows/test_move_only_imports.py` | CREATE | Import tests for all 5 moved files |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Source files to copy:
# packages/ai-parrot/src/parrot/bots/flow/actions.py       552 LoC
# packages/ai-parrot/src/parrot/bots/flow/cel_evaluator.py  140 LoC
# packages/ai-parrot/src/parrot/bots/flow/definition.py     433 LoC
# packages/ai-parrot/src/parrot/bots/flow/loader.py         364 LoC
# packages/ai-parrot/src/parrot/bots/flow/svelteflow.py     192 LoC

# Canonical core imports to use in updated files (replace old sibling imports):
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
# verified: parrot/bots/flows/core/node.py:68, 182, 323, 387

from parrot.bots.flows.core.context import FlowContext
# verified: parrot/bots/flows/core/context.py:51

from parrot.bots.flows.core.transition import FlowTransition
# verified: parrot/bots/flows/core/transition.py:28
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py (post-TASK-1308)
# This file re-exports: AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent
# After TASK-1309, it should ALSO re-export symbols needed externally, e.g.:
# FlowDefinition, NodeDefinition, EdgeDefinition, ACTION_REGISTRY, etc.
# (Only what parrot/bots/flows/__init__.py currently pulls from .flow)
```

### Does NOT Exist

- ~~`parrot.bots.flows.flow.actions`~~ before this task runs
- ~~`parrot.bots.flows.flow.definition`~~ before this task runs
- ~~`parrot.bots.flow.fsm`~~ — deleted in FEAT-163; do not import from it
- ~~`parrot.bots.flow.storage.persistence`~~ — deleted in FEAT-147; use
  `parrot.bots.flows.core.storage.persistence`

---

## Implementation Notes

### Pattern to Follow

For each moved file, the import update pattern is:

```python
# OLD (in bots/flow/actions.py):
from .definition import FlowDefinition, ActionDefinition  # relative within flow/
from parrot.bots.flow.node import Node                     # old node — now canonical

# NEW (in bots/flows/flow/actions.py):
from .definition import FlowDefinition, ActionDefinition  # relative within flows/flow/
from parrot.bots.flows.core.node import Node               # canonical node
```

For `cel_evaluator.py`:
```python
# OLD imports (check file for actuals):
from parrot.bots.flows.core.transition import FlowTransition  # may already be canonical

# NEW: keep canonical paths, update any remaining bots.flow.* refs
```

For `loader.py`:
```python
# Likely imports FlowDefinition — update to: from .definition import FlowDefinition
```

### Key Constraints

- Relative imports (`from .X import Y`) are preferred inside `flows/flow/`
- Do NOT delete originals in `parrot/bots/flow/` — removal is TASK-1316
- Do NOT change the public symbol names or function signatures
- Check each file for `from parrot.bots.flow.node import Node` and replace with
  `from parrot.bots.flows.core.node import Node`
- The `flows/flow/__init__.py` must re-export `FlowDefinition`, `NodeDefinition`,
  `EdgeDefinition` (and others) so `flows/__init__.py` still resolves the `from .flow
  import ...` calls for any curated symbols

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flow/actions.py` — source
- `packages/ai-parrot/src/parrot/bots/flow/cel_evaluator.py` — source
- `packages/ai-parrot/src/parrot/bots/flow/definition.py` — source
- `packages/ai-parrot/src/parrot/bots/flow/loader.py` — source
- `packages/ai-parrot/src/parrot/bots/flow/svelteflow.py` — source

---

## Acceptance Criteria

- [ ] All 5 files exist in `parrot/bots/flows/flow/`
- [ ] `from parrot.bots.flows.flow.actions import ACTION_REGISTRY, BaseAction, register_action` succeeds
- [ ] `from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator` succeeds
- [ ] `from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition` succeeds
- [ ] `from parrot.bots.flows.flow.loader import FlowLoader` succeeds
- [ ] `from parrot.bots.flows.flow.svelteflow import from_svelteflow, to_svelteflow` succeeds
- [ ] No import in the 5 new files references `parrot.bots.flow.node` (old Node)
- [ ] `pytest packages/ai-parrot/tests/bots/flows/test_move_only_imports.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/flow/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_move_only_imports.py
import pytest


def test_actions_import():
    from parrot.bots.flows.flow.actions import (  # noqa: PLC0415
        ACTION_REGISTRY, BaseAction, register_action, create_action,
        LogAction, NotifyAction, WebhookAction,
    )
    assert isinstance(ACTION_REGISTRY, dict)
    assert callable(register_action)


def test_cel_evaluator_import():
    from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator  # noqa: PLC0415
    assert CELPredicateEvaluator is not None


def test_definition_import():
    from parrot.bots.flows.flow.definition import (  # noqa: PLC0415
        FlowDefinition, NodeDefinition, EdgeDefinition,
        FlowMetadata, ActionDefinition,
    )
    assert FlowDefinition is not None
    assert NodeDefinition is not None


def test_loader_import():
    from parrot.bots.flows.flow.loader import FlowLoader, REDIS_KEY_PREFIX  # noqa: PLC0415
    assert FlowLoader is not None


def test_svelteflow_import():
    from parrot.bots.flows.flow.svelteflow import from_svelteflow, to_svelteflow  # noqa: PLC0415
    assert callable(from_svelteflow)
    assert callable(to_svelteflow)


def test_no_legacy_node_import_in_actions():
    """Moved actions.py must not import from parrot.bots.flow.node."""
    import importlib.util, pathlib  # noqa: PLC0415
    src = pathlib.Path(
        "packages/ai-parrot/src/parrot/bots/flows/flow/actions.py"
    ).read_text()
    assert "parrot.bots.flow.node" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1308 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the 5 source files to understand their imports
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
