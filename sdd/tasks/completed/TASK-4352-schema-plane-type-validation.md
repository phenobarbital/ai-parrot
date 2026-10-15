# TASK-4352: DatabaseAgent rejects unsupported schema_plane values

**Feature**: FEAT-679 — DatabaseAgent rejects unsupported `schema_plane` values
**Spec**: `sdd/specs/database-agent-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2/§3 Module 1. Resolves ledger issue:ae4842999074 (the docs half
was already fixed by 235e185b5). `_resolve_schema_plane` stores any non-str/Path
object as the plane; an unsupported value (e.g. `SchemaPlaneConfig`) only fails
later inside `CachePartition.get()`'s swallowed `except`, so the plane silently
never works.

---

## Scope

- In `_resolve_schema_plane`, after the `str`/`Path` branch, raise `TypeError` unless
  the value has callable `get_table`, `put_table` and `list_tables`.
- Add regression tests: `SchemaPlaneConfig`-like object and `object()` raise `TypeError`.

**NOT in scope**: docs, `CachePartition`, schema-plane service changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | fail-fast type check |
| `packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database import DatabaseAgent                    # tests already use it
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig  # imported by service.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/agent.py:162
def _resolve_schema_plane(self, schema_plane: Any) -> Any
# packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py:36 (not runtime_checkable)
class SchemaPlaneReader(Protocol):
    async def get_table(self, origin, schema, table): ...
    async def put_table(self, origin, dialect, metadata): ...
    async def list_tables(self, origin, schema=None): ...
```

### Does NOT Exist
- `SchemaPlaneConfig.root` / `SchemaPlaneConfig.origin` as a plane handle
- `@runtime_checkable` on `SchemaPlaneReader` (do not use `isinstance` against it)

---

## Acceptance Criteria
- [ ] Unsupported `schema_plane` raises `TypeError` at construction.
- [ ] Existing tests in `test_agent_schema_plane.py` still pass.

## Validation Commands
```bash
pytest packages/ai-parrot/tests/bots/database/test_agent_schema_plane.py -q
```

## Test Specification
New parametrized test `test_unsupported_plane_raises_type_error` over a
`SchemaPlaneConfig`-like stand-in and `object()`.

## Agent Instructions
Implement exactly the scope above, run the validation command, commit only the two files.

## Completion Note
**Completed by**: Claude (sdd-fix lane), 2026-10-15
**Commit**: 7aacbe457

The ledger issue had two halves. The docs half (wrong tier order, non-existent
`DatabaseAgent(schema_plane=SchemaPlaneConfig(...))` example in
`docs/wiki/schema-plane.md` §11) was already fixed on `dev` by 235e185b5 — no doc
change needed. The code half was live: `_resolve_schema_plane` now raises `TypeError`
unless the value is `None`, `str`/`Path`, or exposes callable `get_table`/`put_table`/
`list_tables` (duck-typed; `SchemaPlaneReader` is not `@runtime_checkable`).

Validation: `test_agent_schema_plane.py` → 5 passed (2 new); full
`packages/ai-parrot/tests/bots/database` → 205 passed, 9 skipped. `ruff check` clean.
Resolves ledger issue:ae4842999074.
