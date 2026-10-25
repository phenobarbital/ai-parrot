# TASK-4473: Authorized catalog and saved-query expansion (M7)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4467
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M7; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Implement RoleCatalog visible_members/check_query_rights/expand_saved_query/search. Require authorized subject before catalog exposure; filter denied models instead of failing the entire multi-model listing.
- Check every selected/filter/order/time member plus derived dependencies; suggestions must come only from allowed members. Preserve projected masking rules.
- Expand a saved query into the same model before rights validation; unknown name denies clearly. No hidden member names or descriptions in search/suggestions.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_catalog.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticAccessError, SemanticValidationError
from .loader import LoadedModel
from .models import ModelMember, SemanticQuery
from __future__ import annotations
from pathlib import Path
import difflib
import logging
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4467: consumes packages/ai-parrot-semantic/src/parrot/semantic/loader.py (Clean-room model loader, graph scoping and fixtures (M4b))

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/catalog.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_catalog.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
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

### `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` (CREATE)

```python
"""Role-filtered catalog, member-right checks and saved-query expansion (spec §3 Module 7)."""
from __future__ import annotations

import difflib
import logging

from .errors import SemanticAccessError, SemanticValidationError
from .loader import LoadedModel
from .models import ModelMember, SemanticQuery


class RoleCatalog:
    def __init__(self, models: dict[str, LoadedModel]) -> None:
        self.models = models
        self.logger = logging.getLogger(__name__)

    def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[ModelMember]:
        """Allowed members only; a governed model with authorized=False exposes nothing (not even names)."""
        # FILL IN: ungoverned -> all members; governed and not authorized -> []; else filter by
        #          policy.allowed_members(roles, members); hide members whose mask hides them from projection
        raise NotImplementedError

    def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None:
        """Every metric/dimension/time-dimension/filter/order member must be allowed."""
        # FILL IN: collect referenced names (walk FilterGroup recursively); first disallowed ->
        #   SemanticAccessError("member_not_granted", details={"member": n, "suggestions": self._suggest(...)})
        raise NotImplementedError

    def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery:
        """Replace `saved_query` with the stored query (same model); unknown name -> SemanticValidationError."""
        # FILL IN: copy limit/offset overrides from the request onto the stored query only if set
        raise NotImplementedError

    def search(self, text: str, roles: frozenset[str], model: str | None = None, *,
               authorized: dict[str, bool] | None = None) -> list[dict]:
        """Case-insensitive substring + difflib ranking over visible members and descriptions."""
        # FILL IN: only models whose authorized[...] is True (governed) or ungoverned
        raise NotImplementedError

    @staticmethod
    def _suggest(name: str, allowed: list[str]) -> list[str]:
        ranked = sorted(allowed, key=lambda a: difflib.SequenceMatcher(None, name, a).ratio(), reverse=True)
        return ranked[:3]
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_catalog.py` (CREATE)

```python
"""Regression contract: Authorized catalog and saved-query expansion (M7)."""
from pathlib import Path
import pytest


def test_catalog_denied_models_and_safe_suggestions(tmp_path: Path) -> None:
    """Verify catalog denied models and safe suggestions."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_all_referenced_members_checked(tmp_path: Path) -> None:
    """Verify all referenced members checked."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_saved_query_same_model_expansion(tmp_path: Path) -> None:
    """Verify saved query same model expansion."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/catalog.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_catalog.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Implement RoleCatalog visible_members/check_query_rights/expand_saved_query/search. Require authorized subject before catalog exposure; filter denied models instead of failing the entire multi-model listing.
- [ ] Check every selected/filter/order/time member plus derived dependencies; suggestions must come only from allowed members. Preserve projected masking rules.
- [ ] Expand a saved query into the same model before rights validation; unknown name denies clearly. No hidden member names or descriptions in search/suggestions.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_catalog.py -q`

## Test Specification

- `test_catalog_denied_models_and_safe_suggestions`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_all_referenced_members_checked`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_saved_query_same_model_expansion`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4473` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.
