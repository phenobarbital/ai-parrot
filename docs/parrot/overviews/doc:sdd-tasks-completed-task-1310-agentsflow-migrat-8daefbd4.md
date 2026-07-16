---
type: Wiki Overview
title: 'TASK-1310: Storage reconciliation — L2 (Module 3)'
id: doc:sdd-tasks-completed-task-1310-agentsflow-migration-storage-reconciliation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 2 of the migration. The legacy `parrot/bots/flow/storage/` contains
  three
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.mixin
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: mentions
---

# TASK-1310: Storage reconciliation — L2 (Module 3)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1308, TASK-1309
**Assigned-to**: unassigned

---

## Context

Layer 2 of the migration. The legacy `parrot/bots/flow/storage/` contains three
files — `memory.py`, `mixin.py`, `synthesis.py` — that are older duplicates of
the canonical `parrot/bots/flows/core/storage/` equivalents. Before deleting them,
we must behavioural-diff the two sets and port any missing semantics into the
canonical files.

Implements §3 Module 3 of the spec.

---

## Scope

1. **Diff** `parrot/bots/flow/storage/memory.py` against
   `parrot/bots/flows/core/storage/memory.py` — identify any behaviour in the
   old `ExecutionMemory` that is missing from the canonical one. Port missing
   semantics (with tests) into the canonical file.

2. **Diff** `parrot/bots/flow/storage/mixin.py` against
   `parrot/bots/flows/core/storage/mixin.py` — same process.

3. **Diff** `parrot/bots/flow/storage/synthesis.py` against
   `parrot/bots/flows/core/storage/synthesis.py` — same process.

4. **Repoint any stragglers** in the test suite that still import from
   `parrot.bots.flow.storage.*`:
   - `packages/ai-parrot/tests/test_orchestrator_agent.py`
   - `packages/ai-parrot/tests/test_execution_memory_integration.py`
   - Any other files discovered by `grep -rn "parrot.bots.flow.storage"`.

5. **Do NOT delete** `parrot/bots/flow/storage/` here — that happens in TASK-1316.

6. Write or update `test_storage_behavioural_parity` test.

**NOT in scope**: modifying `parrot/bots/flows/core/storage/persistence.py`
(already canonical from FEAT-147). Not modifying decision nodes or actions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py` | MODIFY (if gaps found) | Port any missing semantics from old memory.py |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/mixin.py` | MODIFY (if gaps found) | Port any missing semantics from old mixin.py |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/synthesis.py` | MODIFY (if gaps found) | Port any missing semantics from old synthesis.py |
| `packages/ai-parrot/tests/test_orchestrator_agent.py` | MODIFY | Repoint `parrot.bots.flow.storage.*` → `parrot.bots.flows.core.storage.*` |
| `packages/ai-parrot/tests/test_execution_memory_integration.py` | MODIFY | Repoint `parrot.bots.flow.storage.*` → `parrot.bots.flows.core.storage.*` |
| `packages/ai-parrot/tests/test_flow_mixins.py` | MODIFY | Repoint imports |
| `packages/ai-parrot/tests/bots/flows/test_storage_parity.py` | CREATE | Behavioural-parity test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Canonical storage (already exists — target for ports):
from parrot.bots.flows.core.storage import (
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)
# verified: parrot/bots/flows/core/storage/__init__.py

from parrot.bots.flows.core.storage.memory import ExecutionMemory
# verified: parrot/bots/flows/core/storage/memory.py

from parrot.bots.flows.core.storage.mixin import VectorStoreMixin
# verified: parrot/bots/flows/core/storage/mixin.py

from parrot.bots.flows.core.storage.synthesis import SynthesisMixin, synthesize_results
# verified: parrot/bots/flows/core/storage/synthesis.py

# Legacy storage (source for diff — do NOT export from new paths):
# packages/ai-parrot/src/parrot/bots/flow/storage/memory.py    102 LoC
# packages/ai-parrot/src/parrot/bots/flow/storage/mixin.py     141 LoC
# packages/ai-parrot/src/parrot/bots/flow/storage/synthesis.py 108 LoC

# Result model used by storage:
from parrot.bots.flows.core.result import NodeResult, FlowResult, NodeExecutionInfo
# verified: parrot/bots/flows/core/result.py:39, 190, 273
```

### Existing Signatures to Use

```python
# parrot/bots/flows/core/storage/memory.py (canonical — read before modifying)
class ExecutionMemory: ...   # read file for current signatures

# parrot/bots/flows/core/storage/mixin.py (canonical)
class VectorStoreMixin: ...  # read file for current signatures

# parrot/bots/flows/core/storage/synthesis.py (canonical)
class SynthesisMixin: ...    # read file for current signatures
```

### Does NOT Exist

- ~~`parrot.bots.flow.storage.persistence`~~ — deleted in FEAT-147
- ~~`parrot.bots.flow.fsm`~~ — deleted in FEAT-163

---

## Implementation Notes

### Pattern to Follow

The behavioural diff process:

1. Read old file in full
2. Read canonical file in full
3. Identify methods/attributes in old that are NOT in canonical
4. For each gap: decide if it's genuinely useful (port) or was superseded (discard)
5. If porting: add the method/attribute to the canonical file with a docstring
   explaining it was ported from the legacy file
6. Write a test that exercises the ported behaviour against the canonical class

### Key Constraints

- The canonical `flows/core/storage/` wins on all conflicts
- Port only genuinely missing behaviour; do not regress canonical behaviour
- After this task, NO import of `parrot.bots.flow.storage.*` should remain in
  test files (except in the legacy files themselves, which are deleted in TASK-1316)
- Use `NodeResult` / `FlowResult` (not old `AgentResult` if that existed in old code)

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flow/storage/` — source for diff
- `packages/ai-parrot/src/parrot/bots/flows/core/storage/` — canonical target

---

## Acceptance Criteria

- [ ] `grep -rn "parrot.bots.flow.storage" packages/ai-parrot/tests/` returns zero matches
- [ ] `from parrot.bots.flows.core.storage import ExecutionMemory, VectorStoreMixin, SynthesisMixin` succeeds
- [ ] `test_storage_behavioural_parity` passes — any ported semantics verified
- [ ] Existing core storage tests still pass: `pytest packages/ai-parrot/tests/bots/flows/core/storage/ -v`
- [ ] `pytest packages/ai-parrot/tests/test_orchestrator_agent.py -v`
- [ ] `pytest packages/ai-parrot/tests/test_execution_memory_integration.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/core/storage/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_storage_parity.py
import pytest
from parrot.bots.flows.core.storage import ExecutionMemory, VectorStoreMixin, SynthesisMixin


class TestStorageBehaviouralParity:
    """Verify canonical storage has all semantics from the legacy layer."""

    def test_execution_memory_has_add_result(self):
        """ExecutionMemory.add_result (or equivalent) exists and works."""
        mem = ExecutionMemory()
        # Add a result and verify it's stored
        # Adjust method name to match canonical API
        assert hasattr(mem, 'add_result') or hasattr(mem, 'store_result') or hasattr(mem, 'add')

    def test_vector_store_mixin_interface(self):
        """VectorStoreMixin exposes the expected interface."""
        # Check key methods exist
        assert hasattr(VectorStoreMixin, 'index_results') or \
               hasattr(VectorStoreMixin, 'search') or \
               hasattr(VectorStoreMixin, 'similarity_search')

    def test_synthesis_mixin_interface(self):
        """SynthesisMixin exposes synthesis method."""
        assert hasattr(SynthesisMixin, 'synthesize') or \
               hasattr(SynthesisMixin, 'synthesize_results')

    def test_no_legacy_storage_import_in_test_orchestrator(self):
        import pathlib  # noqa: PLC0415
        src = pathlib.Path(
            "packages/ai-parrot/tests/test_orchestrator_agent.py"
        ).read_text()
        assert "parrot.bots.flow.storage" not in src

    def test_no_legacy_storage_import_in_test_execution_memory(self):
        import pathlib  # noqa: PLC0415
        src = pathlib.Path(
            "packages/ai-parrot/tests/test_execution_memory_integration.py"
        ).read_text()
        assert "parrot.bots.flow.storage" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1308 and TASK-1309 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read both sets of storage files before making changes
4. **Run the diff** — read old and canonical files carefully before deciding what to port
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
