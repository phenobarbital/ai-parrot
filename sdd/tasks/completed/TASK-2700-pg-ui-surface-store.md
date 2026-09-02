# TASK-2700: PgUISurfaceStore — models, DDL & share tokens

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The persistence foundation of the ui_surfaces plane: two
Postgres tables (`navigator.ui_surfaces`, `navigator.ui_surface_shares`)
auto-created on first use, their Pydantic row models, and the async store
every other module consumes. Resolved decisions folded in: no envelope size
limit (v1); share tokens default `expires_at NULL` (when a TTL is enabled the
default is 90 days); the list lane must support **shared-with-me** (spec §8
resolution) — which requires recording which authenticated user *claimed* a
share token.

---

## Scope

- Implement `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`:
  - `UISurfaceKind` (str Enum: `dashboard|infographic|widget`).
  - `UISurfaceRecord` and `UISurfaceShare` Pydantic models (spec §2 Data
    Models). `UISurfaceRecord.refreshable` property = `recipe_name is not None`.
  - DDL constants: `CREATE SCHEMA IF NOT EXISTS navigator;`,
    `CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (...)`,
    `CREATE TABLE IF NOT EXISTS navigator.ui_surface_shares (...)` — follow
    the `handlers/models/bots.py:29` idiom. Shares table includes
    `claimed_by TEXT NULL` + `claimed_at TIMESTAMPTZ NULL` (shared-with-me
    support). Indexes: `ui_surfaces(user_id)`, `ui_surfaces(user_id, kind)`,
    `ui_surface_shares(surface_id)`, `ui_surface_shares(claimed_by)`.
  - `PgUISurfaceStore` (async, `AsyncDB("pg", dsn=default_dsn)` per
    operation or lightweight pooling — follow `comm_center.py:72-80`):
    `ensure_schema()` (idempotent, lazy on first use),
    `save(record, *, overwrite=False) -> str`,
    `get(surface_id) -> Optional[UISurfaceRecord]`,
    `list(user_id, *, kind=None) -> list[UISurfaceRecord]` (owned),
    `list_shared_with(user_id) -> list[UISurfaceRecord]` (surfaces whose
    non-revoked, non-expired share tokens have `claimed_by == user_id`),
    `update_envelope(surface_id, envelope, recipe_params) -> None` (bumps
    `updated_at`),
    `delete(surface_id, user_id) -> bool`,
    `mint_share(surface_id, *, expires_at=None) -> UISurfaceShare`
    (`secrets.token_urlsafe(32)`; default no expiry; 90 days when a TTL is
    requested without an explicit date),
    `resolve_share(token) -> Optional[UISurfaceShare]` (None for
    missing/revoked/expired — indistinguishable, no oracle),
    `claim_share(token, user_id) -> None` (sets `claimed_by`/`claimed_at`
    on first authenticated use; idempotent, never overwrites an existing claim),
    `revoke_share(token, surface_id) -> bool`,
    `list_shares(surface_id) -> list[UISurfaceShare]`.
- Write unit tests in
  `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py`.

**NOT in scope**: HTTP handler / negotiation (TASK-2702), route registration
(TASK-2703), RecipeRunner changes (TASK-2701), mixin/tool writers (TASK-2704).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | CREATE | Models + DDL + `PgUISurfaceStore` |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py` | CREATE | Unit tests (store + shares + claim) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
from asyncdb import AsyncDB                          # verified: handlers/bots.py:5 (core dep)
from asyncdb.exceptions import NoDataFound           # verified: handlers/comm_center.py:30
from parrot.conf import default_dsn                  # verified: handlers/comm_center.py:36
from parrot.outputs.a2ui.models import CreateSurface # verified: outputs/a2ui/models.py:446 (envelope validation only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/comm_center.py:72-80 — Pg access idiom
def _get_db() -> AsyncDB:
    return AsyncDB("pg", dsn=default_dsn)

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py:29 — auto-create DDL idiom
#   "CREATE TABLE IF NOT EXISTS navigator.ai_bots ( ... )"

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:446 — the envelope column's shape
class CreateSurface(A2UIMessageBase):
    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component]
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
    metadata: SurfaceMetadata | None = None
# Stored envelope == CreateSurface.model_dump(by_alias=True, mode="json")
# (the persist_envelope convention, outputs/a2ui/baking.py:399)

# Deep-link one-shot token idiom to MIRROR for opacity/no-oracle (NOT to reuse —
# these tokens are multi-use and Pg-stored, deep-links are single-use Redis):
# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py:148  token_urlsafe(32)
```

### Does NOT Exist
- ~~`navigator.ui_surfaces` / `navigator.ui_surface_shares`~~ — THIS task creates them
- ~~`PgUISurfaceStore`, `UISurfaceRecord`, `UISurfaceShare`, `UISurfaceKind`~~ — all new here
- ~~a persistent surface store anywhere~~ — only `ConversationMemorySurfaceStore` (conversation memory) exists
- ~~`DBRecipeStore` on Postgres~~ — it is Redis-backed (`outputs/a2ui/recipes/store.py:314`); do NOT copy it as a Pg pattern
- ~~`parrot.conf.UI_SURFACES_DSN`~~ — resolved: use `default_dsn` (spec §8)

---

## Implementation Notes

### Pattern to Follow
```python
# comm_center.py handler style: fresh AsyncDB("pg") per operation, async with:
async with await self._db().connection() as conn:   # follow comm_center's actual usage
    await conn.execute(DDL_UI_SURFACES)
```
Read `handlers/comm_center.py` before writing queries — reuse its
execute/fetch idioms (`fetchall(sentence, *args)` gotcha at line ~497:
a tuple counts as ONE arg).

### Key Constraints
- Async throughout; Pydantic models for every row shape; `self.logger`.
- `ensure_schema()` must be idempotent and safe under concurrent first-calls
  (`IF NOT EXISTS` everywhere; tolerate duplicate-index races).
- Envelope stored as jsonb verbatim — NO size validation (resolved: no limit v1).
- `resolve_share`: single query filtering `revoked = false AND (expires_at IS
  NULL OR expires_at > now())`; missing/revoked/expired all return `None`.
- `claim_share`: `UPDATE ... SET claimed_by=$1, claimed_at=now() WHERE token=$2
  AND claimed_by IS NULL` — first authenticated user wins; later users still
  get read access via the token, but the listing claim is not reassigned (v1).
- Timestamps: `datetime.now(timezone.utc)`, ISO in models.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` — Pg idioms
- `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` — DDL idiom
- `packages/ai-parrot-server/src/parrot/autonomous/ledger.py:47-67` — another auto-create example

---

## Acceptance Criteria

- [ ] `ensure_schema()` creates both tables + indexes; second call is a no-op
- [ ] `UISurfaceRecord` round-trips through save/get with envelope intact
- [ ] `list()` filters by owner (+ optional kind); `list_shared_with()` returns
      only surfaces with a live token claimed by that user
- [ ] `update_envelope()` replaces envelope+recipe_params and advances `updated_at`
- [ ] Share lifecycle: mint (no expiry default; 90-day default when TTL
      requested) → resolve → claim (idempotent) → revoke → resolve returns None
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py
# Mock/patch AsyncDB (or use the repo's pg test fixture if present in
# tests/handlers/) — do NOT require a live prod database.

async def test_ensure_schema_idempotent(): ...
async def test_save_get_roundtrip_envelope_intact(): ...
async def test_save_overwrite_flag(): ...
async def test_list_by_owner_and_kind(): ...
async def test_update_envelope_in_place_bumps_updated_at(): ...
async def test_delete_owner_only(): ...
async def test_share_mint_default_no_expiry(): ...
async def test_share_mint_ttl_defaults_90_days(): ...
async def test_share_resolve_revoked_expired_missing_all_none(): ...
async def test_share_claim_idempotent_first_wins(): ...
async def test_list_shared_with_claimed_only(): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/a2ui-surface-rehydration.spec.md` (§2 Data
   Models, §3 Module 1, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing any code.
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify** acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**:
Implemented `PgUISurfaceStore`, `UISurfaceRecord`, `UISurfaceShare`,
`UISurfaceKind` and the auto-create DDL in
`packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`,
following the `comm_center.py` `_get_db()` + `AsyncDB("pg", dsn=default_dsn)`
+ `async with await db.connection() as conn:` idiom, and the
`autonomous/ledger.py` idempotent-statement-list DDL pattern (tolerates
"already exists" races). All 11 unit tests pass against an in-memory fake
connection that matches on the module's own SQL constants (no live
Postgres required), mirroring `test_comm_center_dispatch.py`'s
`_FakeAsyncDB`/`_FakeConnCtx` idiom. `ruff check` is clean.

**Deviations from spec**:
- `mint_share()` signature gained an extra keyword `use_default_ttl: bool =
  False` beyond the spec's documented `(surface_id, *, expires_at=None)`.
  The spec's resolved Open Question ("no expiry by default; 90 days when a
  TTL is enabled") requires a caller-supplied signal distinct from an
  explicit date, and the New Public Interfaces code block doesn't name one
  — `use_default_ttl` is the minimal, additive way to satisfy both the
  "no expiry by default" and "90-day default when TTL requested" acceptance
  criteria without overloading `expires_at` with a sentinel value. Purely
  additive (keyword-only, defaults preserve the no-TTL behavior) — will not
  break TASK-2702's handler, which can pass it through from the REST body.
- Surface ids are generated as `str(uuid.uuid4())` (hyphenated canonical
  form) rather than the literal "uuid4 hex" phrasing in the spec's Data
  Models section — the `surface_id UUID PRIMARY KEY` column round-trips
  through asyncpg as a canonical hyphenated string, so hex-without-dashes
  input would not survive a save/get round-trip byte-for-byte. ID
  generation itself lives with the caller (mixin, TASK-2704), not the
  store — `save()` persists whatever `UISurfaceRecord.surface_id` it is
  given.
