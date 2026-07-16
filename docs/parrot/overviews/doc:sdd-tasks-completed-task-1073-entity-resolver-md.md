---
type: Wiki Overview
title: 'TASK-1073: Implement EntityResolver with four strategies'
id: doc:sdd-tasks-completed-task-1073-entity-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 New Public Interfaces, §3 Module 2. `EntityResolver` is the component
  that converts natural-language mentions (e.g., *"Jesús"*) into graph `_id`s. It
  is the linchpin of the driving use case — without it, the AQL has no `@target_id`
  to bind, and traversal cannot proceed.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.ontology.entity_resolver
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1073: Implement EntityResolver with four strategies

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1071
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces, §3 Module 2. `EntityResolver` is the component that converts natural-language mentions (e.g., *"Jesús"*) into graph `_id`s. It is the linchpin of the driving use case — without it, the AQL has no `@target_id` to bind, and traversal cannot proceed.

The resolver MUST raise typed exceptions (`EntityAmbiguityError`, `EntityNotFoundError`) so the Mixin can translate them to `ContextEnvelope` states. It MUST NOT swallow ambiguity into silent picks unless the rule explicitly says so.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` with:
  - `class EntityAmbiguityError(Exception)` carrying `rule_name`, `mention`, `candidates: list[dict]`.
  - `class EntityNotFoundError(Exception)` carrying `rule_name`, `mention: str | None`.
  - `class EntityResolver` with async `extract_and_resolve(pattern, query, user_context, tenant_id) -> dict[str, str]`.
- Implement **mention extraction** per rule:
  - Heuristic: strip the matched trigger phrase from the query, take residual capitalized tokens as the mention candidate.
  - LLM-assisted: only when `rule.resolver == "ai_assisted"` OR the heuristic produces nothing AND an `llm_client` is configured.
- Implement four **resolution strategies** dispatched on `rule.resolver`:
  - `exact_id_match`: AQL `FILTER e.{key_field} == @mention LIMIT 2`.
  - `fuzzy_name_match`: AQL `FILTER LIKE(LOWER(e.name), CONCAT('%', LOWER(@mention), '%')) SORT LENGTH(e.name) ASC LIMIT 10`.
  - `ai_assisted`: shortlist by fuzzy (top 10), then LLM picks one with structured output.
  - `hybrid_concept_match`: raise `NotImplementedError` with a message pointing to FEAT-concept-document-authority.
- Implement **scope filtering** from `user_context`:
  - `same_tenant`: implicit (tenant scoping is done by `OntologyGraphStore.execute_traversal` via `TenantContext`).
  - `same_department`: add `FILTER e.department == @user_department` (skip silently if `user_context` has no `department`).
  - `anywhere`: no filter.
- Implement **ambiguity handling** per `rule.ambiguity_strategy`:
  - `ask_user` or `fail` → raise `EntityAmbiguityError(rule_name, mention, candidates)`.
  - `pick_first` → return the first candidate by sort order.
  - `use_context` → re-rank by proximity (same dept → same mgmt chain → others). If the re-rank yields a unique winner, return it; else raise `EntityAmbiguityError` (fall through to `ask_user` semantics).
  - `rerank_by_authority` → raise `NotImplementedError` (reserved for FEAT-concept-document-authority).
- Skip rules where the mention cannot be extracted AND `rule.required is False`. If `required` and no mention → `EntityNotFoundError`.
- Return `dict[str, str]` mapping `rule_name -> resolved _id`.

**NOT in scope**:
- Authorization (TASK-1074).
- Tool dispatch (TASK-1075).
- Mixin composition (TASK-1076).
- The full `hybrid_concept_match` strategy — explicitly deferred to FEAT-concept-document-authority. Only the `NotImplementedError` placeholder is in scope.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` | CREATE | `EntityResolver` + typed exceptions. |
| `packages/ai-parrot/tests/knowledge/test_entity_resolver.py` | CREATE | Unit tests covering all four strategies, scope filters, and ambiguity. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import (
    TraversalPattern,           # schema.py:131 — extended in TASK-1071
    EntityExtractionRule,       # NEW from TASK-1071
    MergedOntology,             # schema.py:185
)
from parrot.knowledge.ontology.graph_store import OntologyGraphStore   # graph_store.py:33
from parrot.clients.abstract_client import AbstractClient              # confirm path before use
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:33
class OntologyGraphStore:
    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:                              # lines 185-223

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:185 (post TASK-1071)
class MergedOntology:
    # Use to discover entity collection name for a given `EntityExtractionRule.type`.
    def get_entity_collections(self) -> list[str]: ...
```

### Does NOT Exist
- ~~A pre-built mention extractor in `parrot.knowledge`~~ — write the heuristic inline; do not invent a `parrot.nlp` module.
- ~~`OntologyGraphStore.search_entity(...)`~~ — there is no helper; use `execute_traversal` with a hand-written AQL.
- ~~`AbstractClient.structured_output(...)`~~ — do not assume a method by that name; use whatever the AbstractClient actually exposes for structured/function-calling output. Verify before use.

---

## Implementation Notes

### Pattern to Follow

```python
class EntityResolver:
    def __init__(
        self,
        graph_store: OntologyGraphStore,
        ontology: MergedOntology,
        llm_client: AbstractClient | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._ontology = ontology
        self._llm = llm_client
        self.logger = logging.getLogger(__name__)

    async def extract_and_resolve(
        self, pattern: TraversalPattern, query: str,
        user_context: dict[str, Any], tenant_id: str,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for rule_name, rule in pattern.entity_extraction.items():
            mention = await self._extract_mention(rule_name, rule, pattern, query)
            if mention is None:
                if rule.required:
                    raise EntityNotFoundError(rule_name=rule_name, mention=None)
                continue
            candidates = await self._resolve(rule, mention, user_context, tenant_id)
            chosen = self._pick(rule, rule_name, mention, candidates, user_context)
            resolved[rule_name] = chosen
        return resolved
```

### Key Constraints

- Async throughout — no blocking calls.
- AQL bind variables ONLY; never string-interpolate user input.
- The fuzzy `LIKE` AQL must use `LOWER(...)` on both sides for case-insensitive match.
- `same_department` scope: read from `user_context.get("department")`. If absent, log a debug message and skip the filter (do not raise).
- `pick_first` requires a stable sort; the AQL `SORT LENGTH(e.name) ASC` provides it for fuzzy; for exact, length sort is trivially deterministic.
- For `use_context` re-ranking, fetch the asking user's `department` and (if available) `manager_id` from `user_context`. If `user_context` lacks these, fall through to ambiguity.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:185` — `execute_traversal` usage.
- `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py:97-127` — example of how `user_context` is consumed elsewhere in the ontology package.

---

## Acceptance Criteria

- [ ] `test_entityresolver_exact_match` passes: unambiguous name → single `_id`, no LLM call.
- [ ] `test_entityresolver_fuzzy_match_ambiguous` passes: multiple matches with `ambiguity_strategy=ask_user` raise `EntityAmbiguityError(name, candidates)`.
- [ ] `test_entityresolver_fuzzy_use_context` passes: two candidates, one in user's dept → resolver picks the in-dept one.
- [ ] `test_entityresolver_not_found_required` passes: `required=True` and no match → `EntityNotFoundError`.
- [ ] `test_entityresolver_not_found_optional` passes: `required=False` and no match → no raise.
- [ ] `test_entityresolver_scope_same_department` passes: filter excludes out-of-department candidates.
- [ ] `hybrid_concept_match` resolver raises `NotImplementedError` referencing FEAT-concept-document-authority.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_entity_resolver.py -v`.
- [ ] No regression on `test_ontology_mixin.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_entity_resolver.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.entity_resolver import (
    EntityResolver, EntityAmbiguityError, EntityNotFoundError,
)
from parrot.knowledge.ontology.schema import (
    TraversalPattern, EntityExtractionRule,
)


@pytest.fixture
def graph_store():
    gs = MagicMock()
    gs.execute_traversal = AsyncMock()
    return gs


@pytest.fixture
def ontology():
    o = MagicMock()
    o.get_entity_collections = MagicMock(return_value=["Employee"])
    return o


@pytest.fixture
def resolver(graph_store, ontology):
    return EntityResolver(graph_store=graph_store, ontology=ontology, llm_client=None)


def _pattern_with_rule(rule: EntityExtractionRule) -> TraversalPattern:
    return TraversalPattern(
        description="t",
        trigger_intents=["el equipo de"],
        query_template="FOR e IN Employee RETURN e",
        post_action="vector_search", post_query=None,
        entity_extraction={"target": rule},
    )


class TestEntityResolver:
    async def test_exact_match_no_llm(self, resolver, graph_store):
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/123", "name": "Jesús Lara"}
        ]
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match",
        ))
        out = await resolver.extract_and_resolve(
            pattern, "el equipo de Jesús", user_context={"user_id": "u1"}, tenant_id="t1",
        )
        assert out == {"target": "Employee/123"}

    async def test_ambiguous_raises(self, resolver, graph_store):
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara"},
            {"_id": "Employee/2", "name": "Jesús Pérez"},
        ]
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match",
            ambiguity_strategy="ask_user",
        ))
        with pytest.raises(EntityAmbiguityError) as exc:
            await resolver.extract_and_resolve(
                pattern, "el equipo de Jesús",
                user_context={"user_id": "u1"}, tenant_id="t1",
            )
        assert exc.value.rule_name == "target"
        assert len(exc.value.candidates) == 2

    async def test_use_context_picks_same_dept(self, resolver, graph_store):
        graph_store.execute_traversal.return_value = [
            {"_id": "Employee/1", "name": "Jesús Lara", "department": "Engineering"},
            {"_id": "Employee/2", "name": "Jesús Pérez", "department": "Sales"},
        ]
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match",
            ambiguity_strategy="use_context",
        ))
        out = await resolver.extract_and_resolve(
            pattern, "el equipo de Jesús",
            user_context={"user_id": "u1", "department": "Engineering"},
            tenant_id="t1",
        )
        assert out == {"target": "Employee/1"}

    async def test_not_found_required_raises(self, resolver, graph_store):
        graph_store.execute_traversal.return_value = []
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match", required=True,
        ))
        with pytest.raises(EntityNotFoundError):
            await resolver.extract_and_resolve(
                pattern, "el equipo de Jesús",
                user_context={"user_id": "u1"}, tenant_id="t1",
            )

    async def test_not_found_optional_silent(self, resolver, graph_store):
        graph_store.execute_traversal.return_value = []
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="fuzzy_name_match", required=False,
        ))
        out = await resolver.extract_and_resolve(
            pattern, "el equipo de Jesús",
            user_context={"user_id": "u1"}, tenant_id="t1",
        )
        assert out == {}

    async def test_hybrid_raises_not_implemented(self, resolver):
        pattern = _pattern_with_rule(EntityExtractionRule(
            type="Employee", resolver="hybrid_concept_match",
        ))
        with pytest.raises(NotImplementedError, match="FEAT-concept-document-authority"):
            await resolver.extract_and_resolve(
                pattern, "X", user_context={"user_id": "u1"}, tenant_id="t1",
            )
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. Verify the contract: re-read `schema.py`, `graph_store.py`, and `intent.py` to confirm signatures are still accurate.
3. Implement following the scope, pattern, and notes.
4. Verify all acceptance criteria.
5. Move this file to `sdd/tasks/completed/`.
6. Update `sdd/tasks/index/ontology-entity-extraction.json` → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session>
**Date**: YYYY-MM-DD
**Notes**: ...
**Deviations from spec**: none | describe if any
