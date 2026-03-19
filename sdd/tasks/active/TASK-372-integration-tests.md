# TASK-372: Integration Tests — Full E2E Pipeline

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-355, TASK-358, TASK-362, TASK-363, TASK-365, TASK-366, TASK-369, TASK-370, TASK-371
**Assigned-to**: —

---

## Context

> End-to-end integration tests covering the full ontology pipeline: YAML loading → merge →
> graph initialization → data extraction → edge discovery → intent resolution → enriched context.
> Implements spec Integration Tests section.

---

## Scope

### Create `tests/knowledge/test_ontology_integration.py`

**Test 1: `test_e2e_yaml_to_graph`**
- Load `base.ontology.yaml` + `field_services.ontology.yaml` from defaults.
- Merge into `MergedOntology`.
- Initialize tenant (mocked ArangoDB).
- Upsert sample employee/project/portal nodes.
- Run relation discovery with sample data.
- Verify correct edges created.

**Test 2: `test_e2e_intent_to_context`**
- Set up merged ontology with traversal patterns.
- Query "what is my portal?" → fast path → graph traversal → enriched context.
- Verify `EnrichedContext` has graph data and correct post-action.

**Test 3: `test_e2e_refresh_pipeline`**
- Set up initial graph state with sample data.
- Add new records + modify existing + remove one.
- Run refresh pipeline.
- Verify: new nodes inserted, changed updated, removed soft-deleted.
- Verify edge rediscovery ran only for changed nodes.
- Verify cache invalidated.

**Test 4: `test_e2e_mixin_disabled`**
- Set `ENABLE_ONTOLOGY_RAG=False`.
- Call `process()` → returns `EnrichedContext(source="disabled")`.

**Test 5: `test_e2e_graceful_degradation`**
- Mock ArangoDB as unavailable.
- Call `process()` → returns `EnrichedContext(source="vector_only")` without error.

### Fixtures
- Sample employee data (5 records).
- Sample project/portal data (3 records each).
- Mocked ArangoDB client.
- Mocked LLM client (for AI-assisted discovery and LLM intent path).
- Mocked Redis client.

---

## Acceptance Criteria

- [ ] All 5 integration tests pass.
- [ ] Tests use mocked external services (ArangoDB, LLM, Redis) — no real API calls.
- [ ] Tests cover the full pipeline from YAML to enriched context.
- [ ] Refresh pipeline delta sync verified with assertions on insert/update/delete counts.
- [ ] Graceful degradation tested.
- [ ] Tests run with: `pytest tests/knowledge/test_ontology_integration.py -v`.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `tests/knowledge/test_ontology_integration.py` | **Create** |
