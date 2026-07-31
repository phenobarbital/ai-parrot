---
type: Wiki Overview
title: 'TASK-1092: End-to-End Tests & Golden Fixtures'
id: doc:sdd-tasks-completed-task-1092-e2e-tests-golden-fixtures-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.knowledge.ontology.mixin import OntologyRAGMixin # verified:
  mixin.py:27'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_embedding
  rel: mentions
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1092: End-to-End Tests & Golden Fixtures

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1084, TASK-1085, TASK-1086, TASK-1087, TASK-1088, TASK-1089, TASK-1090, TASK-1091
**Assigned-to**: unassigned

---

## Context

> Module 9 of the spec. Driving use case validation that exercises all prior modules
> end-to-end. Fixtures model the canonical "commissions" scenario: 3 documents, 2 concepts
> linked via is_a, covers_topic edges with authority levels, mocked PageIndex trees, and
> mocked vector store with metadata_filters honored.

---

## Scope

- Create test fixtures:
  - 3 Documents: sales-commissions-policy (primary), commissions-faq (mentions), commissions-memo (mentions), bonus-policy (primary for bonuses).
  - 2 Concepts: commissions (parent), sales-commissions (is_a commissions), bonuses, pto.
  - `covers_topic` edges seeded.
  - Mocked `PageIndexToolkit._indices` returning deterministic snippets.
  - Mocked `PgVectorStore` honoring metadata_filters.
- Create `packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py` with:
  - `test_e2e_commissions_routes_to_policy` — primary doc returned, not FAQ/memo.
  - `test_e2e_sub_concept_routes_to_parent_primary` — sub-concept walks is_a to parent's primary.
  - `test_e2e_multi_concept_union` — two concepts → union of primaries.
  - `test_e2e_unknown_concept_vector_fallback` — degradation to vector.
  - `test_e2e_no_primary_falls_to_secondary` — secondary fallback.
  - `test_e2e_concept_synonyms_re_embedding` — synonym update triggers re-embed.
  - `test_e2e_two_primaries_deterministic_order` — equal authority_score ordering.
  - `test_e2e_pageindex_tree_id_missing_silent` — missing tree_id graceful handling.
- Verify no regression in existing PageIndex tests or FEAT-158's tests.

**NOT in scope**: Implementing any module — this task only writes tests and fixtures.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py` | CREATE | End-to-end integration tests |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/conftest.py` | CREATE | Shared fixtures |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/authority/acme.yaml` | CREATE | Per-tenant authority fixture |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/knowledge.ontology.yaml` | CREATE | Knowledge YAML fixture (copy or symlink) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.mixin import OntologyRAGMixin  # verified: mixin.py:27
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # verified: tenant.py:18
from parrot.knowledge.ontology.merger import OntologyMerger  # verified: merger.py:26
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # verified: graph_store.py:33
from parrot.knowledge.ontology.cache import OntologyCache  # verified: cache.py:30
from parrot.tools.pageindex_toolkit import PageIndexToolkit  # verified: pageindex_toolkit.py:39
from parrot.stores.postgres import PgVectorStore  # verified: postgres.py:58
from parrot.pageindex.retriever import PageIndexRetriever  # verified: retriever.py:11
from parrot.knowledge.ontology.concept_embedding import ConceptEmbeddingPipeline  # TASK-1085
# FEAT-158 additions:
from parrot.knowledge.ontology.schema import ContextEnvelope, EnrichedContext
from parrot.knowledge.ontology.entity_resolver import EntityResolver
```

### Does NOT Exist
- All "Does NOT Exist" items from the spec §6 apply here. The implementing agent must verify each module's actual interface before writing fixture wiring.

---

## Implementation Notes

### Fixture strategy
Use `pytest` fixtures with `unittest.mock` for external dependencies:
- **ArangoDB**: Mock `OntologyGraphStore.execute_traversal` to return deterministic document rows based on `bind_vars["authority_level"]` and `bind_vars["topic_ids"]`.
- **PageIndex**: Mock `PageIndexToolkit._indices` with deterministic retrievers.
- **PgVectorStore**: Mock or use an in-memory double that respects `metadata_filters`.
- **LLM client**: Mock for the hybrid resolver's tie-breaker step.

### Key Constraints
- Tests must be deterministic — no actual DB, no actual LLM calls.
- Fixture data must match spec §4 exactly (document names, concept names, edge types).
- Each test should assert on `ContextEnvelope.context.source` to verify which degradation level was hit.
- Run existing test suites to verify no regressions.

### References in Codebase
- Spec §4 — full test specification with 8 integration tests
- Spec §4 "Test Data / Fixtures" — fixture shapes
- `packages/ai-parrot/tests/` — existing test patterns to follow

---

## Acceptance Criteria

- [ ] All 8 e2e tests from spec §4 are implemented
- [ ] `test_e2e_commissions_routes_to_policy` passes
- [ ] `test_e2e_sub_concept_routes_to_parent_primary` passes
- [ ] `test_e2e_multi_concept_union` passes
- [ ] `test_e2e_unknown_concept_vector_fallback` passes
- [ ] `test_e2e_no_primary_falls_to_secondary` passes
- [ ] `test_e2e_concept_synonyms_re_embedding` passes
- [ ] `test_e2e_two_primaries_deterministic_order` passes
- [ ] `test_e2e_pageindex_tree_id_missing_silent` passes
- [ ] No regression in existing PageIndex tests
- [ ] No regression in FEAT-158's `test_entity_extraction_e2e.py` (if present)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_concept_authority_e2e.py
import pytest


class TestConceptAuthorityE2E:
    async def test_e2e_commissions_routes_to_policy(self, acme_ontology, pageindex_toolkit_with_indices):
        """'how do commissions work?' → primary doc (sales-commissions-policy), source=graph:primary."""

    async def test_e2e_sub_concept_routes_to_parent_primary(self, acme_ontology, pageindex_toolkit_with_indices):
        """'how do sales commissions work?' → walks is_a → parent primary doc."""

    async def test_e2e_multi_concept_union(self, acme_ontology, pageindex_toolkit_with_indices):
        """'commissions and bonuses' → union of both concepts' primaries."""

    async def test_e2e_unknown_concept_vector_fallback(self, acme_ontology, pgvector_with_concepts):
        """'holiday roster' (no concept) → vector fallback."""

    async def test_e2e_no_primary_falls_to_secondary(self, acme_ontology):
        """Concept matched but only secondary → graph:secondary."""

    async def test_e2e_concept_synonyms_re_embedding(self, acme_ontology, pgvector_with_concepts):
        """Add synonym, re-sync → only that concept re-embedded."""

    async def test_e2e_two_primaries_deterministic_order(self, acme_ontology, pageindex_toolkit_with_indices):
        """Equal authority_score → deterministic ordering across runs."""

    async def test_e2e_pageindex_tree_id_missing_silent(self, acme_ontology, pageindex_toolkit_with_indices):
        """Missing tree_id → warning logged, remaining trees returned, state=ok."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (especially §4)
2. **Check dependencies** — ALL prior tasks (TASK-1084 through TASK-1091) must be in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read each module file created by prior tasks to understand their actual interfaces
   - Confirm all imports and method signatures
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Run existing test suites** to verify no regressions
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1092-e2e-tests-golden-fixtures.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
