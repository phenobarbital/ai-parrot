---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [parrot-formdesigner]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [security, tenant-isolation, fieldsync, venue, ddl, formdesigner]
---

# Brainstorm: FieldSync venue tables — close the FEAT-330 security findings (issue #1005)

**Date**: 2026-10-08
**Author**: Jesus Lara + Claude
**Status**: accepted
**Recommended Option**: B

---

## Problem Statement

PR #998 (FEAT-330 "Store Venue Sub-Structure — Site/Location", merged to `dev`
2026-07-10, then `#1004 → main`) shipped `fieldsync.sites` / `fieldsync.locations`
and the `VenueService` CRUD without addressing two HIGH findings raised in the
pre-merge code review. GitHub issue
[#1005](https://github.com/phenobarbital/ai-parrot/issues/1005) tracks them so
they are not lost. Verified on 2026-10-08: the last commit touching
`venue_service.py` and `fieldsync_schema.py` is still the original FEAT-330
merge (`810a521eb`), so **nothing has been fixed yet**.

**Who is affected**: every tenant of the FieldSync deployment that consumes
`parrot-formdesigner`. The venue tables are the system of record for the
per-location geofence that gates visit check-ins (FEAT-303 §8 / FEAT-318 D5.7),
so a cross-org write corrupts another organization's operational data.

**The five findings (all in scope — Round 1 decision):**

1. **HIGH — `create_location` allows cross-org writes.** `_INSERT_LOCATION_SQL`
   (`venue_service.py:182-189`) inserts the caller-supplied `site_id` together with
   the *session* `org_id` without checking that the parent site belongs to that
   org. `site_id` is an enumerable `SERIAL`. Consequences: a name-existence oracle
   across orgs via 409 (because `uq_locations_site_name` is org-agnostic), silent
   cross-org data loss through `ON DELETE CASCADE`, and inconsistent rows
   (`location.org_id ≠ site.org_id`) that neither org's graph can see.
2. **HIGH — UNIQUE constraints omit `org_id`.** `uq_sites_store_name UNIQUE
   (store_id, client_id, name)` (`fieldsync_schema.py:99`) and
   `uq_locations_site_name UNIQUE (site_id, name)` (`:118`) collide across orgs
   → name oracle + name squatting. The DDL is `CREATE TABLE IF NOT EXISTS`, so
   editing the text alone never reaches an environment where the table already
   exists.
3. **MEDIUM — `client_id` is taken from the request body** in both
   `create_site` (`handlers.py:2710-2716`) and `create_location`
   (`:2811-2817`) with no check that the client belongs to the session org.
4. **MEDIUM — no bounds on `latitude` / `longitude` / `geofence_radius_m`.**
   The handler passes `body.get("latitude")` etc. straight through
   (`handlers.py:2831-2833`); a string or out-of-range value surfaces as a 500
   from asyncpg instead of a 400.
5. **MEDIUM — `networkninja.stores_geographies` column names are unverified.**
   `_SQL_GET_STORES_FOR_CLIENT` (`org_graph.py:157-161`) carries a NOTE saying
   so; the upstream FEAT-330 spec (Q2) deferred the confirmation to coding time
   and it never happened.

**Why now**: the user confirmed (Round 1) that `FieldsyncSchemaManager.initialize()`
has **not yet** run against any shared environment, so the tables are empty
everywhere. Constraint changes are instantaneous today and need a data migration
the moment rows land.

## Constraints & Requirements

- **Hard tenant isolation is the FEAT-302/330 invariant**: every query on
  `fieldsync.*` filters by `org_id`. The fix must make it impossible to create a
  row whose `org_id` disagrees with its parent's.
- **DDL doctrine stays "idempotent, no migration framework"**
  (`fieldsync_schema.py:16-19`): `initialize()` must converge *both* a fresh
  database and one that already has the v1 tables, and running it twice must be a
  no-op (existing test `test_initialize_twice_no_error`).
- **Service remains unit-testable with the fake pool** (`tests/unit/test_venue_service.py:46-66`):
  a `MagicMock` conn with `fetchrow` / `fetch` `AsyncMock`s. No real Postgres
  fixture exists in `parrot-formdesigner` tests (checked `tests/integration/conftest.py`
  and `tests/fixtures/persistence.py` — the `survey_form_postgres` fixture is a
  `FormSchema`, not a database).
- **Error semantics**: cross-org or non-existent parent ⇒ `SiteNotFoundError` ⇒
  404 (never 403/409, to avoid the existence oracle). Client not in org ⇒ 404 by
  the same reasoning (mirrors `OrgGraphService.get_node` raising `KeyError`).
  Bad geofence values ⇒ 400 with a field-specific message.
- **`org_id` keeps coming from the session only** (`_get_org_id`,
  `handlers.py:221-247`); never from the body.
- **SQL stays 100 % parameterised with table names in constants**
  (`venue_service.py:18`, enforced by `TestSQLSafety`).
- **All three schemas (`auth.*`, `networkninja.*`, `fieldsync.*`) live in the
  same database** — `OrgGraphService` already queries all three through one pool
  (`org_graph.py:106-176`). The service-level membership check relies on this;
  the DB role behind the `VenueService` pool needs `SELECT` on
  `auth.organization_clients`.
- **No new dependencies**: asyncpg + Pydantic v2 + aiohttp only.
- **Issue #1005 closes with this feature's PR.** The upstream spec
  (`Trocdigital/fieldsync` → `sdd/specs/store-venue-substructure.spec.md`, FEAT-330
  v0.3) is read-only reference; this repo gets its own spec.

---

## Options Explored

### Option A: Literal fix — exactly what the issue asks, nothing structural

Apply the two one-statement fixes from the issue text and the handler-side
medium items, without touching how the schema manager converges existing tables.

- `_INSERT_LOCATION_SQL` becomes `INSERT … SELECT … WHERE EXISTS (site in org)`;
  0 rows ⇒ `SiteNotFoundError`.
- Edit the `CREATE TABLE` text so both UNIQUE constraints include `org_id`.
- `create_site` / `create_location` handlers call
  `OrgGraphService.get_node("client", …)` before writing (404 on `KeyError`).
- Handler validates lat/lon/radius and returns 400.
- Fix the `stores_geographies` column names after a manual check.

✅ **Pros:**
- Smallest diff; every change is local to one function or one constant.
- No new DDL mechanics — the "no migrations" doctrine is untouched in letter.

❌ **Cons:**
- **The constraint fix only reaches databases created after the change.** Any
  environment where `initialize()` already ran keeps the org-less UNIQUEs
  forever; the doctrine's own escape hatch (`fieldsync_schema.py:18-19`,
  "ALTER TABLE idempotente") is not used.
- Handler-level client check adds a round-trip, couples the venue endpoints to
  `self._org_graph_service` (which may be `None` → 501 or silent skip), and leaves
  `VenueService` unsafe when called directly from Python.
- Integrity still depends on every writer going through `VenueService`; a direct
  `INSERT` can still create `location.org_id ≠ site.org_id`.
- No DB-level bounds: a direct writer can store latitude 999.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` | already the driver | no change |
| `pydantic` v2 | already used for `Site` / `Location` | no change |

🔗 **Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` — `_INSERT_LOCATION_SQL`, `SiteNotFoundError`
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/org_graph.py:474-537` — `get_node("client", …)` org-scoped lookup
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:2682-2844` — the two POST handlers

---

### Option B: Converging DDL + relational tenancy (ownership in SQL, integrity in the schema) — **recommended**

Treat the fix as "make the database unable to hold a cross-org row" plus "make
the service unable to attempt one", and make `initialize()` converge any
environment to the new shape.

**Schema (`fieldsync_schema.py`)**
- `CREATE TABLE IF NOT EXISTS` text updated for fresh databases:
  - `sites`: `uq_sites_org_store_name UNIQUE (org_id, store_id, client_id, name)`
    and `uq_sites_id_org UNIQUE (site_id, org_id)` (required target for the
    composite FK).
  - `locations`: `uq_locations_org_site_name UNIQUE (org_id, site_id, name)`,
    `fk_locations_site_org FOREIGN KEY (site_id, org_id) REFERENCES
    fieldsync.sites (site_id, org_id) ON DELETE CASCADE` (replacing the
    single-column FK), and CHECK constraints `ck_locations_latitude`
    (`latitude IS NULL OR latitude BETWEEN -90 AND 90`), `ck_locations_longitude`
    (`BETWEEN -180 AND 180`), `ck_locations_geofence_radius`
    (`geofence_radius_m IS NULL OR geofence_radius_m > 0`), and
    `ck_locations_latlon_pair` (`(latitude IS NULL) = (longitude IS NULL)`).
- A new ordered block of **idempotent ALTER statements** appended to `_ALL_DDL`
  for databases that already have the v1 tables: `ALTER TABLE … DROP CONSTRAINT
  IF EXISTS <old name>` for `uq_sites_store_name`, `uq_locations_site_name`,
  `locations_site_id_fkey`; and, because Postgres has no `ADD CONSTRAINT IF NOT
  EXISTS`, each `ADD CONSTRAINT` wrapped in a `DO $$ … IF NOT EXISTS (SELECT 1
  FROM pg_constraint WHERE conname = '…') THEN … END IF $$` block. New constraint
  names differ from the old ones so the drop/add pair is unambiguous and
  re-runnable. `ddl_statements()` grows accordingly (the existing
  `test_ddl_statements_returns_six` must be updated).

**Service (`venue_service.py`)**
- `_INSERT_SITE_SQL` → `INSERT … SELECT $1,$2,$3,$4 WHERE EXISTS (SELECT 1 FROM
  auth.organization_clients WHERE client_id = $2 AND org_id = $3)`; 0 rows ⇒ new
  `ClientNotInOrgError(client_id)`.
- `_INSERT_LOCATION_SQL` → `INSERT … SELECT … WHERE EXISTS (site $1 in org $3)
  AND EXISTS (client $2 in org $3)`; 0 rows ⇒ the service re-checks which guard
  failed with one follow-up `SELECT` (site first) so it can raise
  `SiteNotFoundError` vs `ClientNotInOrgError` precisely — or, simpler, raises
  `SiteNotFoundError` when the site check fails and `ClientNotInOrgError`
  otherwise. Both map to 404 in the handler.
- Docstrings updated: "UNIQUE per `(org_id, store_id, client_id)`" etc.
- `_db_utils.py` gains `is_check_violation()` (SQLSTATE `23514`) and
  `is_foreign_key_violation()` (`23503`) next to `is_unique_violation()`, so the
  service can surface a `VenueValidationError` instead of a bare asyncpg error if
  a direct caller bypasses the handler.

**Handler (`handlers.py`)**
- `create_location`: validate `latitude` / `longitude` as finite floats in range,
  `geofence_radius_m` as a positive int, lat/lon both present or both absent;
  400 with the offending field name. Map `SiteNotFoundError` and
  `ClientNotInOrgError` → 404, `VenueValidationError` → 400.
- `create_site`: map `ClientNotInOrgError` → 404.

**Org graph (`org_graph.py`)**
- A verification task: a documented `psql` / `information_schema.columns` check
  against `networkninja.stores_geographies` (with `ENV=prod`, per project memory),
  then edit `_SQL_GET_STORES_FOR_CLIENT` to the real column names and delete the
  NOTE. The fake-pool fixture in `test_org_graph_service.py:390-392` is keyed by
  table name, not column, so it tolerates a rename.

✅ **Pros:**
- Cross-org rows become **impossible by any path** — the composite FK rejects
  them even from a raw `INSERT`, and the EXISTS guard turns the attempt into a
  clean 404 with no oracle.
- `initialize()` converges both fresh and already-initialised databases, which
  is exactly the escape hatch the DDL doctrine reserved; no out-of-band script
  for ops to remember.
- Client membership is enforced in the same statement as the write (one
  round-trip) and holds for direct Python callers, not only the HTTP layer.
- CHECK constraints make the 400 validation a convenience, not the only guard.
- All of it is unit-testable with the existing fake pool (assert SQL text
  contains `EXISTS`, `fetchrow` → `None` raises the right exception, DDL text
  contains the constraint names, handler returns 400/404).

❌ **Cons:**
- Larger DDL diff; `_ALL_DDL` roughly doubles in statement count and the
  `DO $$` blocks are the first procedural SQL in the module.
- The `VenueService` pool's DB role now needs `SELECT` on
  `auth.organization_clients` (true today for the `OrgGraphService` role, to be
  confirmed for the venue pool — open question).
- Constraint renames mean anyone with a hand-written v1 database must run
  `initialize()` once; that is the intended path but it is a behaviour change to
  document.
- Without a real-Postgres test the ALTER block is only text-tested; a one-off
  manual run against a disposable DB is recommended in the task's validation
  commands.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` | driver; `conn.execute()` runs `DO $$` blocks fine | already a dependency |
| `pydantic` v2 | optional `LocationCreate` input model for the bounds | already a dependency |
| PostgreSQL ≥ 9.x | `DROP CONSTRAINT IF EXISTS`, composite FK, CHECK | server feature, nothing to install |

🔗 **Existing Code to Reuse:**
- `services/fieldsync_schema.py:124-131` — `_ALL_DDL` ordered list + `ddl_statements()` introspection used by tests
- `services/venue_service.py:162-204` — SQL constants; `:259-266` / `:347-362` the `is_unique_violation` → `DuplicateVenueError` pattern to extend
- `services/_db_utils.py:8-20` — `is_unique_violation()` template for the new helpers
- `services/org_graph.py:179-184` — `_SQL_GET_CLIENT_SCOPED` is the exact membership predicate to inline as `EXISTS`
- `api/handlers.py:2846-2880` — `get_location` shows the `LocationNotFoundError → 404` mapping style
- `tests/unit/test_venue_service.py:39-120` — fake-pool helpers (`_make_conn`, `_make_pool`, `_site_row`, `_location_row`)
- `tests/unit/test_fieldsync_schema.py:53-150` — DDL text + manager tests to extend

---

### Option C: Postgres Row-Level Security as the tenancy boundary (unconventional)

Keep the SQL mostly as-is and push isolation into the database: enable RLS on
`fieldsync.sites` / `fieldsync.locations` with policies keyed on
`current_setting('fieldsync.org_id')::int`; `VenueService` wraps every call in a
transaction that does `SET LOCAL fieldsync.org_id = $org`. The cross-org insert
then fails at the policy (`WITH CHECK`) and the parent-site lookup implicit in
the FK is itself org-filtered.

✅ **Pros:**
- Isolation no longer depends on every SQL string remembering `AND org_id = $n`;
  it is a property of the connection context.
- Covers future tables in the schema for free once the pattern is set.

❌ **Cons:**
- `SET LOCAL` requires an explicit transaction on every call — a structural
  change to `VenueService` (and `ProjectService`, for consistency) that the fake
  pool cannot exercise meaningfully.
- RLS is bypassed by table owners and `BYPASSRLS` roles; it only works if the
  app role is neither, which is an ops guarantee outside this repo.
- Does **not** by itself fix the UNIQUE constraints (a policy filters rows, it
  does not change the uniqueness key) nor the bounds — Option B's DDL work is
  still needed, so this is additive cost, not a replacement.
- Error mapping gets worse: a policy violation surfaces as a generic
  `insufficient_privilege`-class error, so distinguishing "site not found" from
  "client not in org" needs extra queries anyway.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| PostgreSQL RLS | `CREATE POLICY` / `ALTER TABLE … ENABLE ROW LEVEL SECURITY` | server feature; needs role audit |
| `asyncpg` | `conn.transaction()` + `SET LOCAL` | already a dependency |

🔗 **Existing Code to Reuse:**
- `services/fieldsync_schema.py` — would host the policy DDL
- `services/venue_service.py` — every method would gain a transaction wrapper

---

## Recommendation

**Option B** is recommended because:

- It is the only option that closes **all five** findings and leaves the
  database unable to hold the bad state the issue describes. Option A fixes the
  symptoms in code but the DDL change never reaches an existing database, which
  is the exact failure mode the issue warns about ("fixing them post-data
  requires a migration"). Option C adds a heavyweight mechanism that still needs
  Option B's constraint work underneath.
- It uses the escape hatch the DDL module already reserved for itself
  ("columnas añadidas en futuras tasks con ALTER TABLE idempotente",
  `fieldsync_schema.py:18-19`) instead of inventing a migration lane.
- It keeps the FEAT-302/330 testing style intact: every assertion is on SQL text
  or on `fetchrow` returning `None`, so the existing fake-pool suite extends
  rather than being replaced.
- The user's Round 2 decisions (service-level SQL check, composite FK, handler
  400 + DB CHECK) are exactly Option B's shape.

What we trade off: a bigger DDL diff and the first procedural `DO $$` blocks in
the module, plus a grant requirement on `auth.organization_clients` for the venue
pool's role. Both are acceptable for a security fix on empty tables.

---

## Feature Description

### User-Facing Behavior

- `POST /api/v1/org/sites/{site_id}/locations` with a `site_id` that belongs to
  another organisation (or does not exist) returns **404** `Site <id> not found`
  — identical to the response for a missing site, so nothing leaks.
- `POST /api/v1/org/stores/{store_id}/sites` and the location endpoint with a
  `client_id` that is not a member of the session organisation return **404**
  `Client <id> not found`.
- Duplicate names are now scoped per organisation: two orgs can each have a
  site "Vending Zone" in the same store, or a location "Kiosk A-12" under their
  own sites, without seeing each other's 409.
- Location bodies with `latitude` outside `[-90, 90]`, `longitude` outside
  `[-180, 180]`, a non-numeric coordinate, a `geofence_radius_m` that is not a
  positive integer, or only one of the two coordinates return **400** naming the
  field, instead of 500.
- Operators run `FieldsyncSchemaManager.initialize()` once (on startup, as
  today) and any database — fresh or already initialised — ends up with the new
  constraints.
- The org-graph `store` level reads the real `networkninja.stores_geographies`
  columns; the "unverified" NOTE disappears.

### Internal Behavior

1. **Schema convergence.** `initialize()` executes the updated `CREATE TABLE IF
   NOT EXISTS` statements (no-op on existing tables), then the ALTER block:
   drop the three v1 constraints if they exist, add the v2 UNIQUEs, the
   `(site_id, org_id)` unique on sites, the composite FK and the CHECKs if they
   do not exist (catalog-guarded). Second run: every statement is a no-op.
2. **Ownership-checked writes.** `create_site` inserts via
   `INSERT … SELECT … WHERE EXISTS (client ∈ org)`; `create_location` via
   `INSERT … SELECT … WHERE EXISTS (site ∈ org) AND EXISTS (client ∈ org)`.
   `fetchrow` returning `None` means a guard failed; the service raises
   `SiteNotFoundError` or `ClientNotInOrgError`. UNIQUE violations still map to
   `DuplicateVenueError`; CHECK / FK violations map to a new
   `VenueValidationError` through `_db_utils` helpers.
3. **Handler validation.** Before calling the service, `create_location` parses
   the geofence trio into typed values with range checks and the pairing rule;
   failures return 400. Both POST handlers map the new exceptions to 404 / 400
   and keep the generic 500 for anything else.
4. **Store column verification.** A task runs the documented catalog query
   against the production dump, records the real column names in its Completion
   Note, and edits `_SQL_GET_STORES_FOR_CLIENT`.

### Edge Cases & Error Handling

- **Site exists but in another org** → 404 (not 403), no row written, no
  cascade exposure.
- **Site in org, client not in org** → 404 `Client not found`; the site's
  existence is not disclosed beyond what the caller already knows from the path.
- **Both guards fail** → `SiteNotFoundError` wins (site is checked first).
- **Duplicate name within the same org** → 409 as before.
- **Same name in a different org** → 201 (new behaviour).
- **`geofence_radius_m` present, coordinates absent** → allowed (radius stored,
  geofence effectively disabled by the FEAT-303 reader semantics) — unless the
  user decides otherwise (open question).
- **Coordinates present, radius absent** → allowed (`None` ⇒ disabled, existing
  contract `venue_service.py:125-126`).
- **Direct Python caller sends latitude 999** → DB CHECK fires →
  `VenueValidationError`, not a raw asyncpg exception.
- **`initialize()` on a database created from an unexpected hand-edited DDL**
  (constraint names differ) → the DROP-IF-EXISTS steps are no-ops and the ADD
  steps add the v2 constraints alongside; the old ones are not removed. Logged
  at WARNING if `pg_constraint` still shows a v1 name after the run.
- **Venue pool role lacks `SELECT` on `auth.organization_clients`** → every
  create fails with `insufficient_privilege` → 500. Documented as a deployment
  prerequisite; a startup probe is an open question.

---

## Capabilities

### New Capabilities
- `fieldsync-schema-convergence`: idempotent ALTER block in
  `FieldsyncSchemaManager` that migrates v1 venue constraints to v2.
- `venue-ownership-guards`: `EXISTS`-guarded inserts and the
  `ClientNotInOrgError` / `VenueValidationError` exceptions in `VenueService`.
- `venue-geofence-validation`: handler-side 400 validation plus DB CHECK
  constraints for the geofence trio.

### Modified Capabilities
- `store-venue-substructure` (upstream FEAT-330, `Trocdigital/fieldsync`
  spec v0.3) — UNIQUE keys gain `org_id`; `create_location` contract adds the
  404 path; the spec's "Confirm the column names" note for
  `stores_geographies` is resolved.
- `formdesigner-package` / org-graph store level — `_SQL_GET_STORES_FOR_CLIENT`
  column names corrected.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `services/fieldsync_schema.py` | modifies | new constraint names in `CREATE TABLE`, new ALTER block in `_ALL_DDL`, statement count changes |
| `services/venue_service.py` | modifies | both INSERT constants become `INSERT … SELECT … WHERE EXISTS`; two new exceptions; docstrings |
| `services/_db_utils.py` | extends | `is_check_violation()`, `is_foreign_key_violation()` |
| `api/handlers.py` (`create_site`, `create_location`) | modifies | bounds validation, 404/400 mapping |
| `services/org_graph.py` | modifies | `_SQL_GET_STORES_FOR_CLIENT` column names, NOTE removed |
| `tests/unit/test_fieldsync_schema.py` | extends | DDL text assertions, statement count, idempotency |
| `tests/unit/test_venue_service.py` | extends | cross-org 404, client-not-in-org 404, SQL contains `EXISTS`, validation error mapping |
| `tests/unit/api/` (new handler tests) | adds | no venue handler tests exist today (`test_route_tenant_coverage.py` only lists the paths) |
| Deployment (FieldSync app) | depends on | venue pool role needs `SELECT` on `auth.organization_clients`; `initialize()` must run once after upgrade |
| GitHub issue #1005 | closes | PR body `Closes #1005` |

No breaking API changes: new 404/400 paths only; 201/409 unchanged in-org.

---

## Code Context

### User-Provided Code

```sql
-- Source: user-provided (issue #1005 body, Javier León)
INSERT INTO fieldsync.locations (site_id, client_id, org_id, name, ...)
SELECT $1, $2, $3, $4, ...
WHERE EXISTS (SELECT 1 FROM fieldsync.sites WHERE site_id = $1 AND org_id = $3)
-- 0 rows → raise SiteNotFoundError (404)
```

### Verified Codebase References

All paths are relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless noted. Verified 2026-10-08 on `dev` @ `35ea61fb3`.

#### Classes & Signatures
```python
# From services/fieldsync_schema.py
_CREATE_SITES_SQL: str      # line 89  — CONSTRAINT uq_sites_store_name UNIQUE (store_id, client_id, name)  (line 99)
_CREATE_LOCATIONS_SQL: str  # line 103 — site_id REFERENCES fieldsync.sites (site_id) ON DELETE CASCADE (106-107)
                            #            CONSTRAINT uq_locations_site_name UNIQUE (site_id, name)       (line 118)
_ALL_DDL: list[str]         # line 124 — 6 statements, sites before locations
class FieldsyncSchemaManager:                       # line 134
    def __init__(self, pool: Any) -> None            # line 154
    async def initialize(self) -> None               # line 158 — `for sql in _ALL_DDL: await conn.execute(sql)`
    @staticmethod
    def ddl_statements() -> list[str]                # line 178 — returns list(_ALL_DDL)

# From services/venue_service.py
class DuplicateVenueError(Exception)     # line 50  — __init__(self, kind: str, name: str)
class SiteNotFoundError(Exception)       # line 64  — __init__(self, site_id: int)
class LocationNotFoundError(Exception)   # line 76  — __init__(self, location_id: int)
class Site(BaseModel)                    # line 93  — extra="forbid"; site_id, store_id: str, client_id, org_id, name, is_active, tenant
class Location(BaseModel)                # line 121 — latitude/longitude: float | None, geofence_radius_m: int | None
_INSERT_SITE_SQL: str                    # line 162 — plain INSERT … VALUES ($1..$4) RETURNING …
_INSERT_LOCATION_SQL: str                # line 182 — plain INSERT … VALUES ($1..$8) RETURNING …
class VenueService:                      # line 211
    def __init__(self, pool: Any) -> None                                              # line 226
    async def create_site(self, *, store_id: str, client_id: int, org_id: int,
                          name: str, tenant: str | None = None) -> Site                 # line 234
    async def get_site(self, site_id: int, *, org_id: int, tenant: str | None = None) -> Site  # line 270
    async def list_sites(self, *, store_id: str, org_id: int, tenant: str | None = None) -> list[Site]  # line 292
    async def create_location(self, *, site_id: int, client_id: int, org_id: int, name: str,
                              location_type: str = "kiosk", latitude: float | None = None,
                              longitude: float | None = None, geofence_radius_m: int | None = None,
                              tenant: str | None = None) -> Location                    # line 314
    async def get_location(self, location_id: int, *, org_id: int, tenant: str | None = None) -> Location  # line 366
    async def list_locations(self, *, site_id: int, org_id: int, tenant: str | None = None) -> list[Location]  # line 389
    # create_* catch `Exception`, test `is_unique_violation(exc)`, raise DuplicateVenueError, else re-raise (259-266, 347-362)

# From services/_db_utils.py
_UNIQUE_VIOLATION_CODE = "23505"                 # line 5
def is_unique_violation(exc: Exception) -> bool  # line 8 — checks type name, .sqlstate/.pgcode, message text

# From services/org_graph.py
_SQL_GET_STORES_FOR_CLIENT: str   # line 157 — SELECT store_id, store_name, market_id FROM networkninja.stores_geographies
                                  #            WHERE client_id = $1 AND orgid = $2   (NOTE at 154-156: columns unverified)
_SQL_GET_CLIENT_SCOPED: str       # line 179 — SELECT c.client_id, c.client_name FROM auth.clients c
                                  #            JOIN auth.organization_clients oc ON oc.client_id = c.client_id
                                  #            WHERE c.client_id = $1 AND oc.org_id = $2
class OrgGraphService:            # line 196 — pool or FIELDSYNC_AUTH_RO_DSN (line 232)
    async def get_node(self, node_type: NodeType, node_id: str, *, tenant: str, org_id: int) -> OrgNode  # line 474
        # node_type == "client": conn.fetch(_SQL_GET_CLIENT_SCOPED, int(node_id), org_id); empty → KeyError (519-525)

# From api/handlers.py
def _get_org_id(self, request: web.Request) -> int | None   # line 221 — request.user.organizations[0].org_id → int, else None
def _session_tenant(self, request: web.Request) -> str      # line 297
async def create_site(self, request: web.Request) -> web.Response      # line 2682 — client_id from body (2710-2716), org_id from session (2718)
async def create_location(self, request: web.Request) -> web.Response  # line 2771 — site_id from path (2800-2804), client_id body (2811-2817),
                                                                       #   latitude/longitude/geofence_radius_m passed raw (2831-2833),
                                                                       #   only DuplicateVenueError → 409, else 500 (2836-2842)
async def get_location(self, request: web.Request) -> web.Response     # line 2846 — LocationNotFoundError → 404 pattern (2872-2876)

# From api/routes.py
app.router.add_post(f"{bp}/org/stores/{{store_id}}/sites", _wrap_auth(handler.create_site, tenant="none"))       # line 539-542
app.router.add_post(f"{bp}/org/sites/{{site_id}}/locations", _wrap_auth(handler.create_location, tenant="none")) # line 547-550
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_formdesigner.services.venue_service import (          # services/venue_service.py
    VenueService, Site, Location,
    DuplicateVenueError, SiteNotFoundError, LocationNotFoundError,
)
from parrot_formdesigner.services.fieldsync_schema import FieldsyncSchemaManager  # services/fieldsync_schema.py:134
from parrot_formdesigner.services._db_utils import is_unique_violation            # services/_db_utils.py:8
from parrot_formdesigner.services.org_graph import OrgGraphService, OrgNode, NodeType  # services/org_graph.py:42,65,196
# handlers.py imports VenueService at line 105 and re-imports the exceptions lazily inside the except blocks
```

#### Key Attributes & Constants
- `_ALL_DDL` → `list[str]` of 6 statements (`services/fieldsync_schema.py:124-131`); `test_ddl_statements_returns_six` (`tests/unit/test_fieldsync_schema.py:95`) pins the count.
- `_UNIQUE_VIOLATION_CODE = "23505"` (`services/_db_utils.py:5`); Postgres SQLSTATE for CHECK violation is `23514`, FK violation `23503`, insufficient privilege `42501`.
- Test fake-pool helpers: `_row`, `_make_conn(fetchrow_result, fetch_result, fetchrow_side_effect)`, `_make_pool(conn)`, `_site_row(...)`, `_location_row(...)` (`tests/unit/test_venue_service.py:39-120`).
- Org-graph fake fixture keys queries by table name substring (`tests/unit/test_org_graph_service.py:388-396`), so a column rename in `_SQL_GET_STORES_FOR_CLIENT` does not break it.
- `OrgGraphService` queries `auth.*`, `networkninja.*` and `fieldsync.*` through **one** pool (`services/org_graph.py:106-176`) — evidence the three schemas share a database.
- Upstream spec: `Trocdigital/fieldsync` → `sdd/specs/store-venue-substructure.spec.md` (FEAT-330 v0.3, reachable via `gh api repos/Trocdigital/fieldsync/contents/...`). Q2 there: `stores_geographies` confirmed as the table on 2026-06-12, column names explicitly left "to confirm when coding the query".
- `FieldsyncSchemaManager.initialize()` is **not called anywhere in this repo**; the consuming FieldSync application wires it at startup.
- No handler tests exist for the venue routes: `tests/unit/api/test_route_tenant_coverage.py:70-72` only lists the three paths; `test_api_feat302.py` / `test_feat302_review_fixes.py` have zero `create_site` / `create_location` references.
- No real-Postgres fixture in `parrot-formdesigner/tests` (`tests/integration/conftest.py`, `tests/fixtures/persistence.py` checked).
- `ProjectService.create_project` (`services/project_service.py:214`) has the **same** missing client-membership guard — out of scope here, candidate ledger issue.

### Does NOT Exist (Anti-Hallucination)
- ~~`ClientNotInOrgError`~~, ~~`VenueValidationError`~~ — not in `venue_service.py` yet; this feature introduces them.
- ~~`is_check_violation`~~, ~~`is_foreign_key_violation`~~ — `_db_utils.py` has only `is_unique_violation`.
- ~~`VenueService.validate_geofence(...)`~~, ~~`LocationCreate` / `SiteCreate` Pydantic input models~~ — the service takes keyword args; handlers read `body.get(...)` directly.
- ~~`FieldsyncSchemaManager.migrate()`~~ / ~~`upgrade()`~~ / ~~`_ALTER_DDL`~~ — only `initialize()` and `ddl_statements()` exist.
- ~~`uq_sites_id_org`~~, ~~`fk_locations_site_org`~~, ~~`ck_locations_*`~~ — proposed constraint names, not present in the DDL today.
- ~~`fieldsync.clients`~~ — client membership lives in `auth.organization_clients` (`org_graph.py:181`), there is no fieldsync-owned clients table.
- ~~`networkninja.stores`~~ — the table is `networkninja.stores_geographies` (upstream Q2); its column names are the thing still unverified.
- ~~`_get_tenant`~~ in handlers for the venue routes — the survivor is `_session_tenant` (`handlers.py:297`); the upstream spec's component diagram still names the old helper.
- ~~Venue handler tests~~ — none exist (see Key Attributes).
- ~~A Postgres test container / `FORMDESIGNER_TEST_DSN` fixture~~ — not present in this package's test tree.

---

## Parallelism Assessment

- **Internal parallelism**: partial. The DDL work (`fieldsync_schema.py` + its
  tests), the `_db_utils` helpers, and the `stores_geographies` verification
  (`org_graph.py`) touch disjoint files and can run as one parallel wave. The
  `venue_service.py` guard rewrite depends on nothing but should precede the
  handler task, which consumes the new exception names. Suggested order: wave 1
  = {schema ALTER block, `_db_utils` helpers, store-column verification}; wave 2
  = service guards + exceptions; wave 3 = handler validation/mapping + handler
  tests; wave 4 = docs/spec cross-reference + issue closure.
- **Cross-feature independence**: no conflict found. The only in-flight
  `parrot-formdesigner` worktree, `feat-FEAT-551-msteams-formdesigner-renderer`,
  has no diff under `services/` or `api/` versus `origin/dev`. FEAT-429
  (`fieldsync-tenant-url`) already landed and declares `requires_tenant` bodies
  "DO NOT MODIFY" — the venue routes are `tenant="none"` and untouched here.
  The upstream `Trocdigital/fieldsync` spec is read-only reference.
- **Recommended isolation**: `per-spec`.
- **Rationale**: five small edits across four source files in one package,
  with a strict service → handler dependency; one worktree with sequential (or
  lightly parallel) tasks is cheaper than per-task worktrees, and the DDL text
  must be reviewed as a single coherent diff.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `feature` on `dev`.
- [x] Scope — *Owner: Jesus Lara*: both HIGH findings plus all three medium items.
- [x] Have the venue tables received data anywhere? — *Owner: Jesus Lara*: no, `initialize()` has not run against a shared environment; tables are empty.
- [x] Migration mechanics — *Owner: Jesus Lara*: idempotent ALTER block inside `initialize()` (no separate script, no "DDL text only").
- [x] Where the `client_id` membership check lives — *Owner: Jesus Lara*: service-level `WHERE EXISTS` on `auth.organization_clients`, same statement as the insert.
- [x] Composite FK `(site_id, org_id)` — *Owner: Jesus Lara*: yes, add it (plus the `UNIQUE (site_id, org_id)` it requires on `sites`).
- [x] Geofence bounds — *Owner: Jesus Lara*: handler returns 400 **and** the DDL adds CHECK constraints.
- [x] `networkninja.stores_geographies` columns — *Owner: Jesus Lara*: a verification task inside the feature (documented catalog query, `ENV=prod`), not a brainstorm-time check.
- [ ] Does the DB role behind the **VenueService** pool have `SELECT` on `auth.organization_clients`? (`OrgGraphService` uses `FIELDSYNC_AUTH_RO_DSN`; the venue pool is wired by the FieldSync app, not this repo.) If not, the grant is a deployment prerequisite to document in the spec. — *Owner: Jesus Lara / FieldSync ops*
- [x] Should `create_site` also verify that `store_id` belongs to the org via `networkninja.stores_geographies` (`client_id` + `orgid`)? — *Owner: Jesus Lara*: yes, same `EXISTS` pattern; 0 rows ⇒ 404 `StoreNotFoundError`; depends on the column-verification task.
- [x] Pairing rule for the geofence trio: is `geofence_radius_m` without coordinates a 400? — *Owner: Jesus Lara*: reject — radius requires coordinates (handler 400 + CHECK `geofence_radius_m IS NULL OR (latitude IS NOT NULL AND longitude IS NOT NULL)`); lat/lon both-or-neither; coordinates without radius stay allowed (`NULL ⇒ disabled`).
- [x] Should `ProjectService.create_project` get the same client-membership guard in this feature? — *Owner: Jesus Lara*: no — ledger follow-up only (`wikitoolkit ledger open` against `services/project_service.py`), feature stays scoped to #1005.
- [ ] Is a manual run of `initialize()` against a disposable Postgres (v1 DDL applied first, then v2) acceptable as the validation evidence for the ALTER block, given there is no Postgres test fixture in this package? — *Owner: Jesus Lara*
- [ ] Should the upstream `Trocdigital/fieldsync` FEAT-330 spec receive an errata note pointing at this feature, or is the GitHub issue closure enough? — *Owner: Jesus Lara*
