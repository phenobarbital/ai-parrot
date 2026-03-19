# TASK-366: Dual-Path Intent Resolver

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-360, TASK-362, TASK-364
**Assigned-to**: —

---

## Context

> Dual-path intent resolution: fast-path keyword matching + LLM-based classification.
> Implements spec Module 11.

---

## Scope

### Create `parrot/knowledge/ontology/intent.py`

`OntologyIntentResolver`:
- `__init__(self, ontology: MergedOntology, llm_client, graph_store: OntologyGraphStore)`.
- Pre-build `_schema_prompt` via `ontology.build_schema_prompt()`.

- `async resolve(self, query: str, user_context: dict) -> ResolvedIntent`:

  **Fast path** (~0ms):
  - `query_lower = query.lower()`
  - Scan `ontology.traversal_patterns` — if any `trigger_intent` keyword is in `query_lower`, return `ResolvedIntent(action="graph_query", source="fast_path", ...)` with the predefined pattern.

  **LLM path** (~200-800ms):
  - Send query + `_schema_prompt` to LLM using structured output (`IntentDecision` Pydantic model).
  - Model: `ONTOLOGY_AQL_MODEL` from conf.
  - If LLM says `graph_query` with known pattern → return it.
  - If LLM says `graph_query` with dynamic AQL → validate via `graph_store.validate_aql()` → return.

  **Fallback**:
  - Return `ResolvedIntent(action="vector_only")`.

- `_build_collection_binds() -> dict` — map `@@collection` names from ontology.
- `_build_intent_prompt() -> str` — system prompt with schema + classification instructions.

`IntentDecision(BaseModel)` — structured output for LLM:
- `action: Literal["graph_query", "vector_only"]`
- `pattern: str | None` — known pattern name or "dynamic"
- `aql: str | None` — dynamic AQL (only if pattern="dynamic")
- `suggested_post_action: str | None`

---

## Acceptance Criteria

- [ ] Fast path matches keywords in <1ms and returns predefined pattern.
- [ ] LLM path uses `ONTOLOGY_AQL_MODEL` and structured output.
- [ ] Dynamic AQL from LLM is validated via `validate_aql()` before return.
- [ ] Fallback returns `vector_only` when nothing matches.
- [ ] `_build_collection_binds()` maps all entity/relation collections.
- [ ] Unit tests: fast path match, LLM known pattern, LLM dynamic AQL, fallback.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/intent.py` | **Create** |
| `tests/knowledge/test_ontology_intent.py` | **Create** |
