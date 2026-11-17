---
id: FC-004
query_id: Q004
type: grep
intent: "Does AQL leak outside the store (callers building AQL strings, traversal patterns stored in ontology definitions)?"
executed_at: 2026-11-06T13:35:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — AQL is part of the ontology *data*, the LLM prompt path and the validators, not just the store

## Summary

`grep -rnE "aql|AQL|OUTBOUND|INBOUND|DynamicQuery\(|execute_query\(|execute_pattern\(|query_templates?" packages/ai-parrot/src/parrot/knowledge/ontology`. AQL leaks through four layers above the store: (1) **ontology YAML** — every `traversal_patterns.*.query_template` in the bundled defaults is literal AQL (`FOR v IN 1..1 OUTBOUND @user_id @@reports_to RETURN v`), including patterns that query an ArangoSearch view by name; (2) **intent resolution** — `intent.py` defaults `dialect="aql"` and the LLM is asked to emit dynamic AQL (legacy `"aql"` response key still accepted); (3) **validation** — `validators.py` is an AQL safety validator registered as `register_query_validator("aql", validate_aql)`, reused by `schema_overlay/validator.py`; (4) **`ResolvedIntent.dialect`** defaults to `"aql"`. A per-dialect hook exists (`TraversalPattern.query_templates: dict[str, str]`, `register_query_validator`), so the design *anticipates* other dialects, but only `aql` content exists.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml`
  lines: 116-149
  symbol: `traversal_patterns`
  excerpt: |
    traversal_patterns:
      find_manager:
        trigger_intents: [my manager, ...]
        query_template: >
          FOR v IN 1..1 OUTBOUND @user_id @@reports_to RETURN v
      find_team:
        query_template: >
          FOR dept IN 1..1 OUTBOUND @user_id @@belongs_to_dept
            FOR teammate IN 1..1 INBOUND dept._id @@belongs_to_dept
              FILTER teammate._id != @user_id

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml`
  lines: 214-222
  symbol: `traversal_patterns` (concept_is_a expansion)
  excerpt: |
    214:    query_template: |
    216:        FOR cid IN @topic_ids
    218:          FOR sub IN 0..3 INBOUND base._id @@concept_is_a
    221:      FOR doc IN documents
    222:        FOR edge IN doc_covers_concept

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
  lines: 145-205
  symbol: `search_views` + view-bound pattern
  excerpt: |
    145:search_views:
    173:    query_template: >
    174:      FOR a IN @@articulo
    198:    query_template: >
    199:      FOR a IN legal_articulos_view
    205:        FOR v IN a.versions

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py`
  lines: 76-265
  symbol: `dialect` handling in the intent resolver
  excerpt: |
    86:        dialect: str = "aql",
    201:            if isinstance(parsed, dict) and not parsed.get("query") and parsed.get("aql"):
    202:                if self._dialect == "aql":
    204:                    parsed = {**parsed, "query": parsed["aql"]}
    265:        return (pattern.query_templates or {}).get(self._dialect) or pattern.query_template

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py`
  lines: 36-144
  symbol: `validate_aql`
  excerpt: |
    36:async def validate_aql(
    71:    match = _MUTATION_PATTERN.search(aql)
    78:    match = _SYSTEM_COLLECTIONS.search(aql)
    85:    match = _JS_PATTERN.search(aql)
    93:    for depth_match in _TRAVERSAL_DEPTH_PATTERN.finditer(aql):
    144:register_query_validator("aql", validate_aql)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/validator.py`
  lines: 42-131
  symbol: `_check_aql`
  excerpt: |
    42:from parrot.knowledge.ontology.validators import validate_aql
    125:        query_template = overlay.definition.get("query_template", "")
    126:        aql_check = await _check_aql(query_template)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 561-575
  symbol: `ResolvedIntent.dialect`
  excerpt: |
    561:        dialect: Query dialect of ``query`` (default ``aql``).
    575:    dialect: str = "aql"

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 164-166
  symbol: `OntologyRAGMixin` dialect resolution
  excerpt: |
    164:        """Return the query dialect of the configured graph store (default ``aql``)."""
    166:        return dialect if isinstance(dialect, str) and dialect else "aql"

## Notes

- Per-file match counts: `graph_store.py` 62, `validators.py` 24, `schema_overlay/validator.py` 22, `mixin.py` 13, `intent.py` 10, `schema.py` 7, `contracts.py` 3, `merger.py` 3, `exceptions.py` 3, `authorization.py` 1, `schema_overlay/models.py` 1.
- Bundled ontology YAMLs carrying AQL: `defaults/base.ontology.yaml`, `defaults/knowledge.ontology.yaml`, `defaults/domains/field_services.ontology.yaml` (L93-106), `defaults/domains/legal.ontology.yaml`. Tenant/client YAMLs under `ONTOLOGY_DIR` (outside the repo) will carry more — they are data that a backend swap must migrate or re-template.
- This directly contradicts the draft's non-goal "no free Cypher/SPARQL queries by agents": today the ontology pipeline's *dynamic path* is exactly an LLM-generated free query, validated and executed against the graph.
