# TASK-4707: Scoped identity binding and exception-safe cleanup (M10 context)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M10; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Extend context.py after its M2 identity class with current_pctx/current_identity and bind_semantic_context(ctx, identity=None) async context manager.
- Validate trusted identity/context equivalence, comparing copied metadata as well as user/tenant/roles. Bind satellite context and core _pctx_var; keep tokens local and reset in finally on normal/error/cancellation paths.
- Context-only authenticated calls are allowed without retention; require_identity raises for handles when no complete identity is bound. Never derive agent/session from caller parameters or request_id.
- Test concurrent two-subject calls, nesting, failures and cancellation. No core hooks or PermissionContext fields change.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/context.py` | MODIFY | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_context.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticAccessError, SemanticResultError
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from parrot.auth.context import _pctx_var
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

```python
# packages/ai-parrot/src/parrot/auth/context.py:33
_pctx_var: contextvars.ContextVar[PermissionContext | None]
```

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: SemanticRequestIdentity in context.py; serializes the M2 CREATE with this MODIFY

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_context.py",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/context.py` (MODIFY)

Dependency-created anchor `class SemanticRequestIdentity` — expected occurrences: **1** in the producer blueprint. It is absent on dev; re-read its actual line/count after the producer lands, before any edit.

```python
# AFTER dependency-created SemanticRequestIdentity (expected occurrences: 1).
# Re-read and preserve its complete M2 model; add these binding helpers.
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections.abc import AsyncIterator
from parrot.auth.context import _pctx_var
from .errors import SemanticAccessError, SemanticResultError

_semantic_pctx_var: ContextVar[PermissionContext | None] = ContextVar("semantic_pctx", default=None)
_identity_var: ContextVar[SemanticRequestIdentity | None] = ContextVar("semantic_identity", default=None)

def current_pctx() -> PermissionContext | None:
    """Return the current trusted permission context."""
    return _semantic_pctx_var.get()

def current_identity() -> SemanticRequestIdentity | None:
    """Return the complete retention identity, if bound."""
    return _identity_var.get()

def require_identity() -> SemanticRequestIdentity:
    """Deny retention/handoff when no complete trusted scope is bound."""
    # FILL IN: return or SemanticResultError; AC25.
    ...

@asynccontextmanager
async def bind_semantic_context(ctx: PermissionContext, *,
                                identity: SemanticRequestIdentity | None = None) -> AsyncIterator[None]:
    """Bind copied context and identity; restore all tokens in finally."""
    # FILL IN: compare canonical trusted attributes, set tokens locally, yield,
    # reset identity/core/satellite context in reverse order even on cancellation.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_context.py` (CREATE)

```python
"""Regression contract: Scoped identity binding and exception-safe cleanup (M10 context)."""
from pathlib import Path
import pytest


def test_trusted_scope_and_context_only_calls(tmp_path: Path) -> None:
    """Verify trusted scope and context only calls."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_concurrent_nested_isolation(tmp_path: Path) -> None:
    """Verify concurrent nested isolation."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_error_cancellation_and_token_reset(tmp_path: Path) -> None:
    """Verify error cancellation and token reset."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/context.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_context.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Extend context.py after its M2 identity class with current_pctx/current_identity and bind_semantic_context(ctx, identity=None) async context manager.
- [ ] Validate trusted identity/context equivalence, comparing copied metadata as well as user/tenant/roles. Bind satellite context and core _pctx_var; keep tokens local and reset in finally on normal/error/cancellation paths.
- [ ] Context-only authenticated calls are allowed without retention; require_identity raises for handles when no complete identity is bound. Never derive agent/session from caller parameters or request_id.
- [ ] Test concurrent two-subject calls, nesting, failures and cancellation. No core hooks or PermissionContext fields change.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_context.py -q`

## Test Specification

- `test_trusted_scope_and_context_only_calls`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_concurrent_nested_isolation`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_error_cancellation_and_token_reset`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4707` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
