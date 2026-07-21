---
type: Wiki Overview
title: 'TASK-1088: hybrid_concept_match Resolver Strategy'
id: doc:sdd-tasks-completed-task-1088-hybrid-concept-match-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.stores.postgres import PgVectorStore # verified: postgres.py:58'
relates_to:
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1088: hybrid_concept_match Resolver Strategy

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1085, TASK-1087
**Assigned-to**: unassigned

---

## Context

> Module 5 of the spec. Implements the `hybrid_concept_match` resolver strategy inside
> FEAT-158's `EntityResolver`. FEAT-158 declared this strategy with `NotImplementedError`;
> this task replaces that with the actual implementation. The algorithm cascades:
> synonym/fuzzy exact → vector top-K → LLM tie-breaker. Multi-concept parsing for
> conjunction queries ("A and B", "A y B"). Returns `list[str]` of resolved Concept `_id`s.
>
> **Hard dependency on FEAT-158**: `EntityResolver`, `EntityExtractionRule` must exist on
> the branch before this task can be implemented.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` (FEAT-158 creates this file):
  - Implement `_resolve_hybrid_concept_match(rule, mention, user_context, tenant_id) -> list[str]`.
  - Stage 1: Synonym/fuzzy exact match over `ontology.entities['Concept'].instances`.
  - Stage 2: `PgVectorStore.similarity_search()` on `concepts` namespace with `metadata_filters={'tenant_id': tenant_id}`, top_k=10.
  - Stage 3: LLM tie-breaker over top-5 candidates when vector scores are ambiguous.
  - Multi-concept conjunction parsing: regex-based splitting on `\band\b`, `\bvs?\.?\b`, `\b[ye]\b`, `\bfrente a\b`.
  - Result caching by `(query_hash, ontology_version, tenant_id)`.
  - Cap concept list to 5 (drop extras with debug log).
- Write comprehensive unit tests.

**NOT in scope**: The YAML traversal pattern (TASK-1084), the degradation chain (TASK-1090), PageIndex integration (TASK-1089).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` | MODIFY | Implement _resolve_hybrid_concept_match |
| `packages/ai-parrot/tests/knowledge/test_hybrid_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.stores.postgres import PgVectorStore  # verified: postgres.py:58
# FEAT-158 additions (must be present on branch before this task):
from parrot.knowledge.ontology.entity_resolver import EntityResolver  # FEAT-158 creates this
from parrot.knowledge.ontology.schema import EntityExtractionRule  # FEAT-158 adds this to schema.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/stores/postgres.py:741
class PgVectorStore:
    async def similarity_search(
        self,
        query: str,
        table: str = None,
        schema: str = None,
        metadata_filters: Optional[Dict[str, Any]] = None,  # line 748
        ...
    ) -> List[SearchResult]:  # already supports metadata_filters with scalar equality + list/IN (after TASK-1087)

# FEAT-158 EntityExtractionRule (from schema.py):
class EntityExtractionRule(BaseModel):
    type: str
    resolver: Literal["exact_id_match", "fuzzy_name_match", "ai_assisted", "hybrid_concept_match"]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal["ask_user", "pick_first", "use_context", "fail", "rerank_by_authority"] = "ask_user"
    required: bool = True
```

### Does NOT Exist
- ~~`EntityResolver` on `dev` today~~ — added by FEAT-158; MUST be present before this task starts
- ~~`_resolve_hybrid_concept_match` implementation~~ — FEAT-158 declares it with `NotImplementedError`; this task provides the real implementation
- ~~A `concepts` PgVector namespace with pre-populated data~~ — populated by `ConceptEmbeddingPipeline.sync()` (TASK-1085); tests mock the vector store
- ~~An existing synonym matcher in the ontology module~~ — does NOT exist; this task implements the fuzzy/synonym matching inline

---

## Implementation Notes

### Multi-concept conjunction detection
```python
import re

CONJUNCTION_RE = re.compile(
    r'\bvs?\.?\b|\band\b|\b[ye]\b|\bfrente\s+a\b',
    re.IGNORECASE,
)

def _split_mentions(self, mention: str) -> list[str]:
    """Split multi-concept mentions into individual terms."""
    parts = CONJUNCTION_RE.split(mention)
    return [p.strip() for p in parts if p.strip()]
```

### Resolution cascade (per term)
```python
async def _resolve_single_term(self, term, ontology_concepts, tenant_id):
    # Stage 1: Synonym/fuzzy exact match
    for concept in ontology_concepts:
        if term.lower() in [s.lower() for s in concept.synonyms + [concept.label]]:
            return [concept.id]  # confidence > 0.95, done

    # Stage 2: Vector search
    results = await self._vector_store.similarity_search(
        query=term,
        table="concepts",
        schema="ontology",
        metadata_filters={"tenant_id": tenant_id},
        limit=10,
    )
    if results and results[0].score < threshold and results[0].score < 1.3 * results[1].score:
        return [results[0].metadata["concept_id"]]

    # Stage 3: LLM tie-breaker on top-5
    top5 = results[:5]
    selected = await self._llm_tiebreak(term, top5)
    return selected
```

### Key Constraints
- **Multi-concept queries**: split with regex, resolve each term, union results, deduplicate by `_id`, cap at 5.
- **Result caching**: use `functools.lru_cache` or a dict keyed by `(hash(mention), ontology_version, tenant_id)`.
- **Tenant isolation**: vector search MUST pass `metadata_filters={"tenant_id": tenant_id}`.
- **LLM tie-breaker prompt**: ask model to return JSON array of selected `concept_id`s; validate against candidate pool.
- **Score comparison**: vector results use distance (lower = more similar for cosine). Adjust thresholds accordingly based on PgVectorStore's distance strategy.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` — FEAT-158's file to modify
- `packages/ai-parrot/src/parrot/stores/postgres.py` — PgVectorStore for vector search

---

## Acceptance Criteria

- [ ] `_resolve_hybrid_concept_match` replaces FEAT-158's `NotImplementedError`
- [ ] Synonym exact match returns immediately without vector or LLM call
- [ ] Vector clearly dominant (top-1 >> top-2) returns without LLM call
- [ ] Ambiguous vector results trigger LLM tie-breaker
- [ ] Tenant filtering enforced at vector step
- [ ] Multi-concept conjunction parsing works for English ("and", "vs") and Spanish ("y", "frente a")
- [ ] Results cached by `(query_hash, ontology_version, tenant_id)`
- [ ] Cache invalidates on ontology version bump
- [ ] Concept list capped at 5
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_hybrid_resolver.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_hybrid_resolver.py
import pytest


class TestHybridConceptMatchResolver:
    async def test_synonym_dominant(self):
        """Exact synonym match → returns immediately, no vector/LLM call."""

    async def test_vector_clearly_dominant(self):
        """top-1 score >> top-2 → returns without LLM."""

    async def test_llm_tiebreaker(self):
        """Ambiguous vector scores → LLM tie-breaker invoked with top-5."""

    async def test_tenant_filter(self):
        """Resolver with tenant_id='acme' does not return 'globex' concepts."""

    async def test_multi_concept_conjunction_en(self):
        """'commissions and bonuses' → union of both concept IDs."""

    async def test_multi_concept_conjunction_es(self):
        """'comisiones y bonos' → union of both concept IDs."""

    async def test_cache_hit(self):
        """Same query+version+tenant → no vector/LLM on second call."""

    async def test_cache_invalidates_on_version_bump(self):
        """Bump ontology version → fresh resolution."""

    async def test_cap_at_five_concepts(self):
        """Query resolving 7 concepts → only first 5 returned."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1085 and TASK-1087 are in `tasks/completed/`
3. **CRITICAL**: Verify FEAT-158 has landed — `EntityResolver` must exist in `entity_resolver.py`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Read `entity_resolver.py` to find the `NotImplementedError` stub for `hybrid_concept_match`
   - Confirm `PgVectorStore.similarity_search` has `metadata_filters` with list support
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1088-hybrid-concept-match-resolver.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
