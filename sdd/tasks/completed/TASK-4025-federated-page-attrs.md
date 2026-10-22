# TASK-4025: Federated attrs reads and namespace routing

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4023
**Assigned-to**: unassigned

---

## Context

Complete M1 federation. Fan out list_by_attrs only to supporting handles, qualify IDs using existing routing helpers, and report unsupported/error handles through the existing skip mechanism. Route get_attrs using qualified IDs. Expose appropriate supports_attrs for the composed store and forward writes only to a valid writable local target; never use a namespace-scoped facade as the brief writer. _EmptyStore supplies empty attrs reads. Preserve scoped/local qualification, limit and skip semantics.

---

## Scope

Complete M1 federation. Fan out list_by_attrs only to supporting handles, qualify IDs using existing routing helpers, and report unsupported/error handles through the existing skip mechanism. Route get_attrs using qualified IDs. Expose appropriate supports_attrs for the composed store and forward writes only to a valid writable local target; never use a namespace-scoped facade as the brief writer. _EmptyStore supplies empty attrs reads. Preserve scoped/local qualification, limit and skip semantics.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | A federated supports_attrs flag alone cannot hide unsupported individual backends. |
| `packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py` | CREATE | Use deterministic fake handles plus temporary SQLite planes. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Mapping, Sequence  # stdlib or existing pyproject dependency/test environment
from typing import Any  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.federation as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:622
class FederatedWikiStore(BaseWikiStore):

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:960
    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None:

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:950
    async def list_pages(
        self,
        category: str | None = None,
        limit: int = 100,
        origin: list[str] | None = None,
    ) -> list[dict[str, Any]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:712
    def scoped(self, selector: str | None) -> BaseWikiStore:

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1576
class _EmptyStore(BaseWikiStore):
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/federation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.list_pages",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore.scoped",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#_EmptyStore"
  ]
}
```

---

## Implementation Notes

TASK-4023: consumes BaseWikiStore attrs methods

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (MODIFY)

Anchor `class FederatedWikiStore(BaseWikiStore):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:622`.

Anchor `class _EmptyStore(BaseWikiStore):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:1576`.

```python
from collections.abc import Mapping, Sequence
from typing import Any
# Add these overrides inside FederatedWikiStore, preserving its existing methods.
async def get_attrs(self, concept_id: str) -> dict[str, str]:
    """Return attrs for an existing page, respecting backend routing."""
    # FILL IN: implement this task's read contract.
    raise NotImplementedError
async def list_by_attrs(
    self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
    since: str | None = None, until: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """Return matching stubs with AND/IN/date filter semantics."""
    # FILL IN: implement filtering/fan-out per scope and AC.
    raise NotImplementedError
async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
    """Persist attrs for an existing writable page; never target foreign planes."""
    # FILL IN: merge/replace or local-only forwarding per scope and AC.
    raise NotImplementedError
# Extend FederatedWikiStore with the dependency's attrs method signatures.
# FILL IN: use _route/get_page-style dispatch for get_attrs and qualify_id helpers
# for list_by_attrs, while inspecting supports_attrs per handle; AC18.
# FILL IN: preserve task-local skip reporting for unsupported/error handles.
# FILL IN: keep attrs mutations local-only, respecting scoped foreign guards.
# _EmptyStore uses BaseWikiStore's empty reads and unsupported mutation default.
```

**Why**: A federated supports_attrs flag alone cannot hide unsupported individual backends.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.federation as subject


def test_qualified_attrs_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify qualified attrs routing."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_unsupported_and_foreign_write_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unsupported and foreign write guards."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use deterministic fake handles plus temporary SQLite planes.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Foreign results use ns::id; local/scoped IDs obey existing conventions.
- [ ] Unsupported and failed namespaces are skipped with evidence, not fatal.
- [ ] get_attrs routes to the correct plane; foreign attrs writes remain prohibited.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_federation_attrs.py -q`
- `pytest tests/knowledge/wiki/test_federation.py -q`
- `pytest tests/knowledge/wiki/test_federation_overlay.py -q`

---

## Test Specification

- Foreign results use ns::id; local/scoped IDs obey existing conventions.
- Unsupported and failed namespaces are skipped with evidence, not fatal.
- get_attrs routes to the correct plane; foreign attrs writes remain prohibited.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4025`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
