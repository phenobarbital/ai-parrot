# TASK-4476: Scoped result handles and exact retained provenance (M9b)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M9; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement ResultHandle and ResultHandleStore per rev 0.4: nonempty user/tenant/agent/session identity, exact semantic members, qualified physical columns/tables, expiry, digests and audit id.
- claim(result_id, *, identity, subject_digest, model_digest, policy_digest) checks every scope component, expiry and versions. Never substitute null/session defaults or request_id.
- Return defensive snapshots, bound retention by count/TTL and opaque random ids. Alias names are output metadata only, never authorization provenance.
- Test same user across agents/sessions, changed roles/metadata, foreign/expired/stale handles and mutation of returned row objects.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/results.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_results.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .context import SemanticRequestIdentity
from .errors import SemanticResultError
from __future__ import annotations
from datetime import datetime
from parrot.auth import PermissionContext
from pathlib import Path
from pydantic import BaseModel
from typing import Any
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: SemanticRequestIdentity and SemanticResultError for owner-bound claims

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/results.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_results.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext"
  ]
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `packages/ai-parrot-semantic/src/parrot/semantic/results.py` (CREATE)

```python
"""Bounded expiring handles with immutable ownership and authorization provenance."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel
from parrot.auth import PermissionContext
from .context import SemanticRequestIdentity
from .errors import SemanticResultError

class ResultHandle(BaseModel):
    """A defensive retained result, never a grant by itself."""
    result_id: str
    agent_id: str
    user_id: str
    tenant_id: str
    session_id: str
    subject_digest: str
    model: str
    model_digest: str
    policy_digest: str
    expires_at: datetime
    members: tuple[str, ...]
    physical_columns: tuple[str, ...]
    physical_tables: tuple[str, ...]
    columns: list[str]
    rows: list[dict[str, Any]]
    audit_id: str
    governed_sql: str
    # FILL IN: strict nonempty identifiers and copied provenance/rows; AC25.

class ResultHandleStore:
    """Opaque TTL store with complete owner and version checks."""
    def __init__(self, *, ttl_s: int = 900, max_entries: int = 256) -> None:
        # FILL IN: bounded private store and injectable clock for deterministic tests.
        ...
    def put(self, handle: ResultHandle) -> str:
        """Store a defensive snapshot under a random opaque id."""
        ...
    def claim(self, result_id: str, *, identity: SemanticRequestIdentity,
              subject_digest: str, model_digest: str, policy_digest: str) -> ResultHandle:
        """Return a snapshot only for exact current owner, context and versions."""
        # FILL IN: all ownership/expiry checks; no wildcard null fields.
        ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_results.py` (CREATE)

```python
"""Regression contract: Scoped result handles and exact retained provenance (M9b)."""
from pathlib import Path
import pytest


def test_same_user_distinct_sessions_and_agents(tmp_path: Path) -> None:
    """Verify same user distinct sessions and agents."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_expiry_context_policy_and_provenance(tmp_path: Path) -> None:
    """Verify expiry context policy and provenance."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_defensive_copy_and_bounded_store(tmp_path: Path) -> None:
    """Verify defensive copy and bounded store."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/results.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_results.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement ResultHandle and ResultHandleStore per rev 0.4: nonempty user/tenant/agent/session identity, exact semantic members, qualified physical columns/tables, expiry, digests and audit id.
- [ ] claim(result_id, *, identity, subject_digest, model_digest, policy_digest) checks every scope component, expiry and versions. Never substitute null/session defaults or request_id.
- [ ] Return defensive snapshots, bound retention by count/TTL and opaque random ids. Alias names are output metadata only, never authorization provenance.
- [ ] Test same user across agents/sessions, changed roles/metadata, foreign/expired/stale handles and mutation of returned row objects.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_results.py -q`

## Test Specification

- `test_same_user_distinct_sessions_and_agents`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_expiry_context_policy_and_provenance`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_defensive_copy_and_bounded_store`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4476` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: gpt-5.6-terra (codex), 1 attempt, 71s.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
