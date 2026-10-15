---
type: feature
base_branch: dev
feature_id: FEAT-679
projects: [ai-parrot]
tags: [database-agent, schema-plane, validation]
---

# Feature Specification: DatabaseAgent rejects unsupported `schema_plane` values

**Feature ID**: FEAT-679
**Date**: 2026-10-15
**Author**: Claude (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:ae4842999074 (discovered from review:TASK-3695).

---

## 1. Motivation & Business Requirements

### Problem Statement

The ledger issue reported two defects:

1. `docs/wiki/schema-plane.md` §11 described the wrong cache tier order and
   showed a non-existent `DatabaseAgent(schema_plane=SchemaPlaneConfig(...))`
   API. **Already fixed on `dev`** by commit 235e185b5 — §11 now documents
   `LRU → schema cache → Redis → schema plane → vector store` and the
   `schema_plane=".parrot/schema"` (str/Path or open `SchemaPlaneService`) form.
2. `DatabaseAgent._resolve_schema_plane`
   (`packages/ai-parrot/src/parrot/bots/database/agent.py:162`) only special-cases
   `None`, `str` and `Path`; any other object — e.g. the `SchemaPlaneConfig` the
   old docs suggested — is stored as-is and later assigned to
   `CachePartition.plane`. It fails only at the first `plane.get_table()` call,
   inside `CachePartition.get()`'s best-effort `except Exception`, so the error is
   downgraded to a warning on every lookup and the plane silently never works.

### Goals
- `DatabaseAgent(schema_plane=<unsupported>)` raises `TypeError` at construction,
  naming the accepted types.
- Accepted values are unchanged: `None`, `str`, `Path`, or any object exposing the
  `SchemaPlaneReader` surface (`get_table`, `put_table`, `list_tables` callables) —
  including `SchemaPlaneService` and test doubles.

### Non-Goals
- No change to `docs/wiki/schema-plane.md` (already correct).
- No change to `CachePartition` or the schema-plane service.

---

## 2. Architectural Design

In `_resolve_schema_plane`, after the `str`/`Path` branch, duck-type check the
value against the `SchemaPlaneReader` protocol's three methods (the protocol is
not `@runtime_checkable`, and the import must stay lazy). On failure raise
`TypeError(f"schema_plane must be None, a str/Path plane directory, or a SchemaPlaneReader (e.g. SchemaPlaneService); got {type(x).__name__}")`.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatabaseAgent.__init__` | caller | `self._schema_plane = self._resolve_schema_plane(schema_plane)` |
| `parrot.knowledge.wiki.schema.service.SchemaPlaneReader` | protocol | `get_table`, `put_table`, `list_tables` |

---

## 3. Module Breakdown

### Module 1: Fail-fast schema_plane validation
- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`,
  `packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py`
- **Responsibility**: reject unsupported values; regression tests.

---

## 4. Test Specification

`pytest packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py` passes,
including new cases: a `SchemaPlaneConfig`-like object and a plain `object()` raise
`TypeError`; existing service/path/None cases unchanged.

---

## 5. Acceptance Criteria
- [ ] Unsupported `schema_plane` raises `TypeError` at `DatabaseAgent(...)` construction.
- [ ] `None`, `str`, `Path`, and `SchemaPlaneReader`-shaped objects keep working.
- [ ] `test_agent_schema_plane.py` passes.

---

## 6. Codebase Contract
- `packages/ai-parrot/src/parrot/bots/database/agent.py:162` — `def _resolve_schema_plane(self, schema_plane: Any) -> Any`
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py:36` — `class SchemaPlaneReader(Protocol)` with async `get_table`, `put_table`, `list_tables` (not `@runtime_checkable`)
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/models.py` — `SchemaPlaneConfig` (pydantic model, no `get_table`)

## 7. Open Questions
None.
