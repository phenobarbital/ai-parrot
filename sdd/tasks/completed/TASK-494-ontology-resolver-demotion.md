# TASK-494: OntologyIntentResolver Demotion

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-491
**Assigned-to**: unassigned

---

## Context

> Demotes the existing OntologyIntentResolver from being a full router to being an AQL query planner only. The IntentRouterMixin (TASK-491) now handles all routing decisions. The OntologyIntentResolver retains its fast-path and LLM-path for AQL query planning but loses its routing responsibilities.
> Implements spec Section 3 — Module 6 (OntologyIntentResolver Demotion).
> This is a careful refactor: standalone usage of OntologyIntentResolver must still work (no breaking change for existing consumers).

---

## Scope

- Modify `parrot/knowledge/ontology/schema.py`:
  - Deprecate `IntentDecision.action` field: make it `Optional` with default `None`. Add deprecation note in docstring.
  - Deprecate `ResolvedIntent.action` field: make it `Optional` with default `"graph_query"`. Add deprecation note in docstring.
- Modify `parrot/knowledge/ontology/intent.py`:
  - Remove the `vector_only` fallback path from `resolve()`. When the resolver cannot build an AQL query, it should return `None` or a result indicating "no AQL plan" rather than falling back to vector search (that's now IntentRouterMixin's job).
  - Keep `_try_fast_path()` intact — it still produces AQL query plans from keyword patterns.
  - Keep `_try_llm_path()` intact — it still uses the LLM to generate AQL query plans.
  - Add deprecation warnings (via `warnings.warn()`) when `action` field is explicitly set to non-graph values.
- Ensure standalone usage still works: calling `OntologyIntentResolver.resolve()` directly still returns valid results for graph/AQL queries.

**NOT in scope**: IntentRouterMixin (TASK-491 — already done), CapabilityRegistry changes, AbstractBot changes (TASK-492).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/knowledge/ontology/schema.py` | MODIFY | Deprecate action fields on IntentDecision and ResolvedIntent |
| `parrot/knowledge/ontology/intent.py` | MODIFY | Remove vector_only fallback, keep AQL planning paths |
| `tests/knowledge/test_resolver_demotion.py` | CREATE | Tests for deprecated fields and removed fallback |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/knowledge/ontology/schema.py
import warnings
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class IntentDecision(BaseModel):
    """Decision from the intent resolver.

    .. deprecated::
        The `action` field is deprecated. Routing decisions are now handled
        by IntentRouterMixin. This model is used only for AQL query planning.
    """
    # ... existing fields ...
    action: Optional[str] = Field(
        None,
        description="DEPRECATED: Routing action. Use IntentRouterMixin for routing.",
    )

    @model_validator(mode="after")
    def _warn_action_deprecated(self):
        if self.action is not None and self.action != "graph_query":
            warnings.warn(
                "IntentDecision.action is deprecated for routing. "
                "Use IntentRouterMixin instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self


class ResolvedIntent(BaseModel):
    """Resolved intent with AQL query plan.

    .. deprecated::
        The `action` field is deprecated. Defaults to 'graph_query'.
    """
    # ... existing fields ...
    action: Optional[str] = Field(
        "graph_query",
        description="DEPRECATED: Always 'graph_query'. Routing handled by IntentRouterMixin.",
    )
```

```python
# parrot/knowledge/ontology/intent.py
class OntologyIntentResolver:
    async def resolve(self, query: str, **kwargs):
        """Resolve a query into an AQL query plan.

        No longer falls back to vector_only search.
        Returns None if no AQL plan can be generated.
        """
        # Try fast path (keyword-based AQL generation)
        result = self._try_fast_path(query)
        if result:
            return result

        # Try LLM path (LLM-assisted AQL generation)
        result = await self._try_llm_path(query, **kwargs)
        if result:
            return result

        # No AQL plan possible — return None (caller handles fallback)
        self.logger.debug("No AQL plan for query: %s", query)
        return None
```

### Key Constraints
- **Non-breaking for standalone usage**: `OntologyIntentResolver.resolve()` must still work when called directly. Existing code that checks `result.action` should not crash (action defaults to "graph_query").
- **Deprecation warnings**: Use `warnings.warn()` with `DeprecationWarning` category so users are informed but code doesn't break.
- **No removal of fields**: Fields are deprecated, not removed. Removal would be a breaking change for a future major version.
- **vector_only removal**: Find the code path in `resolve()` that falls back to vector-only search and remove it. The resolver should return None when it can't produce an AQL plan.

### References in Codebase
- `parrot/knowledge/ontology/schema.py` — `IntentDecision`, `ResolvedIntent` models
- `parrot/knowledge/ontology/intent.py` — `OntologyIntentResolver` class
- `parrot/bots/mixins/intent_router.py` — `_run_graph_pageindex()` will call the resolver

---

## Acceptance Criteria

- [ ] `IntentDecision.action` is Optional with default None
- [ ] `ResolvedIntent.action` is Optional with default "graph_query"
- [ ] Setting `IntentDecision.action` to non-graph value emits DeprecationWarning
- [ ] `vector_only` fallback path is removed from `resolve()`
- [ ] `resolve()` returns None when no AQL plan can be generated
- [ ] `_try_fast_path()` still works for AQL query generation
- [ ] `_try_llm_path()` still works for AQL query generation
- [ ] Standalone `OntologyIntentResolver.resolve()` still works for graph queries
- [ ] Existing tests for ontology module still pass (no regression)
- [ ] No linting errors: `ruff check parrot/knowledge/ontology/`

---

## Test Specification

```python
# tests/knowledge/test_resolver_demotion.py
import warnings
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestIntentDecisionDeprecation:
    def test_action_defaults_to_none(self):
        from parrot.knowledge.ontology.schema import IntentDecision
        # Create IntentDecision without action
        # Assert action is None
        pass

    def test_action_graph_query_no_warning(self):
        from parrot.knowledge.ontology.schema import IntentDecision
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Create with action="graph_query"
            # Assert no DeprecationWarning
            pass

    def test_action_non_graph_emits_warning(self):
        from parrot.knowledge.ontology.schema import IntentDecision
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Create with action="vector_search"
            # Assert DeprecationWarning emitted
            pass


class TestResolvedIntentDeprecation:
    def test_action_defaults_to_graph_query(self):
        from parrot.knowledge.ontology.schema import ResolvedIntent
        # Create ResolvedIntent without action
        # Assert action == "graph_query"
        pass

    def test_action_is_optional(self):
        from parrot.knowledge.ontology.schema import ResolvedIntent
        # Create with action=None
        # Assert no error
        pass


class TestResolverVectorOnlyRemoved:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_aql_plan(self):
        """resolve() returns None instead of falling back to vector search."""
        from parrot.knowledge.ontology.intent import OntologyIntentResolver
        # Create resolver with mocks
        # Mock _try_fast_path to return None
        # Mock _try_llm_path to return None
        # Call resolve()
        # Assert result is None (not a vector search result)
        pass

    @pytest.mark.asyncio
    async def test_fast_path_still_works(self):
        """_try_fast_path still generates AQL plans."""
        from parrot.knowledge.ontology.intent import OntologyIntentResolver
        # Create resolver, call with a keyword that triggers fast path
        # Assert result has AQL query
        pass

    @pytest.mark.asyncio
    async def test_llm_path_still_works(self):
        """_try_llm_path still generates AQL plans via LLM."""
        from parrot.knowledge.ontology.intent import OntologyIntentResolver
        # Create resolver with mock LLM
        # Call resolve with query that triggers LLM path
        # Assert result has AQL query
        pass


class TestStandaloneUsage:
    @pytest.mark.asyncio
    async def test_direct_resolve_works(self):
        """Standalone OntologyIntentResolver.resolve() still functions."""
        from parrot.knowledge.ontology.intent import OntologyIntentResolver
        # Create resolver, call resolve() with a valid graph query
        # Assert returns a valid result (not None for valid queries)
        pass
```

---

## Agent Instructions

1. Read this task file completely before starting.
2. Read the spec at `sdd/specs/intent-router.spec.md` for full context on Module 6.
3. Verify TASK-491 is complete (IntentRouterMixin exists).
4. Read `parrot/knowledge/ontology/schema.py` to understand current IntentDecision and ResolvedIntent fields.
5. Read `parrot/knowledge/ontology/intent.py` to find and understand the `vector_only` fallback path.
6. Make minimal, backward-compatible changes with deprecation warnings.
7. Run existing tests for `parrot/knowledge/ontology/` to verify no regressions.
8. Run `ruff check` on all modified files.
9. Run the tests in **Test Specification** with `pytest`.
10. Do NOT implement anything outside the **Scope** section.
11. When done, fill in the **Completion Note** below and commit.

---

## Completion Note

*(Agent fills this in when done)*
