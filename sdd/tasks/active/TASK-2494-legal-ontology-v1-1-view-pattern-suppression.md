# TASK-2494: Legal ontology v1.1 — `legal_articulos_view`, `search_articles` pattern, `SpanSuppression` entity

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2493
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. With `search_views:` supported by the schema (TASK-2493),
the legal ontology declares the view over article wordings + norm titles, the
declarative `search_articles` traversal pattern (`SEARCH … BM25()` + temporal
predicate — the load-bearing filter that keeps repealed wordings out of the
dossier for the wrong `as_of`), and the append-only `SpanSuppression` entity
whose collection (`span_suppressions`) TASK-2495 writes to. Bump the ontology
`version` to `"1.1"`.

Blocks TASK-2495, TASK-2496, TASK-2498.

---

## Scope

- Edit `legal.ontology.yaml`:
  - `version: "1.1"`.
  - Add entity `SpanSuppression` (`collection: span_suppressions`,
    `key_field: suppression_id`) with properties `suppression_id` (string,
    required, unique), `execution_id` (string, required), `suppressed_text`
    (string, required), `claimed_anchors` (list), `reason` (string,
    required), `user_id` (string), `created_at` (datetime, required) — check
    the spec §3 M3 YAML block and match the style of existing entities
    (`source` wiring: this entity has NO data source — it is written by the
    application; verify how entities without a source are declared in other
    bundled ontologies and follow that shape).
  - Add top-level `search_views:` with `legal_articulos_view` linking
    `Articulo` (`versions[*].text`, analyzers `["text_es", "text_en"]`) and
    `Norma` (`titulo`, same analyzers).
  - Add `traversal_patterns.search_articles` with the description,
    trigger intents, and `query_template` from spec §3 M3 verbatim
    (view name and analyzer names are LITERALS in the template — they cannot
    be bind vars). `post_action: none`.
- If TASK-2493's `text_es` spike found the analyzer missing on the target
  server, apply the fallback recorded there and note it.
- Tests:
  - Extend `packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py`:
    entity `SpanSuppression` present with collection `span_suppressions`;
    `search_views["legal_articulos_view"]` has the two links; pattern
    `search_articles` present; `version == "1.1"`.
  - `test_search_articles_pattern_passes_validate_aql`: `await validate_aql(pattern.query_template)`
    returns the template unchanged.
  - Regression: `article_in_force` pattern unchanged.

**NOT in scope**: Python helper `search_articles()` (TASK-2496); the
`SuppressionLog` writer (TASK-2495); provisioning code (TASK-2493).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | MODIFY | v1.1: entity + view + pattern |
| `packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py` | MODIFY | new assertions + `validate_aql` test |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev`.

### Verified Imports
```python
from parrot.knowledge.ontology.validators import validate_aql          # validators.py:36  (async)
from parrot.knowledge.ontology.exceptions import AQLValidationError     # exceptions.py:27
from parrot.knowledge.ontology.schema import SearchViewDef              # created by TASK-2493
```

### Existing Signatures to Use
```yaml
# legal.ontology.yaml (v1.0) — current layout
name: legal            # :1
version: "1.0"         # :2   → "1.1"
entities:              # :11   Norma(:12) Articulo(:38, collection articulo, versions list :60) Materia(:65)
relations:             # :79   modifica deroga pertenece_a
traversal_patterns:    # :102  article_in_force(:103) — bind vars @@articulo, @articulo_key, @as_of
```
```python
# validators.py:13-33 — validate_aql rejects ONLY:
#   INSERT|UPDATE|REMOVE|REPLACE|UPSERT ; _system|_graphs|_modules|_analyzers|_jobs|_queues ;
#   APPLY(|CALL(|V8( ; traversal depth > max_depth.  SEARCH / BM25 / TOKENS / ANALYZER pass.
async def validate_aql(aql: str, max_depth: int | None = None) -> str   # :36

# schema.py:263 — TraversalPattern fields: description, trigger_intents, query_template,
#   post_action, post_query (+ authorization). extra="forbid" (:297).
```
```python
# tests/knowledge/ontology/test_legal_ontology.py — existing `merged` fixture and tests:
#   test_entities_present(:21) test_relations_present(:25) test_collections(:29)
#   test_versions_is_list_type(:33) test_source_wiring(:37)
```

### Does NOT Exist
- ~~`legal_articulos_view` / `search_articles` / `SpanSuppression`~~ — this task creates them.
- ~~Bind-var view names (`FOR a IN @@view`) or bind-var analyzers inside `ANALYZER()`/`TOKENS()`~~ — ArangoDB forbids both; literals only.
- ~~A `chunk` collection or `vectorize:` on `Articulo`~~ — R14: none, and do not add.
- ~~`PropertyDef.type` nested-model support~~ — `versions` stays `type: list` (shape enforced in Python).

---

## Implementation Notes

### Pattern to Follow
```yaml
search_views:
  legal_articulos_view:
    links:
      - entity: Articulo
        fields:
          - path: "versions[*].text"
            analyzers: ["text_es", "text_en"]
      - entity: Norma
        fields:
          - path: "titulo"
            analyzers: ["text_es", "text_en"]

traversal_patterns:
  search_articles:
    query_template: >
      FOR a IN legal_articulos_view
        SEARCH ANALYZER(a.versions.text IN TOKENS(@query, "text_es"), "text_es")
            OR ANALYZER(a.versions.text IN TOKENS(@query, "text_en"), "text_en")
        LET score = BM25(a)
        SORT score DESC
        LIMIT @limit
        FOR v IN a.versions
          FILTER v.valid_from <= @as_of
          FILTER v.valid_to == null OR v.valid_to > @as_of
          RETURN { articulo_key: a._key, norma_ref: a.norma_ref,
                   numero: a.numero, version: v, score: score }
    post_action: none
```

### Key Constraints
- The temporal `FILTER` pair is load-bearing (spec §7 gotchas) — copy the
  boundary semantics from `article_in_force` (inclusive `valid_from`,
  exclusive `valid_to`).
- `Norma.titulo` is in the view for recall/ranking only; the pattern
  returns `articulo` rows exclusively.
- `SearchViewLink.entity` is the entity NAME (`Articulo`), not the collection.

### References in Codebase
- `legal.ontology.yaml:102-140` — `article_in_force` as the style template
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:857-878` — SEARCH/BM25 AQL shape

---

## Acceptance Criteria

- [ ] `legal` ontology merges cleanly (`TenantOntologyManager(...).resolve(..., domain="legal")`) with `version == "1.1"`
- [ ] `merged.search_views["legal_articulos_view"]` has links for `Articulo` and `Norma` with the declared paths/analyzers
- [ ] `merged.entities["SpanSuppression"].collection == "span_suppressions"`
- [ ] `await validate_aql(merged.traversal_patterns["search_articles"].query_template)` returns it unchanged
- [ ] `article_in_force` pattern and all existing `test_legal_ontology.py` tests unchanged/passing
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/ontology/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_legal_ontology.py (additions)
import pytest
from parrot.knowledge.ontology.validators import validate_aql


def test_version_bumped(merged):
    assert merged.version == "1.1"


def test_search_view_declared(merged):
    view = merged.search_views["legal_articulos_view"]
    assert {l.entity for l in view.links} == {"Articulo", "Norma"}


def test_span_suppression_entity(merged):
    assert merged.entities["SpanSuppression"].collection == "span_suppressions"


async def test_search_articles_pattern_passes_validate_aql(merged):
    tpl = merged.traversal_patterns["search_articles"].query_template
    assert await validate_aql(tpl) == tpl
    assert "legal_articulos_view" in tpl and "BM25(" in tpl
    assert "v.valid_to == null OR v.valid_to > @as_of" in tpl
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M3, §7 gotchas)
2. **Check dependencies** — TASK-2493 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `SearchViewDef` exists in `schema.py` and how TASK-2493 named things
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2494-legal-ontology-v1-1-view-pattern-suppression.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
