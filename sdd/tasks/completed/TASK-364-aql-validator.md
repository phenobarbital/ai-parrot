# TASK-364: AQL Security Validator

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-363
**Assigned-to**: —

---

## Context

> Validate LLM-generated AQL for safety — no mutations, depth limit, no system collections,
> no JS execution. Implements spec Module 9.

---

## Scope

### Create `parrot/knowledge/ontology/validators.py`

`async validate_aql(aql: str, max_depth: int = None) -> str`:
- Use `ONTOLOGY_MAX_TRAVERSAL_DEPTH` from conf if `max_depth` not provided.
- **Checks**:
  1. No mutation keywords: `INSERT`, `UPDATE`, `REMOVE`, `REPLACE`, `UPSERT` (case-insensitive regex).
  2. Traversal depth: parse `..N` from AQL traversal syntax, reject if N > max_depth.
  3. No system collections: `_system`, `_graphs`, `_modules`, `_analyzers`.
  4. No inline JavaScript: `APPLY`, `CALL`, `V8` keywords.
  5. (Optional) Query plan analysis via AQL `explain()` when ArangoDB client is available.
- Returns validated AQL (unchanged) or raises `AQLValidationError`.

---

## Acceptance Criteria

- [ ] Mutations (`INSERT`, `UPDATE`, `REMOVE`, `REPLACE`, `UPSERT`) are rejected.
- [ ] Traversal depth exceeding `ONTOLOGY_MAX_TRAVERSAL_DEPTH` is rejected.
- [ ] System collection access is rejected.
- [ ] JS execution keywords are rejected.
- [ ] Valid read-only AQL passes through unchanged.
- [ ] `AQLValidationError` includes which check failed.
- [ ] Unit tests for each rejection case and for valid AQL.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/validators.py` | **Create** |
| `tests/knowledge/test_ontology_validators.py` | **Create** |
