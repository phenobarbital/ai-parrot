# TASK-360: Ontology Pydantic Schema Models

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-356
**Assigned-to**: —

---

## Context

> Define all Pydantic v2 models for YAML validation and runtime representation.
> Implements spec Module 5.

---

## Scope

### Create `parrot/knowledge/ontology/schema.py`

All models with `model_config = ConfigDict(extra="forbid")`:

1. **`PropertyDef(BaseModel)`** — type, required, unique, default, enum, description.
2. **`EntityDef(BaseModel)`** — collection, source, key_field, properties, vectorize, extend.
3. **`DiscoveryRule(BaseModel)`** — source_field, target_field, match_type (Literal), threshold.
4. **`DiscoveryConfig(BaseModel)`** — strategy (Literal), rules list.
5. **`RelationDef(BaseModel)`** — from_entity (alias="from"), to_entity (alias="to"), edge_collection, properties, discovery. Use `populate_by_name=True`.
6. **`TraversalPattern(BaseModel)`** — description, trigger_intents, query_template, post_action (Literal), post_query.
7. **`OntologyDefinition(BaseModel)`** — name, version, extends, description, entities dict, relations dict, traversal_patterns dict. Root model for a single YAML layer.
8. **`MergedOntology(BaseModel)`** — name, version, entities, relations, traversal_patterns, layers list, merge_timestamp.
   - `get_entity_collections() -> list[str]`
   - `get_edge_collections() -> list[str]`
   - `get_vectorizable_fields(entity_name) -> list[str]`
   - `build_schema_prompt() -> str` — natural language description for LLM.
9. **`TenantContext(BaseModel)`** — tenant_id, arango_db, pgvector_schema, ontology (MergedOntology).
10. **`ResolvedIntent(BaseModel)`** — action (Literal), pattern, aql, params, collection_binds, post_action, post_query, source.
11. **`EnrichedContext(BaseModel)`** — source, graph_context, vector_context, tool_hint, intent, metadata.

---

## Acceptance Criteria

- [ ] All models use `extra="forbid"` to catch typos in YAML.
- [ ] `RelationDef` uses `Field(alias="from")` / `Field(alias="to")` with `populate_by_name=True`.
- [ ] `MergedOntology.build_schema_prompt()` returns a formatted string listing entities, relations, and patterns.
- [ ] `TraversalPattern.post_action` is `Literal["vector_search", "tool_call", "none"]`.
- [ ] `ResolvedIntent.action` is `Literal["graph_query", "vector_only"]`.
- [ ] All models have Google-style docstrings.
- [ ] Unit tests validate model construction and rejection of invalid data.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/schema.py` | **Create** |
| `tests/knowledge/test_ontology_schema.py` | **Create** |
