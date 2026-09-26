# TASK-3786: UISurfaceRecord.refreshable + conditional update_envelope(expected_updated_at)

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (store half), AC8, AC15 (S11). A persisted linked surface is refreshable by
its descriptor even without a recipe, so `UISurfaceRecord.refreshable` widens to
`recipe_name is not None or has_data_sources(envelope)`. Renderer intervals, manual refreshes
and server refreshes can race; today `update_envelope` is an unconditional update by id
(`models/ui_surfaces.py:648-656`), so a stale snapshot can overwrite a newer one. This task adds
an optimistic-concurrency predicate (`WHERE … AND updated_at = $expected`) used by the descriptor
refresh path in TASK-3787.

---

## Scope

- Widen `UISurfaceRecord.refreshable` (L84-86) using `has_data_sources` from TASK-3769.
- Add keyword-only `expected_updated_at: datetime | None = None` to
  `PgUISurfaceStore.update_envelope`; return `bool` (True when a row was updated).
  `expected_updated_at is None` ⇒ exactly today's SQL (`_UPDATE_ENVELOPE_SQL`, unchanged).
  Otherwise use a NEW constant `_UPDATE_ENVELOPE_IF_UNCHANGED_SQL` with the extra predicate.
- Unit tests using the in-memory fake-connection idiom of `test_ui_surfaces_store.py`
  (own local fake — do not edit that file).

**NOT in scope**: handler wiring and the 409 response (TASK-3787); DDL changes (spec non-goal:
no ui_surfaces DDL change); `update_visibility` or any other query.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | MODIFY | `refreshable` widening; conditional `update_envelope` + new SQL constant |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_store.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, UISurfaceKind, PgUISurfaceStore   # models/ui_surfaces.py:63,41,449
from parrot.handlers.models import ui_surfaces as m   # test idiom (test_ui_surfaces_store.py:17)
from parrot.outputs.a2ui.linked import has_data_sources   # TASK-3769 (linked/__init__.py) — accepts CreateSurface | dict
from parrot.outputs.a2ui.models import CreateSurface       # models.py:446 (tests)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
from datetime import UTC, datetime, timedelta       # L24 (already imported)
class UISurfaceRecord(BaseModel):                   # L63; envelope: dict[str, Any] L69; updated_at: datetime L81
    @property
    def refreshable(self) -> bool:                  # L84-86: return self.recipe_name is not None
_UPDATE_ENVELOPE_SQL = """
UPDATE navigator.ui_surfaces
SET envelope = $2::jsonb, recipe_params = $3::jsonb, updated_at = NOW()
WHERE surface_id = $1
RETURNING surface_id
"""                                                  # L250-255
def _as_uuid(value) -> uuid.UUID | None             # module helper used by every store method
class PgUISurfaceStore:                              # L449
    async def _ensure_ready(self) -> None            # L470
    def _get_db(self)                                # AsyncDB("pg") per-call idiom
    async def update_visibility(...) -> bool         # L616-646 — `result = await conn.fetchval(...); return result is not None` precedent
    async def update_envelope(self, surface_id: str, envelope: dict[str, Any], recipe_params: dict[str, Any]) -> None:   # L648-656
        # surface_uuid = _as_uuid(surface_id); None → return; await self._ensure_ready(); db = self._get_db();
        # async with await db.connection() as conn: await conn.fetchval(_UPDATE_ENVELOPE_SQL, surface_uuid, envelope, recipe_params)

# packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py — fake idiom: _FakeConnCtx L27, _FakeConn L114
#   (fetchval dispatches on `sql == m._UPDATE_ENVELOPE_SQL` L161), _FakeAsyncDB L257,
#   pg_store fixture monkeypatches store._get_db (L271-274). Copy the minimal shape locally.
```

### Does NOT Exist
- ~~`update_envelope(expected_updated_at=…)`~~ — added here.
- ~~`_UPDATE_ENVELOPE_IF_UNCHANGED_SQL`~~ — added here.
- ~~`UISurfaceRecord.has_data_sources`~~ — not a field/property; call the core function.
- ~~any `version`/`etag` column~~ — none; `updated_at` IS the concurrency token (no DDL change allowed).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#UISurfaceRecord.refreshable",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore.update_envelope",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore.update_visibility"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Existing callers of `update_envelope` (the recipe refresh path, `handlers/ui_surfaces.py:638`) pass no
  `expected_updated_at` and ignore the return — keep the old SQL for them byte-for-byte (the existing
  store test's fake matches on `m._UPDATE_ENVELOPE_SQL` identity).
- Timestamp equality: `updated_at` is `TIMESTAMPTZ`; pass the `datetime` read from the record (asyncpg round-trips
  microseconds). Do not stringify.
- `has_data_sources` is a core import at module top — core is a dependency of ai-parrot-server, so this is the
  allowed import direction.

---

## Implementation Blueprint

### Steps (in order)
1. Import `has_data_sources` — *why*: `refreshable` needs it.
2. Widen `refreshable` — *why*: AC8, surfaces with sources and no recipe become refreshable.
3. Add `_UPDATE_ENVELOPE_IF_UNCHANGED_SQL` right after `_UPDATE_ENVELOPE_SQL` — *why*: keep the old constant untouched for the recipe lane and its tests.
4. Make `update_envelope` conditional + `-> bool` — *why*: S11, the loser of a race gets 409 in TASK-3787.
5. Tests.

### `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -c 'from parrot.conf import default_dsn' packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py)
# AFTER — insert below `from parrot.conf import default_dsn` (verified: models/ui_surfaces.py:30)
from parrot.outputs.a2ui.linked import has_data_sources
```

### `ui_surfaces.py` (MODIFY) — refreshable
```python
# occurrences: 1 (verified: grep -c '    def refreshable(self) -> bool:' packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py)
# REPLACE models/ui_surfaces.py:84-86
    @property
    def refreshable(self) -> bool:
        """Refreshable via ``RecipeRunner`` replay (recipe_ref) or via its linked data-source descriptor."""
        return self.recipe_name is not None or has_data_sources(self.envelope)
```

### `ui_surfaces.py` (MODIFY) — conditional SQL
```python
# occurrences: 1 (verified: grep -c '_UPDATE_ENVELOPE_SQL = """' packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py)
# AFTER — insert below the closing `"""` of `_UPDATE_ENVELOPE_SQL` (verified: models/ui_surfaces.py:250-255)

_UPDATE_ENVELOPE_IF_UNCHANGED_SQL = """
UPDATE navigator.ui_surfaces
SET envelope = $2::jsonb, recipe_params = $3::jsonb, updated_at = NOW()
WHERE surface_id = $1 AND updated_at = $4
RETURNING surface_id
"""
```

### `ui_surfaces.py` (MODIFY) — update_envelope
```python
# occurrences: 1 (verified: grep -c '    async def update_envelope(self, surface_id: str, envelope: dict\[str, Any\], recipe_params: dict\[str, Any\]) -> None:' models/ui_surfaces.py)
# REPLACE models/ui_surfaces.py:648-656
    async def update_envelope(
        self,
        surface_id: str,
        envelope: dict[str, Any],
        recipe_params: dict[str, Any],
        *,
        expected_updated_at: datetime | None = None,
    ) -> bool:
        """Replace ``envelope``/``recipe_params`` in place, bumping ``updated_at``.

        With ``expected_updated_at`` the update is conditional (optimistic concurrency, FEAT-598 S11): it only
        applies when the row's ``updated_at`` still equals the value the caller read; a newer snapshot wins.

        Returns:
            ``True`` when a row was updated; ``False`` for an unknown surface or a lost race.
        """
        surface_uuid = _as_uuid(surface_id)
        if surface_uuid is None:
            return False
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if expected_updated_at is None:
                result = await conn.fetchval(_UPDATE_ENVELOPE_SQL, surface_uuid, envelope, recipe_params)
            else:
                result = await conn.fetchval(
                    _UPDATE_ENVELOPE_IF_UNCHANGED_SQL, surface_uuid, envelope, recipe_params, expected_updated_at
                )
        return result is not None
```
**Why**: `fetchval` + `RETURNING` → `None` when no row matched, the same idiom as `update_visibility`.

### `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_store.py` (CREATE)
```python
"""FEAT-598 M8 — refreshable widening + conditional update_envelope (spec §4)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from parrot.handlers.models import ui_surfaces as m

pytestmark = pytest.mark.asyncio


# FILL IN: minimal local fake (conn.fetchval dispatching on m._UPDATE_ENVELOPE_SQL and
#          m._UPDATE_ENVELOPE_IF_UNCHANGED_SQL against an in-memory {uuid: row} with "updated_at"), plus a pg_store
#          fixture patching store._get_db and store._ensure_ready — bounded by the test_ui_surfaces_store.py idiom
#          (copy, do not import its private helpers).


def test_refreshable_with_data_sources(): ...          # FILL IN: no recipe + linked envelope → True
def test_refreshable_baked_without_recipe(): ...       # FILL IN: no recipe + no sources → False (unchanged)
async def test_update_envelope_expected_updated_at(): ...   # FILL IN: matching → True + row changed; stale → False, row untouched
async def test_update_envelope_unconditional_unchanged(): ...  # FILL IN: no expected → old SQL constant used, True
async def test_update_envelope_unknown_surface(): ...  # FILL IN: invalid uuid → False
```
Build the linked envelope dict as `{"surfaceId": …, "components": [...], "dataModel": {...}, "metadata": {"extensions": {"parrot_data_sources": {...}}}}`
using TASK-3769's `LinkedDataSource` dumped with `model_dump(mode="json")` (the `linked_source` fixture lives in the core test
tree and is not visible here — construct one inline).

### FILL IN checklist
- [ ] local fake + fixture; bounded by the existing store-test idiom.
- [ ] test bodies; bounded by spec §4 rows `test_refreshable_with_data_sources`, `test_update_envelope_expected_updated_at`.

---

## Acceptance Criteria

- [ ] `refreshable` is True for a surface with sources and no recipe; unchanged otherwise (AC8).
- [ ] `update_envelope(..., expected_updated_at=stale)` returns False and leaves the row untouched (AC15).
- [ ] `update_envelope` without `expected_updated_at` issues the unchanged `_UPDATE_ENVELOPE_SQL` (AC11).
- [ ] Existing `test_ui_surfaces_store.py` / `test_ui_surfaces_handler.py` stay green.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_store.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py -q`

---

## Test Specification

See the CREATE test block (spec §4: `test_refreshable_with_data_sources`, `test_update_envelope_expected_updated_at`).

---

## Agent Instructions

1. Read spec §3 Module 8 and S11.
2. Check TASK-3769 is done (`has_data_sources` importable).
3. Verify the Codebase Contract.
4. Index → `"in-progress"`; implement; complete every `# FILL IN:`.
5. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`).
6. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note.

---

## Completion Note


- Task: TASK-3786
- Feature: a2ui-linked-surfaces
- Implementation SHA: 144c7609399412697d755f7b090163c52ebb4bf6
- Closed at (UTC): 2026-09-26T01:35:04+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: 2 pre-existing failures already characterized (test_agent_a2ui_stream.py brittle source-string assertions), unrelated to this task's diff. Task's own scoped tests: 5+14+42 passed (ui_surfaces linked store, ui_surfaces store, ui_surfaces handler). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
