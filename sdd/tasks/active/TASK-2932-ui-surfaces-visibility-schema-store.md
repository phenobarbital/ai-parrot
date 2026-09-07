# TASK-2932: `ui_surfaces` visibility columns, record fields and store methods

**Feature**: FEAT-535 — Tenant-aware, permission-based visibility for UI surfaces
**Spec**: `sdd/specs/ui-surfaces-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1**. `navigator.ui_surfaces` has 13 columns and knows only
its owner. This task adds `tenant`, `visibility`, `allowed_groups` (live
migration inside `_DDL_STATEMENTS`, the `models/bots.py` idiom), carries them
through the record, the SQL constants and `_row_to_record`, and adds the two
store methods the handler will call: `list_visible(scope, kind)` and
`update_visibility(...)`. Everything is additive; a row written before this
task must load as `private`.

---

## Scope

- `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`:
  - `class SurfaceVisibility(str, Enum)`: `private`, `tenant`, `groups`.
  - `UISurfaceRecord`: `tenant: str | None = None`, `visibility: SurfaceVisibility = SurfaceVisibility.private`, `allowed_groups: list[str] = Field(default_factory=list)`.
  - `_DDL_STATEMENTS`: add the three columns to the `CREATE TABLE IF NOT EXISTS navigator.ui_surfaces` column list AND append four statements after the two `CREATE TABLE`s: `ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS tenant VARCHAR(63)`, `... visibility VARCHAR(16) NOT NULL DEFAULT 'private'`, `... allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb`, `CREATE INDEX IF NOT EXISTS ix_ui_surfaces_tenant_visibility ON navigator.ui_surfaces (tenant, visibility)`.
  - `_INSERT_SQL` / `_UPSERT_SQL` / `_GET_SQL`: add the three columns (`allowed_groups` as `$N::jsonb`, `json.dumps(list)` on write; `_LIST_*`/`_LIST_SHARED_WITH_SQL` inherit through `_GET_SQL`/its own column list — update `_LIST_SHARED_WITH_SQL`'s explicit column list too).
  - `_row_to_record`: read `tenant` (`data.get`), `visibility` (`SurfaceVisibility(data.get("visibility") or "private")`), `allowed_groups` (`_decode_jsonb`-style list decode; tolerate `None`, a JSON string, or a list).
  - New SQL `_LIST_VISIBLE_SQL` / `_LIST_VISIBLE_BY_KIND_SQL` exactly as spec §2 "Visibility SQL" (`$1 user_id, $2 tenant, $3 groups::text[], $4 is_superuser[, $5 kind]`), and `_UPDATE_VISIBILITY_SQL` (`UPDATE ... SET visibility=$3, allowed_groups=$4::jsonb, updated_at=NOW() WHERE surface_id=$1 AND user_id=$2 RETURNING surface_id`).
  - `PgUISurfaceStore.list_visible(self, scope, *, kind=None) -> list[UISurfaceRecord]` — `scope` is duck-typed here (`user_id`, `tenant`, `groups`, `is_superuser` attributes) so this module does not import the handler package; pass `list(scope.groups)` for `$3`.
  - `PgUISurfaceStore.update_visibility(self, surface_id, user_id, visibility, allowed_groups) -> bool`.
  - `save` writes the new columns (positional params extended in the same order in INSERT and UPSERT).
- Tests:
  - Extend `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py`'s fake state so `_FakeConn` understands the new columns and the two new SQL constants (it dispatches on SQL text today — see how `_LIST_SQL` is matched), then add: old-row-loads-as-private, `list_visible` matrix, `update_visibility` owner-only, DDL statements count.
  - NEW `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store_live.py`: real Postgres gated on `NAVIGATOR_PG_DSN` (skip with a clear reason when unset), using a throwaway schema name is NOT possible (the DDL hard-codes `navigator`) — so: create the PRE-feature table shape first (copy the old `CREATE TABLE` text into the test as a literal), run `ensure_schema()`, assert the columns/index exist via `information_schema`, run the `list_visible` matrix and `update_visibility` against real rows, clean up the rows you inserted (never drop the table). This is the test that proves `?| $3::text[]` and `::jsonb` actually execute — the fake cannot.

**NOT in scope**: the scope resolver (TASK-2933), handler changes (TASK-2934/2935), docs (TASK-2936).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | MODIFY | enum, record fields, DDL, SQL, `_row_to_record`, two methods |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py` | MODIFY | fake-state coverage of the new columns/SQL + new tests |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store_live.py` | CREATE | real-Postgres proof (`NAVIGATOR_PG_DSN`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceRecord, UISurfaceKind, UISurfaceShare  # models/ui_surfaces.py:351,49,41,72 (dev 3d03bb2cd)
from asyncdb import AsyncDB   # already imported by the module
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py  (origin/dev 3d03bb2cd)
class UISurfaceKind(str, Enum)                                        # :41
class UISurfaceRecord(BaseModel):                                     # :49-69  13 fields; @property refreshable (:66)
class UISurfaceShare(BaseModel): permissions: Literal["read+refresh"] # :72-82
_DDL_STATEMENTS: list[str]                                            # :89-127  ["CREATE SCHEMA IF NOT EXISTS navigator", CREATE TABLE ui_surfaces (:96-110), 2 indexes (:112-113), CREATE TABLE ui_surface_shares (:114-125), 2 indexes]
_INSERT_SQL                                                           # :131-136  13 params: $4::jsonb envelope, $11::jsonb recipe_params
_INSERT_OR_SKIP_SQL / _UPSERT_SQL                                     # :138-157  UPSERT SET list must gain the three columns
_GET_SQL                                                              # :159-164  explicit column list
_LIST_SQL = _GET_SQL.replace("WHERE surface_id = $1", "WHERE user_id = $1") + "\nORDER BY updated_at DESC"   # :166
_LIST_BY_KIND_SQL                                                     # :168-170
_LIST_SHARED_WITH_SQL                                                 # :172-182  its OWN explicit column list (extend it too)
_UPDATE_ENVELOPE_SQL / _DELETE_SQL (WHERE surface_id = $1 AND user_id = $2 RETURNING surface_id)   # :184-195
def _decode_jsonb(raw: Any) -> dict[str, Any]                         # :232  (dict-shaped; write a sibling `_decode_jsonb_list` for allowed_groups)
def _row_to_record(row: Any) -> UISurfaceRecord                       # :254-272  dict(row) → explicit mapping
def _as_uuid(value) -> uuid.UUID | None ; def _require_uuid(value) -> uuid.UUID   # :309, :321
async def _exec(conn, sql, *args) -> None ; async def _fetch_rows(conn, sql, *args) -> list   # :329, :337  (asyncdb quirks live here — use them)
class PgUISurfaceStore:                                               # :351
    def __init__(self, dsn: str | None = None)                        # :357
    def _get_db(self) -> AsyncDB                                      # :361  (tests monkeypatch this)
    async def _ensure_ready(self) / async def ensure_schema(self)     # :365, :369-395  loops _DDL_STATEMENTS via _exec; tolerates "already exists"
    async def save(self, record, *, overwrite=False) -> str           # :397  builds the positional tuple from the record — extend in INSERT/UPSERT order
    async def get(self, surface_id) -> UISurfaceRecord | None         # ~:430  conn.fetch_one(_GET_SQL, uuid)
    async def list(self, user_id, *, kind=None)                       # :447  KEEP unchanged
    async def list_shared_with(self, user_id)                         # :456  KEEP unchanged
    async def update_envelope(self, surface_id, envelope, recipe_params)   # :466  conn.fetchval(_UPDATE_ENVELOPE_SQL, uuid, json.dumps(...), json.dumps(...))
    async def delete(self, surface_id, user_id) -> bool               # :477  pattern for owner-only UPDATE/DELETE: fetchval RETURNING → `result is not None`

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py:573-577 — the live-migration idiom (ALTER TABLE ... ADD COLUMN IF NOT EXISTS inside a DDL string)

# tests/handlers/test_ui_surfaces_store.py (origin/dev)
class _FakeAsyncDB / _FakeConnCtx / _FakeConn(state)   # dispatch on SQL text; fake_state = SimpleNamespace(surfaces={}, shares={}, ddl_calls=[])  (:182-190)
@pytest.fixture pg_store(monkeypatch, fake_state): PgUISurfaceStore(dsn="postgres://fake/test"); monkeypatch _get_db   # :187-190
def _make_record(**overrides) -> UISurfaceRecord                      # :207-227  (add the three new keys to `defaults`)
```

### Does NOT Exist
- ~~a `tenant`/`visibility`/`allowed_groups` column or field~~ — this task adds them.
- ~~`list_visible`, `update_visibility`, `SurfaceVisibility`~~ — new here.
- ~~a migrations directory for `ui_surfaces`~~ — DDL lives ONLY in `_DDL_STATEMENTS`.
- ~~`SurfaceScope` importable from this module~~ — it is TASK-2933's handler-package type; duck-type the parameter here.
- ~~`conn.execute` for writes~~ — swallows errors under asyncdb 2.15 (FEAT-528 finding); use `_exec`/`fetchval`.

---

## Implementation Notes

### Key Constraints
- Additive DDL only; never `DROP`, never rename; `NOT NULL DEFAULT` on ADD COLUMN is metadata-only in PostgreSQL ≥ 11.
- `$3::text[]` receives a Python `list[str]` (asyncpg maps it); `allowed_groups ?| $3::text[]` is the jsonb "any key exists" operator over a JSON ARRAY of strings — write `allowed_groups` as a JSON array (`json.dumps(["a","b"])`), never an object.
- Keep `list`/`list_shared_with` byte-identical in behaviour; every existing test in the file must still pass.
- Google docstrings, type hints, `self.logger` at INFO for `ensure_schema` only (never log DSNs).

### References in Codebase
- `models/bots.py:565-585` — ALTER inside DDL string.
- `models/recipes.py` (FEAT-528) — the sibling store written against the same asyncdb quirks.

---

## Acceptance Criteria

- [ ] `ensure_schema()` on a table created with the OLD DDL adds the three columns + index (live test); second run no-op; fresh DB gets the same shape
- [ ] Old row → `visibility=private`, `tenant=None`, `allowed_groups=[]`
- [ ] `list_visible` matrix passes on the fake AND the live database (owner / tenant / groups hit+miss / superuser / caller without tenant / row without tenant)
- [ ] `update_visibility` owner-only (mutation: drop `AND user_id = $2` → the non-owner test goes RED; evidence in the Completion Note)
- [ ] All pre-existing tests in `test_ui_surfaces_store.py` pass unchanged in intent; `ruff check` clean on changed files

---

## Test Specification

```python
# tests/handlers/test_ui_surfaces_store.py (excerpt)
async def test_old_row_without_new_columns_loads_as_private(pg_store, fake_state):
    rid = str(uuid.uuid4())
    fake_state.surfaces[rid] = {**_old_row(rid)}          # no tenant/visibility/allowed_groups keys
    rec = await pg_store.get(rid)
    assert rec.visibility is m.SurfaceVisibility.private and rec.tenant is None and rec.allowed_groups == []

async def test_list_visible_matrix(pg_store):
    ...  # see spec §4 row "test_list_visible_matrix"

# tests/handlers/test_ui_surfaces_store_live.py
DSN = os.getenv("NAVIGATOR_PG_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="NAVIGATOR_PG_DSN not set (fs-scratch-pg)")
```

---

## Agent Instructions

1. Read spec §2 (Data Models, Visibility SQL), §3 Module 1, §6, §7.
2. Verify the contract line numbers against the tree; then implement.
3. Run `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store*.py -v` (with `NAVIGATOR_PG_DSN` exported) and `ruff check` on changed files.
4. Update `sdd/tasks/index/ui-surfaces-tenant-visibility.json` → `in-progress` → `done`; move this file to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
