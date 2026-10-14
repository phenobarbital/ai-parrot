# TASK-4314: wiki/transport.py — OperationDescriptor registry with schema fingerprints

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4306, TASK-4307, TASK-4308
**Assigned-to**: unassigned

---

## Context

Spec §3 M5 + codex S11. One deterministic registry of transport-neutral descriptors feeds both the framework tools and the SDK server.

---

## Scope

- Create `wiki/transport.py`: `OperationDescriptor` (name, description, input_model, schema_fingerprint, mount, invoke) and `build_operation_descriptors(bundle_inputs)` returning descriptors per mounted plane; duplicate names raise.
- `schema_fingerprint` = sha256 of the canonical (sorted-keys) JSON schema.
- Tests: determinism, duplicate detection, mounts follow configuration (ledger present/absent, schema plane present/absent, bulk on/off).

**NOT in scope**: Adapting descriptors to MCP SDK / framework tools (TASK-4315).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | CREATE | descriptors |
| `packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py` | CREATE | descriptor tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.operations import OperationResult  # TASK-4306
from parrot.knowledge.wiki.mcp_server import WikiToolBundle  # mcp_server.py:93 (TYPE_CHECKING only)
```

### Existing Signatures to Use
```python
# mcp_server.py: WikiToolBundle :93 (tools, vault_tools, description, store, read_store, ledger_service, namespace_handles); abuild_wiki_tools :105-320 (mount conditions)
```

### Does NOT Exist
- ~~`OperationDescriptor` / `build_operation_descriptors` (created here)~~
- ~~a fixed six-tool manifest~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/transport.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#WikiToolBundle",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#abuild_wiki_tools"
  ]
}
```

---

## Implementation Notes

Mount conditions must mirror `abuild_wiki_tools` exactly — read it and copy the conditions, don't invent new ones. Tool names/descriptions must equal today's tool names (`wiki_query`, `ledger_open`, ...).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Model + fingerprint — *why*: S11 golden comparability.
2. Builder mirroring abuild_wiki_tools mounts — *why*: configuration-dependent surface.
3. Tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` (CREATE)
```python
"""Transport-neutral wiki operation descriptors (FEAT-540 M5)."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.wiki.operations import OperationResult


class OperationDescriptor(BaseModel):
    """One wiki tool, independent of transport."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    schema_fingerprint: str
    mount: str
    invoke: Callable[[BaseModel], Awaitable[OperationResult]]


def schema_fingerprint(model: type[BaseModel]) -> str:
    """sha256 of the canonical JSON schema."""
    return hashlib.sha256(json.dumps(model.model_json_schema(), sort_keys=True).encode()).hexdigest()


def build_operation_descriptors(bundle_inputs: Any) -> list[OperationDescriptor]:
    """Descriptors for every mounted plane; raises ValueError on duplicate names."""
    # FILL IN: mirror abuild_wiki_tools mount conditions (core, structural, decisions, schema, ledger, bulk, vault-ingest)
    raise NotImplementedError
```
**Why**: `invoke` closes over store/context so transports only pass validated params.

### `packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py` (CREATE)
```python
"""Descriptor registry (FEAT-540 M5)."""
import pytest

# FILL IN: determinism (two builds equal by name+fingerprint), duplicate name -> ValueError, mounts per configuration
```
**Why**: Configuration matrix starts here; golden files land in TASK-4316.

### FILL IN checklist
- [ ] `build_operation_descriptors` with exact mounts
- [ ] tests

---

## Acceptance Criteria

- [ ] descriptor names equal the current tool names per configuration
- [ ] fingerprints stable across runs
- [ ] duplicates rejected

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4314 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
