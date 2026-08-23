# TASK-2375: article_in_force resolution helper and boundary tests

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2371
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. A **thin, typed wrapper** that binds `as_of` and calls the declarative
traversal pattern from TASK-2371.

> **Read this before writing any code.** The resolution *logic* lives in the YAML
> `query_template`. This module is ergonomics — binding, calling, deserialising. If you find
> yourself re-implementing version selection in Python (looping over `versions[]`, comparing
> dates), **stop**: you are duplicating the pattern and violating spec goal G4. The correct
> fix for a resolution bug is to change the AQL, not to add Python.

This task also owns the **boundary-semantics tests**, which are the feature's most important
correctness guarantee: an off-by-one here silently returns the wrong law.

---

## Scope

- Implement `async def article_in_force(store, ctx, articulo_key, as_of) -> ArticleVersion | None`
  that looks up the `article_in_force` pattern from `ctx.ontology.traversal_patterns`, binds
  `@articulo_key` and `@as_of` plus the `@@articulo` collection bind, calls
  `OntologyGraphStore.execute_traversal`, and deserialises the single result.
- Return `None` when no version was in force (e.g. `as_of` precedes the first `valid_from`).
- Write unit tests for version selection and boundary semantics against a **stubbed**
  `execute_traversal` — no live ArangoDB in unit tests.

**NOT in scope**: defining the AQL (TASK-2371); any Python re-implementation of version
selection; live-database integration tests (TASK-2376).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` | CREATE | Typed wrapper around the traversal pattern |
| `packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py` | CREATE | Selection + boundary tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import date
from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # graph_store.py:33
from parrot.knowledge.ontology.schema import (
    TenantContext,       # schema.py:406
    TraversalPattern,    # schema.py:263
)
from parrot_tools.legal.boe.models import ArticleVersion              # TASK-2372
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:185
async def execute_traversal(
    self,
    ctx: TenantContext,
    aql: str,
    bind_vars: dict[str, Any] | None = None,
    collection_binds: dict[str, str] | None = None,
) -> list[dict[str, Any]]: ...
#   bind_vars and collection_binds are MERGED internally into one dict before execution.
#   Returns [] when the query yields nothing (never None).

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:406
class TenantContext(BaseModel):
    tenant_id: str
    arango_db: str
    pgvector_schema: str
    ontology: MergedOntology        # .traversal_patterns lives here

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:330
class MergedOntology(BaseModel):
    traversal_patterns: dict[str, TraversalPattern]

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:263
class TraversalPattern(BaseModel):
    query_template: str      # the AQL to pass to execute_traversal
```

### Does NOT Exist

- ~~A Python `article_in_force` resolver anywhere~~ — and you must not create one beyond the
  thin wrapper described above. The logic is the AQL.
- ~~Any temporal helper in `parrot/knowledge/`~~ — grep for `valid_from|valid_to|as_of`
  returns 2 unrelated `valid_toc_items` hits in `pageindex/builder.py`. No prior art.
- ~~`execute_traversal` returning `None`~~ — it returns `[]` for an empty result (see
  `graph_store.py:205-220`). Do not write `if result is None`.
- ~~A `pattern.execute()` or `TraversalPattern.run()` method~~ — `TraversalPattern` is a
  **plain Pydantic data model** with no behaviour. You read `.query_template` off it and
  pass that string to `execute_traversal` yourself.
- ~~`ctx.traversal_patterns`~~ — the path is `ctx.ontology.traversal_patterns`.

---

## Implementation Notes

### Pattern to Follow

```python
async def article_in_force(
    store: OntologyGraphStore,
    ctx: TenantContext,
    articulo_key: str,
    as_of: date,
) -> ArticleVersion | None:
    """Resolve the wording of an article in force on a given date."""
    pattern = ctx.ontology.traversal_patterns["article_in_force"]
    rows = await store.execute_traversal(
        ctx,
        pattern.query_template,
        bind_vars={"articulo_key": articulo_key, "as_of": as_of.isoformat()},
        collection_binds={"@articulo": "articulo"},
    )
    if not rows:
        return None
    return ArticleVersion(**rows[0])
```

### Key Constraints

- **Date representation must match TASK-2371's AQL and TASK-2372's parser output.** If the
  AQL compares ISO `YYYY-MM-DD` strings, bind `as_of.isoformat()`. A mismatch produces
  silently wrong results, not an error — verify against both tasks before finalising.
- Async throughout; strict type hints; Google-style docstrings.
- Return `None`, never raise, when nothing was in force — "no law applied on that date" is a
  legitimate answer.
- If the pattern name is missing from the ontology, raise a clear `KeyError`/`ValueError`
  naming the missing pattern — that is a configuration bug worth failing loudly on.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:185-224` — `execute_traversal` semantics, including bind merging and empty-result handling
- Spec §7 Known Risks — boundary semantics

---

## Acceptance Criteria

- [ ] `article_in_force` is async and returns `ArticleVersion | None`
- [ ] It reads `query_template` from `ctx.ontology.traversal_patterns["article_in_force"]` — the AQL is **not** inlined in Python
- [ ] It binds `articulo_key`, `as_of`, and the `@articulo` collection bind
- [ ] Given a 3-version article, each of 3 dates selects the correct wording
- [ ] `as_of == valid_from` selects **that** version (inclusive lower bound)
- [ ] `as_of == valid_to` selects the **next** version (exclusive upper bound)
- [ ] `as_of` before the first `valid_from` returns `None`, not version 0
- [ ] Contains **no** Python loop over `versions[]` performing date comparison
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py
import inspect
from datetime import date
import pytest
from parrot_tools.legal.boe.queries import article_in_force


class FakeStore:
    """Stubs execute_traversal; asserts the wrapper binds correctly."""
    def __init__(self, rows): self.rows = rows; self.last = None
    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None):
        self.last = (aql, bind_vars, collection_binds)
        return self.rows


class TestTemporalResolution:
    async def test_binds_as_of_and_key(self, legal_ctx):
        store = FakeStore([])
        await article_in_force(store, legal_ctx, "BOE-A-2015-10566:5", date(2020, 1, 1))
        _, binds, cbinds = store.last
        assert "as_of" in binds and "articulo_key" in binds
        assert "@articulo" in cbinds

    async def test_returns_none_when_no_version(self, legal_ctx):
        store = FakeStore([])
        assert await article_in_force(store, legal_ctx, "k", date(1900, 1, 1)) is None

    async def test_uses_pattern_from_ontology_not_inline_aql(self, legal_ctx):
        store = FakeStore([])
        await article_in_force(store, legal_ctx, "k", date(2020, 1, 1))
        aql, _, _ = store.last
        assert aql == legal_ctx.ontology.traversal_patterns["article_in_force"].query_template

    def test_no_python_date_comparison(self):
        """Version selection must live in AQL, not Python (spec goal G4)."""
        import parrot_tools.legal.boe.queries as m
        src = inspect.getsource(m)
        assert "valid_from" not in src, "date logic belongs in the traversal pattern"
```

> Boundary behaviour (inclusive `valid_from` / exclusive `valid_to`) is asserted end-to-end
> against a real graph in TASK-2376; here it is asserted at the binding level.

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§2 Overview, goal G4).
2. **Check dependencies** — TASK-2371 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
5. **Implement** the wrapper and tests. Resist adding Python date logic.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2375-temporal-resolution-helper.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-23
**Notes**: Implemented `article_in_force(store, ctx, articulo_key, as_of)`
exactly per the "Pattern to Follow" — reads `query_template` from
`ctx.ontology.traversal_patterns["article_in_force"]`, binds
`articulo_key`/`as_of`/`@articulo`, calls `execute_traversal`, returns
`ArticleVersion(**rows[0])` or `None`. Added a `KeyError` with a clear
message when the pattern is missing from the ontology (configuration bug,
fails loudly per the task's constraint). Contains zero Python date
comparison — asserted by `test_no_python_date_comparison`, which greps the
module source for the literal string `"valid_from"` (also had to phrase
the docstring's "no version in force" explanation without using that
literal substring, to avoid tripping its own test). 9 unit tests pass
(`pytest -c pytest.ini packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py -v`);
full `tests/legal/` suite (38/38) passes together. `ruff check` clean.

The `legal_ctx` fixture (not shown in the task's Test Specification stub)
was built by merging `base.ontology.yaml` + `legal.ontology.yaml` via
`OntologyMerger`, matching TASK-2370/2371's own test fixture pattern, then
wrapping the result in a `TenantContext`. Boundary semantics
(`valid_from` inclusive / `valid_to` exclusive) are asserted at the
binding/deserialisation level only, per the task's own note that true
end-to-end boundary enforcement (via the AQL FILTER clauses against a real
graph) is TASK-2376's concern.

**Deviations from spec**: none.
