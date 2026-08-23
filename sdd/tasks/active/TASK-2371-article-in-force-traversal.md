# TASK-2371: article_in_force declarative TraversalPattern

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2370
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (traversal half) and goal **G4**. The parent proposal's finding F018 showed
that `TraversalPattern` is a first-class ontology construct carrying an AQL `query_template`
with bind variables — so "which wording was in force on date D" is **configuration, not
Python**. This is the design's central bet: if version resolution lives in a Python helper,
the feature has failed its own architecture.

Resolution is O(1) selection over the embedded `versions[]` list, **not** a graph traversal.
`modifica`/`deroga` edges exist for provenance ("which norm changed this, and when") and are
deliberately not the validity mechanism.

---

## Scope

- Add a `traversal_patterns:` section to `legal.ontology.yaml` with an `article_in_force`
  pattern whose `query_template` is AQL selecting the correct `versions[]` entry for a bound
  `@as_of` date, given a bound `@articulo_key`.
- Define boundary semantics explicitly in the AQL: **`valid_from` inclusive, `valid_to`
  exclusive**; a null `valid_to` means "currently in force".
- Add `trigger_intents` keywords (Spanish and English) for the fast path.
- Set `post_action: none` (v1 has no vector step).
- Write tests asserting the template passes `validate_aql` and that the pattern loads via
  `OntologyMerger`.

**NOT in scope**: the Python wrapper that binds and calls it (TASK-2375); executing the
query against a live ArangoDB (TASK-2376); `case_chain` or `what_applies` patterns (Sprint 2+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | MODIFY | Add `traversal_patterns:` section |
| `packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py` | MODIFY | Add traversal-pattern + AQL-validation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import TraversalPattern        # schema.py:263
from parrot.knowledge.ontology.validators import validate_aql        # validators.py:36 (ASYNC)
from parrot.knowledge.ontology.exceptions import AQLValidationError
from parrot.knowledge.ontology.merger import OntologyMerger          # merger.py:26
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:263
class TraversalPattern(BaseModel):
    description: str                       # REQUIRED
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str                    # REQUIRED — AQL with @binds / @@collection binds
    post_action: Literal["vector_search","tool_call","none"] = "none"
    post_query: str | None = None
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None
    model_config = ConfigDict(extra="forbid")

# packages/ai-parrot/src/parrot/knowledge/ontology/validators.py:36
async def validate_aql(aql: str, max_depth: int | None = None) -> Any: ...
#   Rejects: INSERT|UPDATE|REMOVE|REPLACE|UPSERT (mutations)
#            _system|_graphs|_modules|_analyzers|_jobs|_queues (system collections)
#            APPLY|CALL|V8 (JavaScript execution)
#   max_depth defaults to ONTOLOGY_MAX_TRAVERSAL_DEPTH (conf.py:150, default 4)
```

### Verified YAML shape (from the shipped domain example)

`defaults/domains/field_services.ontology.yaml:86` —

```yaml
traversal_patterns:
  find_project:
    description: Find the project an employee is assigned to
    trigger_intents:
      - my project
      - which project
    query_template: >
      FOR v IN 1..1 OUTBOUND @user_id @@assigned_to RETURN v
    post_action: none
```

### Does NOT Exist

- ~~Any existing temporal / as-of query anywhere in `parrot/knowledge/`~~ — a grep for
  `valid_from|valid_to|as_of` across the whole subtree returns 2 hits, both the unrelated
  local `valid_toc_items` in `pageindex/builder.py:1476,1480`. There is **no** prior art to
  copy. You are writing the first temporal query in the codebase.
- ~~`validate_aql` as a synchronous function~~ — it is `async def` (`validators.py:36`).
  You must `await` it; tests need `pytest.mark.asyncio` or the project's async test config.
- ~~A `date` comparison helper in the ontology layer~~ — compare ISO date strings directly
  in AQL, or bind a normalised value. Do not invent `DATE_COMPARE` helpers without checking
  ArangoDB's actual AQL function list.
- ~~`post_action: "graph_query"`~~ — the allowed literals are exactly
  `vector_search`, `tool_call`, `none`.

---

## Implementation Notes

### Pattern to Follow

The query does **not** traverse edges — it selects from an embedded array. Shape (adapt to
your property names from TASK-2370):

```yaml
traversal_patterns:
  article_in_force:
    description: >
      Resolve which wording of an article was legally in force on a given date.
    trigger_intents:
      - que decia el articulo
      - redaccion vigente
      - article in force
      - wording on date
    query_template: >
      FOR a IN @@articulo
        FILTER a._key == @articulo_key
        FOR v IN a.versions
          FILTER v.valid_from <= @as_of
          FILTER v.valid_to == null OR v.valid_to > @as_of
          RETURN v
    post_action: none
```

`@@articulo` is a **collection bind** (double-@), resolved by
`execute_traversal(..., collection_binds={"@articulo": "articulo"})`. `@as_of` and
`@articulo_key` are ordinary bind variables.

### Key Constraints

- **Boundary semantics are load-bearing.** `valid_from <= as_of` (inclusive) and
  `valid_to > as_of` (exclusive). An off-by-one here silently returns the wrong law —
  which is the single worst failure mode this feature has.
- A date **before** the first `valid_from` must return **nothing**, not version 0.
- The template must be read-only: no `INSERT`/`UPDATE`/`UPSERT` keywords anywhere, or
  `validate_aql` will reject it.
- Keep the traversal depth trivial — this selects from an array, so it is well within
  `ONTOLOGY_MAX_TRAVERSAL_DEPTH`.
- Dates should be compared in a single consistent representation (ISO `YYYY-MM-DD` strings
  are the simplest and sort correctly). Whatever you choose, the parser (TASK-2372) must emit
  the same representation — coordinate via the spec's `ArticleVersion` model.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml:86` — traversal-pattern shape, including `@@collection` binds
- `packages/ai-parrot/tests/knowledge/ontology/test_ontology_validators.py` — how `validate_aql` is exercised in existing tests

---

## Acceptance Criteria

- [ ] `article_in_force` appears in `merged.traversal_patterns` after `OntologyMerger.merge`
- [ ] Its `query_template` binds `@as_of` and `@articulo_key`, and uses the `@@articulo` collection bind
- [ ] `await validate_aql(pattern.query_template)` passes without raising
- [ ] The template contains no mutation keywords (asserted explicitly in a test)
- [ ] `post_action` is `"none"`
- [ ] `trigger_intents` is non-empty
- [ ] Boundary semantics documented in the pattern's `description` **and** encoded in the FILTER clauses
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py -v`

---

## Test Specification

```python
# additions to packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py
import pytest
from parrot.knowledge.ontology.validators import validate_aql


class TestArticleInForcePattern:
    def test_pattern_present(self, merged):
        assert "article_in_force" in merged.traversal_patterns

    def test_binds_declared(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template
        assert "@as_of" in tpl
        assert "@articulo_key" in tpl
        assert "@@articulo" in tpl

    @pytest.mark.asyncio
    async def test_passes_aql_validation(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template
        await validate_aql(tpl)   # must not raise

    def test_is_read_only(self, merged):
        tpl = merged.traversal_patterns["article_in_force"].query_template.upper()
        for kw in ("INSERT", "UPDATE", "REMOVE", "REPLACE", "UPSERT"):
            assert kw not in tpl

    def test_post_action_none(self, merged):
        assert merged.traversal_patterns["article_in_force"].post_action == "none"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` (§2 Overview, §7 Gotchas).
2. **Check dependencies** — TASK-2370 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing the AQL.
4. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
5. **Implement** the traversal pattern and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2371-article-in-force-traversal.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
