---
type: Wiki Overview
title: 'TASK-1090: ontology_process Degradation Chain'
id: doc:sdd-tasks-completed-task-1090-ontology-degradation-chain-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. `authority="primary"` traversal → tool_call → `context.source="graph:primary"`
relates_to:
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1090: ontology_process Degradation Chain

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1087, TASK-1089
**Assigned-to**: unassigned

---

## Context

> Module 7 of the spec. Adds the 4-level graceful degradation chain to
> `OntologyRAGMixin.ontology_process`. After FEAT-158's refactored traversal+tool_call
> block, this task wraps it in a cascade that falls through progressively less precise
> retrieval strategies, tagging `ContextEnvelope.context.source` at each level.
>
> **Hard dependency on FEAT-158**: The refactored `ontology_process` with `ContextEnvelope`
> return type must exist on the branch.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`:
  - After FEAT-158's refactored body, wrap the traversal+tool_call block in the 4-level chain:
    1. `authority="primary"` traversal → tool_call → `context.source="graph:primary"`
    2. Relax to `authority="secondary"`, retry → `context.source="graph:secondary"`
    3. Vector RAG filtered by `metadata_filters={"doc_type": ["policy","manual"]}` → `context.source="vector:filtered"`
    4. Plain vector RAG → `context.source="vector:plain"`
  - Each level is entered only if the previous returned empty results.
  - `state ∈ {"ambiguous", "denied", "auth_required", "render_error"}` envelopes bypass the chain.
  - Tag `envelope.context.source` per level.
- Write unit tests for each degradation level and bypass conditions.

**NOT in scope**: The YAML traversal (TASK-1084), the hybrid resolver (TASK-1088), IntentRouter branch logic (TASK-1091).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` | MODIFY | Add 4-level degradation chain |
| `packages/ai-parrot/tests/knowledge/test_degradation_chain.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.mixin import OntologyRAGMixin  # verified: mixin.py:27
from parrot.stores.postgres import PgVectorStore  # verified: postgres.py:58
# FEAT-158 additions (must be present on branch):
from parrot.knowledge.ontology.schema import ContextEnvelope, EnrichedContext
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:27
class OntologyRAGMixin:
    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext:  # line 65 — CURRENTLY returns EnrichedContext
        # After FEAT-158 lands, this returns ContextEnvelope instead.
        # This task wraps the traversal block in the degradation chain.

    # Internal vector search helper (verify exact name/signature):
    # Expected: _do_vector_search or similar — grep the mixin for vector search.

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:33
class OntologyGraphStore:
    async def execute_traversal(
        self, ctx, aql, bind_vars=None, collection_binds=None
    ) -> list[dict[str, Any]]:  # line 185
        # The degradation chain calls this twice:
        # 1st with bind_vars={"authority_level": "primary", ...}
        # 2nd with bind_vars={"authority_level": "secondary", ...}

# packages/ai-parrot/src/parrot/stores/postgres.py:741
class PgVectorStore:
    async def similarity_search(
        self, query, table=None, schema=None,
        metadata_filters=None, ...
    ) -> List[SearchResult]:  # After TASK-1087: supports list values in metadata_filters

# FEAT-158 ContextEnvelope (from schema.py):
class ContextEnvelope(BaseModel):
    state: Literal["ok", "ambiguous", "entity_not_found", "denied",
                    "auth_required", "render_error", "tool_failed"]
    context: EnrichedContext | None = None
    # ...
```

### Does NOT Exist
- ~~A degradation chain in `ontology_process` today~~ — does NOT exist; this task adds it
- ~~`EnrichedContext.source` with values like `"graph:primary"`~~ — the field exists as free-form string; these specific values are introduced by this task. Document the convention.
- ~~`ContextEnvelope` on `dev` today~~ — added by FEAT-158; must be present before this task
- ~~A built-in retry mechanism for traversal queries~~ — does NOT exist; the secondary retry is implemented here

---

## Implementation Notes

### Degradation chain structure
```python
async def ontology_process(self, query, user_context, tenant_id, domain=None):
    # ... FEAT-158's existing resolver + intent matching ...

    # If envelope state bypasses chain, return immediately
    if envelope.state in ("ambiguous", "denied", "auth_required", "render_error"):
        return envelope

    # Level 1: Primary authority traversal
    result = await self._ont_graph_store.execute_traversal(
        ctx, aql, bind_vars={**base_vars, "authority_level": "primary"}
    )
    if result:
        # dispatch tool_call with result
        envelope.context.source = "graph:primary"
        return envelope

    # Level 2: Secondary authority
    result = await self._ont_graph_store.execute_traversal(
        ctx, aql, bind_vars={**base_vars, "authority_level": "secondary"}
    )
    if result:
        envelope.context.source = "graph:secondary"
        return envelope

    # Level 3: Filtered vector RAG
    vector_results = await self._ont_vector_store.similarity_search(
        query, metadata_filters={"doc_type": ["policy", "manual"]}, ...
    )
    if vector_results:
        envelope.context.source = "vector:filtered"
        return envelope

    # Level 4: Plain vector RAG
    vector_results = await self._do_vector_search(query, ...)
    envelope.context.source = "vector:plain"
    return envelope
```

### Key Constraints
- The chain MUST respect FEAT-158's existing flow: resolver → intent matching → traversal. The degradation chain wraps only the traversal+tool_call block.
- `authority_level` is bound as a parameter in the AQL, not hardcoded in the query.
- Filtered vector uses `metadata_filters={"doc_type": ["policy", "manual"]}` — requires TASK-1087's list support.
- Plain vector is the existing `_do_vector_search` (or equivalent) path — verify exact method name.
- Document the `context.source` convention in the module docstring.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` — the file to modify
- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:185` — `execute_traversal`
- `packages/ai-parrot/src/parrot/stores/postgres.py:741` — `similarity_search` with metadata_filters

---

## Acceptance Criteria

- [ ] `ontology_process` implements the 4-level degradation chain
- [ ] Level 1: primary traversal hit → `context.source="graph:primary"`, no further levels
- [ ] Level 2: no primary, secondary exists → `context.source="graph:secondary"`
- [ ] Level 3: no graph results → filtered vector with `doc_type IN ('policy','manual')` → `context.source="vector:filtered"`
- [ ] Level 4: filtered vector empty → plain vector → `context.source="vector:plain"`
- [ ] Ambiguity/denial/auth_required envelopes bypass the chain entirely
- [ ] `context.source` convention documented in module docstring
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_degradation_chain.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_degradation_chain.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestDegradationChain:
    async def test_primary_hit(self):
        """Concept matched, primary edge exists → graph:primary, no secondary."""

    async def test_relax_to_secondary(self):
        """No primary, one secondary → graph:secondary."""

    async def test_filtered_vector(self):
        """No graph results → filtered vector → vector:filtered."""

    async def test_plain_vector(self):
        """Filtered vector empty → plain vector → vector:plain."""

    async def test_ambiguity_bypasses_chain(self):
        """state=ambiguous → chain NOT entered."""

    async def test_auth_required_bypasses_chain(self):
        """state=auth_required → chain NOT entered."""

    async def test_denied_bypasses_chain(self):
        """state=denied → chain NOT entered."""

    async def test_render_error_bypasses_chain(self):
        """state=render_error → chain NOT entered."""

    async def test_levels_entered_in_order(self):
        """Each level skipped only when previous returned non-empty."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1087 and TASK-1089 are in `tasks/completed/`
3. **CRITICAL**: Verify FEAT-158 has landed — `ContextEnvelope` and the refactored `ontology_process` must exist
4. **Verify the Codebase Contract** — before writing ANY code:
   - Read `mixin.py` to understand the current `ontology_process` flow (will be refactored by FEAT-158)
   - Grep for vector search helpers (`_do_vector_search` or similar)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1090-ontology-degradation-chain.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
