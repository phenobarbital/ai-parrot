# TASK-4472: Governance composition and subject/provenance digest (M6d)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4470, TASK-4471
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M6; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement GovernancePipeline.govern(sql, *, model, ctx, roles) in fixed spec order on a parsed clone: negative validation, qualification, resource subset/PBAC, usage lineage, RLS, masking, positive guard, render.
- Compute subject_digest using canonical typed JSON of user/tenant/sorted roles and policy-relevant metadata; never rely on UserSession hash or repr ordering. Reject unsupported metadata rather than producing unstable identities.
- Populate GovernedQuery with exact semantic member dependency closure and qualified physical column/table lineage, never reverse-guess from output aliases. Resolve ambiguous semantic mappings conservatively.
- CPU AST work stays off the event loop; PBAC is awaited per request including cache hits. Inputs remain unchanged on failures and success.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_pipeline.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from ..loader import LoadedModel
from ..models import GovernedQuery
from .guard import PositiveGuard, effective_allowed_functions
from .lineage import resolve_column_uses, enforce_usage_rights
from .masking import apply_masks
from .pbac import PbacGate
from .rls import RlsPushdown
from __future__ import annotations
from parrot.auth import PermissionContext
from pathlib import Path
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/security/query_validator.py:29
class QueryValidator():
    # line 165
    def validate_sql_ast(cls, query: str, dialect: Optional[str]=None, read_only: bool=True, require_pk_in_where: bool=False, primary_keys: Optional[List[str]]=None) -> Dict[str, Any]:
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py:81
class PermissionContext():
```

### Dependency Contracts and Parallelism Evidence

- TASK-4470: consumes packages/ai-parrot-semantic/src/parrot/semantic/governance/rls.py (Request-local RLS below aggregation (M6b))
- TASK-4471: consumes packages/ai-parrot-semantic/src/parrot/semantic/governance/masking.py, packages/ai-parrot-semantic/src/parrot/semantic/governance/guard.py (Projection masks and positive SQL guard (M6c))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_pipeline.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/query_validator.py#QueryValidator",
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

### `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py` (CREATE)

```python
"""Fixed-order request-local governance with exact provenance."""
from __future__ import annotations
from parrot.auth import PermissionContext
from ..loader import LoadedModel
from ..models import GovernedQuery
from .pbac import PbacGate
from .rls import RlsPushdown
from .lineage import resolve_column_uses, enforce_usage_rights
from .masking import apply_masks
from .guard import PositiveGuard, effective_allowed_functions

def subject_digest(ctx: PermissionContext | None) -> str:
    """Hash canonical typed subject metadata, never the dataclass hash or repr."""
    # FILL IN: stable typed JSON, roles sorted; anonymous only for ungoverned calls.
    ...

class GovernancePipeline:
    """Authorize and rewrite a clone; never mutate reusable compilation output."""
    def __init__(self, *, pbac: PbacGate, rls: RlsPushdown,
                 allowed_functions: frozenset[str]) -> None:
        self.pbac = pbac
        self.rls = rls
        self.allowed_functions = allowed_functions
    async def govern(self, sql: str, *, model: LoadedModel,
                     ctx: PermissionContext | None, roles: frozenset[str]) -> GovernedQuery:
        """Validate, qualify, authorize, resolve lineage, push RLS, mask and cap."""
        # FILL IN: fixed order of M6, per-request schema/RLS binding and exact
        # members/physical_columns/tables. Caller performs precompile manifest gate.
        # Any unsupported lineage or resource mismatch denies before SQL escapes.
        ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_pipeline.py` (CREATE)

```python
"""Regression contract: Governance composition and subject/provenance digest (M6d)."""
from pathlib import Path
import pytest


def test_fixed_order_and_input_immutability(tmp_path: Path) -> None:
    """Verify fixed order and input immutability."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_typed_subject_digest_and_provenance(tmp_path: Path) -> None:
    """Verify typed subject digest and provenance."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_denials_never_return_partial_sql(tmp_path: Path) -> None:
    """Verify denials never return partial sql."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_pipeline.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement GovernancePipeline.govern(sql, *, model, ctx, roles) in fixed spec order on a parsed clone: negative validation, qualification, resource subset/PBAC, usage lineage, RLS, masking, positive guard, render.
- [ ] Compute subject_digest using canonical typed JSON of user/tenant/sorted roles and policy-relevant metadata; never rely on UserSession hash or repr ordering. Reject unsupported metadata rather than producing unstable identities.
- [ ] Populate GovernedQuery with exact semantic member dependency closure and qualified physical column/table lineage, never reverse-guess from output aliases. Resolve ambiguous semantic mappings conservatively.
- [ ] CPU AST work stays off the event loop; PBAC is awaited per request including cache hits. Inputs remain unchanged on failures and success.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_pipeline.py -q`

## Test Specification

- `test_fixed_order_and_input_immutability`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_typed_subject_digest_and_provenance`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_denials_never_return_partial_sql`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4472` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Seat: opus (native), 1 attempt. Dialect derived from driver; ctx None + RLS rules denied; RLS output re-qualified; members computed for root model only.
Engine fidelity gate clean; merge-tier validation green; orchestrator review approved.
