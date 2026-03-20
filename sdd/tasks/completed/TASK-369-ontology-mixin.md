# TASK-369: OntologyRAGMixin — Agent Pipeline Orchestrator

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (4-8h)
**Depends-on**: TASK-363, TASK-366, TASK-367, TASK-368
**Assigned-to**: —

---

## Context

> Agent mixin that orchestrates the full ontology pipeline — tenant resolution, intent
> detection, graph traversal, post-action routing, caching. Also registers ontology schema
> as a PromptBuilder composable layer.
> Implements spec Modules 12 and 13.

---

## Scope

### Create `parrot/knowledge/ontology/mixin.py`

`OntologyRAGMixin`:
- `__init__` params: `tenant_manager`, `graph_store`, `vector_store`, `intent_resolver_factory`, `cache`.
- `async process(self, query: str, user_context: dict, tenant_id: str) -> EnrichedContext`:
  1. Check `ENABLE_ONTOLOGY_RAG` — if False, return `EnrichedContext(source="disabled")`.
  2. Resolve tenant via `tenant_manager.resolve(tenant_id)`.
  3. Create intent resolver via `intent_resolver_factory(ctx.ontology)`.
  4. Resolve intent.
  5. If `vector_only` → return `EnrichedContext(source="vector_only")`.
  6. Check cache → return if hit.
  7. Execute graph traversal via `graph_store.execute_traversal()`.
  8. Post-action routing:
     - `vector_search`: Extract field from graph result, query vector store.
     - `tool_call`: Build tool hint string from graph context.
     - `none`: Pass graph result directly.
  9. Build `EnrichedContext`.
  10. Cache result.
  11. Return.

- Graceful degradation: if ArangoDB is unavailable, log warning and return `vector_only`.

### PromptBuilder Integration

In `configure()` (or `__init__`):
- Register an `"ontology_schema"` layer with PromptBuilder.
- Layer renders `MergedOntology.build_schema_prompt()`.
- Render at `RenderPhase.CONFIGURE` (static per-tenant, not per-request).

### Update `parrot/knowledge/ontology/__init__.py`

Export `OntologyRAGMixin`, `TenantOntologyManager`, `OntologyGraphStore`, `OntologyIntentResolver`.

---

## Acceptance Criteria

- [ ] `process()` returns `EnrichedContext` with graph + vector + tool hint.
- [ ] Cache hit skips graph traversal and returns cached result.
- [ ] Post-action routing works for all three modes (vector_search, tool_call, none).
- [ ] `ENABLE_ONTOLOGY_RAG=False` makes mixin a no-op.
- [ ] ArangoDB unavailability degrades gracefully to `vector_only`.
- [ ] Ontology schema registered as PromptBuilder layer at `RenderPhase.CONFIGURE`.
- [ ] Unit tests: graph query flow, vector-only flow, cache hit, degradation.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/mixin.py` | **Create** |
| `parrot/knowledge/ontology/__init__.py` | **Modify** — add exports |
| `tests/knowledge/test_ontology_mixin.py` | **Create** |
