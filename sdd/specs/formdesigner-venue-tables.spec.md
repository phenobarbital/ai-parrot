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

# Feature Specification: FieldSync venue tables — tenant-safe constraints and ownership-checked writes

**Feature ID**: FEAT-640
**Date**: 2026-10-08
**Author**: Jesus Lara + Claude
**Status**: draft
**Target version**: parrot-formdesigner next minor
**Closes**: GitHub issue [#1005](https://github.com/phenobarbital/ai-parrot/issues/1005)
**Brainstorm**: `sdd/proposals/formdesigner-venue-tables.brainstorm.md` (accepted, Option B)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

PR #998 (FEAT-330 "Store Venue Sub-Structure — Site/Location", merged to `dev`
2026-07-10, then `#1004 → main`) shipped `fieldsync.sites` / `fieldsync.locations`
and the `VenueService` CRUD without addressing two HIGH findings raised in the
pre-merge code review. GitHub issue #1005 tracks them. Verified 2026-10-08: the
last commit touching `venue_service.py` and `fieldsync_schema.py` is still the
original FEAT-330 merge (`810a521eb`) — **nothing has been fixed yet**.

The venue tables are the system of record for the per-location geofence that
gates visit check-ins (FEAT-303 §8 / FEAT-318 D5.7), so a cross-org write
corrupts another organisation's operational data.

The five findings, all in scope:

1. **HIGH — `create_location` allows cross-org writes.** `_INSERT_LOCATION_SQL`
   (`venue_service.py:182-189`) inserts the caller-supplied `site_id` with the
   *session* `org_id` without checking that the parent site belongs to that org.
   `site_id` is an enumerable `SERIAL`. Consequences: a name-existence oracle
   across orgs via 409 (`uq_locations_site_name` is org-agnostic), silent
   cross-org data loss through `ON DELETE CASCADE`, and inconsistent rows
   (`location.org_id ≠ site.org_id`) invisible to both org graphs.
2. **HIGH — UNIQUE constraints omit `org_id`.** `uq_sites_store_name UNIQUE
   (store_id, client_id, name)` (`fieldsync_schema.py:99`) and
   `uq_locations_site_name UNIQUE (site_id, name)` (`:118`) collide across orgs →
   name oracle + name squatting. The DDL is `CREATE TABLE IF NOT EXISTS`, so
   editing the text alone never reaches a database where the table already exists.
3. **MEDIUM — `client_id` comes from the request body** in `create_site`
   (`handlers.py:2710-2716`) and `create_location` (`:2811-2817`) with no check
   that the client belongs to the session org.
4. **MEDIUM — no bounds on `latitude` / `longitude` / `geofence_radius_m`.** The
   handler passes `body.get("latitude")` etc. straight through
   (`handlers.py:2831-2833`); a string or out-of-range value surfaces as a 500.
5. **MEDIUM — `networkninja.stores_geographies` column names are unverified.**
   `_SQL_GET_STORES_FOR_CLIENT` (`org_graph.py:157-161`) carries a NOTE saying so;
   the upstream FEAT-330 spec deferred the confirmation to coding time and it
   never happened.

**Why now**: `FieldsyncSchemaManager.initialize()` has **not yet** run against any
shared environment (resolved in brainstorm), so the tables are empty everywhere.
Constraint changes are instantaneous today and need a data migration the moment
rows land.

### Goals

- G1. A location can only be created under a site of the caller's own
  organisation; any other `site_id` yields a 404 indistinguishable from a
  missing site.
- G2. A site can only be created under a store that belongs to the caller's
  organisation and client (resolved in brainstorm: same `EXISTS` pattern as G1).
- G3. `client_id` must be a member of the session organisation
  (`auth.organization_clients`), enforced in the same SQL statement as the
  write, for both sites and locations.
- G4. Name uniqueness is scoped per organisation; the database itself cannot
  hold a location whose `org_id` differs from its site's (composite FK).
- G5. `initialize()` converges **both** a fresh database and one that already
  carries the v1 tables, and remains a no-op on re-run — the DDL doctrine's own
  "ALTER TABLE idempotente" escape hatch (`fieldsync_schema.py:18-19`), no
  migration framework.
- G6. Geofence inputs are validated at the handler (400 naming the field) **and**
  by CHECK constraints: latitude ∈ [-90, 90], longitude ∈ [-180, 180],
  `geofence_radius_m` a positive integer, latitude/longitude both present or both
  absent, and a radius requires coordinates (resolved in brainstorm).
- G7. The `networkninja.stores_geographies` column names are verified against
  the production catalog and `_SQL_GET_STORES_FOR_CLIENT` is corrected; the
  "unverified" NOTE is removed.
- G8. Everything stays unit-testable with the existing fake asyncpg pool; the
  feature's PR closes issue #1005.

### Non-Goals (explicitly out of scope)

- **`ProjectService.create_project`** has the same missing client-membership
  guard (`project_service.py:214`). Resolved in brainstorm: ledger follow-up
  only — this feature opens a `wikitoolkit ledger` issue (M6) and does not touch
  `project_service.py`.
- Row-Level Security policies on `fieldsync.*` (brainstorm Option C, rejected:
  does not fix the UNIQUE keys, needs `SET LOCAL` transactions the fake pool
  cannot exercise, and depends on role audits outside this repo).
- A separate migration script or a migrations framework (brainstorm Option A /
  "DDL text only", rejected: never reaches an already-initialised database).
- Handler-level membership checks via `OrgGraphService.get_node` (rejected:
  extra round-trip, couples venue endpoints to a service that may be `None`,
  leaves `VenueService` unsafe for direct callers).
- Changes to the read paths (`get_site`, `list_sites`, `get_location`,
  `list_locations`) — they already filter by `org_id`.
- Backfilling or migrating existing rows — there are none (resolved in
  brainstorm).
- Wiring `FieldsyncSchemaManager.initialize()` into an app startup in this repo —
  the consuming FieldSync application owns that call.
- A startup probe for the `SELECT` grant on `auth.organization_clients` (open
  question §8 Q1; documented as a deployment prerequisite).

---

## 2. Architectural Design

### Overview

Option B from the brainstorm: **make the database unable to hold a location
whose org/client disagrees with its site, make the service unable to attempt
any cross-org or cross-client write, and make `initialize()` converge any
environment to that shape.** Scope of the guarantees (design research S6): the
composite FK and the CHECKs hold for *every* writer, including raw SQL; the
store-ownership and client-membership predicates hold for writes that go through
`VenueService` (a raw `INSERT` into `fieldsync.sites` with an arbitrary
`client_id` is not prevented by the schema — the auth tables are not FK-able
from here).

1. **Schema convergence (M1).** The two `CREATE TABLE IF NOT EXISTS` texts are
   rewritten with v2 constraint names (org-scoped UNIQUEs, `UNIQUE (site_id,
   org_id)` on sites, a composite FK on locations, five CHECKs on the geofence
   trio). A new ordered block of idempotent ALTER statements is appended to
   `_ALL_DDL`: `DROP CONSTRAINT IF EXISTS` for the three v1 names, then one
   catalog-guarded `DO $$ … IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE
   conrelid = '<table>'::regclass AND conname = '…') THEN ALTER TABLE … ADD
   CONSTRAINT … END IF $$` block per v2 constraint (Postgres has no `ADD
   CONSTRAINT IF NOT EXISTS`; the guard is **relation-scoped**, not name-only —
   design research S3). v2 names differ from v1 names so the drop/add pair is
   unambiguous and re-runnable. `initialize()` now runs the whole `_ALL_DDL`
   sequence inside **one transaction** opened after `SELECT
   pg_advisory_xact_lock(hashtext('fieldsync.schema_manager'))` (design research
   S1): a failing `ADD` rolls the drops back, so a database is never left with
   fewer protections than it started with, and two app workers starting at once
   serialise instead of racing the catalog check. `ddl_statements()` grows from 6
   to 18 (the lock statement is a separate constant, not part of `_ALL_DDL`).
2. **Driver error helpers (M2).** `_db_utils.py` gains `is_check_violation()`
   (SQLSTATE `23514`) and `is_foreign_key_violation()` (`23503`) next to
   `is_unique_violation()`, same detection strategy (type name, `.sqlstate` /
   `.pgcode`, message text).
3. **Ownership-checked writes (M3).** Both INSERT constants become
   `INSERT … SELECT $1, $2, … WHERE EXISTS (parent ∈ org) AND EXISTS (client ∈
   org)`. For locations the parent predicate is `(site_id, client_id, org_id)`:
   a location's `client_id` must equal its site's (design research S5 — the
   composite FK carries `client_id` too, so a client-B location under a
   client-A site is impossible even within one org). `fetchrow` returning `None` means a guard failed; the service then runs
   one follow-up existence query on the **parent** (site for locations, store for
   sites) to decide which exception to raise — `SiteNotFoundError` /
   `StoreNotFoundError` when the parent is not in the org, otherwise
   `ClientNotInOrgError`. Parent precedence hides nothing new: the caller already
   named the parent in the URL. A shared `validate_geofence()` helper enforces
   G6 in Python and is called by `create_location` itself (direct callers) and
   by the handler (clean 400 before any DB round-trip). CHECK violations that
   still reach the DB map to `VenueValidationError`; a FK violation on the
   location insert (site deleted between the guard and the write) maps to
   `SiteNotFoundError`.
4. **Handler validation and mapping (M4).** Both POST handlers first require
   the decoded body to be a JSON object (a list/scalar body is 400, not the
   `AttributeError` → 500 of today — design research S8); `create_location`
   then validates the geofence trio through `validate_geofence()` and returns
   400 with the offending field; both POST handlers map `SiteNotFoundError`,
   `StoreNotFoundError` and `ClientNotInOrgError` → 404 and
   `VenueValidationError` → 400, keeping `DuplicateVenueError` → 409 and the
   generic 500. New handler tests cover every branch (none exist today).
5. **Store column verification (M5).** A human-gated task runs the documented
   `information_schema.columns` query against the production catalog
   (`ENV=prod`), records the real names in its Completion Note, edits
   `_SQL_GET_STORES_FOR_CLIENT` **and** the new `_SELECT_STORE_IN_ORG_SQL` in
   M3 if they differ from the assumed `store_id` / `client_id` / `orgid`, and
   deletes the NOTE. Any physical-column rename is done with `AS store_id` /
   `AS store_name` / `AS market_id` aliases so the row keys that
   `_attach_store_substructure()` reads (`org_graph.py:416-424`) never change
   (design research S9).
6. **Closure (M6).** Ledger issue for the `ProjectService` gap, a short
   deployment note (grant + "run `initialize()` once after upgrade"), PR body
   `Closes #1005`.

Decisions carried verbatim from the brainstorm: feature on `dev`; all five
findings in scope; tables empty; idempotent ALTER inside `initialize()`;
service-level `EXISTS` on `auth.organization_clients`; composite FK; handler
400 + DB CHECK; `stores_geographies` verification as a task; `store_id`
ownership in `create_site`; radius requires coordinates; `ProjectService` to
the ledger.

### Component Diagram

```
navigator-auth session ──org_id──▶ FormAPIHandler.create_site / create_location   (api/handlers.py)
                                        │  validate_geofence()  → 400 VenueValidationError
                                        │  client_id (body), store_id / site_id (path)
                                        ▼
                                   VenueService.create_site / create_location    (services/venue_service.py)
                                        │  INSERT … SELECT … WHERE EXISTS(parent ∈ org) AND EXISTS(client ∈ org)
                                        │  0 rows → follow-up parent probe → SiteNotFoundError | StoreNotFoundError | ClientNotInOrgError
                                        │  23505 → DuplicateVenueError · 23514 → VenueValidationError · 23503 → SiteNotFoundError
                                        ▼
            ┌──────────────── one asyncpg pool (auth.* + networkninja.* + fieldsync.*) ────────────────┐
            │ auth.organization_clients   networkninja.stores_geographies   fieldsync.sites / locations │
            └──────────────────────────────────────────────────────────────────────────────────────────┘
                                        ▲
FieldsyncSchemaManager.initialize() ────┘  CREATE TABLE IF NOT EXISTS (v2 text)  +  DROP IF EXISTS v1  +  DO $$ ADD v2 IF MISSING $$
            (services/fieldsync_schema.py — called by the FieldSync app at startup, not by this repo)

_db_utils.is_unique_violation / is_check_violation / is_foreign_key_violation  ← used by VenueService
org_graph._SQL_GET_STORES_FOR_CLIENT  ← column names verified in M5 (same names reused by _SELECT_STORE_IN_ORG_SQL)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FieldsyncSchemaManager` / `_ALL_DDL` (`services/fieldsync_schema.py:124-171`) | modifies | v2 constraint text in `_CREATE_SITES_SQL` / `_CREATE_LOCATIONS_SQL`; new `_ALTER_VENUE_V2_SQL` statements appended; `initialize()` body untouched |
| `VenueService` (`services/venue_service.py:211`) | modifies | both INSERT constants, two follow-up probe constants, three new exceptions, `validate_geofence()` helper, error mapping in both `create_*` |
| `_db_utils` (`services/_db_utils.py`) | extends | two new predicate helpers |
| `FormAPIHandler.create_site` / `create_location` (`api/handlers.py:2682`, `:2771`) | modifies | geofence validation, 404/400 mapping |
| `OrgGraphService._SQL_GET_STORES_FOR_CLIENT` (`services/org_graph.py:157`) | modifies | verified column names; NOTE removed |
| `auth.organization_clients` (navigator-auth table) | depends on | membership predicate; the venue pool's DB role needs `SELECT` on it (§8 Q1) |
| `networkninja.stores_geographies` | depends on | store-ownership predicate; columns verified in M5 |
| `tests/unit/test_fieldsync_schema.py`, `tests/unit/test_venue_service.py` | extends | DDL text, statement count, guard + exception tests |
| `tests/unit/api/test_venue_handlers.py` | creates | first handler tests for the three venue routes |
| FieldSync application (external) | depends on | must run `initialize()` once after upgrading; grant prerequisite |
| GitHub issue #1005 | closes | PR body `Closes #1005` |

No breaking API change: new 404/400 paths only; 201/409 unchanged within an org.
Direct Python callers of `VenueService.create_*` may now see the three new
exceptions — all are subclasses of `Exception` like the existing ones.

### Data Models

```python
# services/venue_service.py — existing models unchanged (Site line 93, Location line 121).
# New value object returned by validate_geofence():
class GeofenceParams(BaseModel):
    """Validated geofence trio. Invariants: lat/lon both set or both None;
    radius > 0; radius requires coordinates (brainstorm resolution)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_m: int | None = None
```

Schema v2 (final constraint set — names are the contract `/sdd-task` builds on):

```sql
-- fieldsync.sites
CONSTRAINT uq_sites_org_store_name  UNIQUE (org_id, store_id, client_id, name)
CONSTRAINT uq_sites_id_client_org   UNIQUE (site_id, client_id, org_id)   -- composite-FK target (S5)

-- fieldsync.locations  (the inline `REFERENCES fieldsync.sites (site_id)` on site_id is REMOVED from the CREATE text)
CONSTRAINT uq_locations_org_site_name    UNIQUE (org_id, site_id, name)
CONSTRAINT fk_locations_site_client_org  FOREIGN KEY (site_id, client_id, org_id)
                                         REFERENCES fieldsync.sites (site_id, client_id, org_id) ON DELETE CASCADE
CONSTRAINT ck_locations_latitude         CHECK (latitude  IS NULL OR (latitude  >= -90  AND latitude  <= 90))
CONSTRAINT ck_locations_longitude        CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180))
CONSTRAINT ck_locations_latlon_pair      CHECK ((latitude IS NULL) = (longitude IS NULL))
CONSTRAINT ck_locations_geofence_radius  CHECK (geofence_radius_m IS NULL OR geofence_radius_m > 0)
CONSTRAINT ck_locations_radius_needs_center CHECK (geofence_radius_m IS NULL OR latitude IS NOT NULL)
```

v1 names dropped by the ALTER block: `uq_sites_store_name`,
`uq_locations_site_name`, `locations_site_id_fkey` (Postgres' auto-name for the
v1 inline FK).

### New Public Interfaces

```python
# services/venue_service.py
class StoreNotFoundError(Exception):
    """Raised when the parent store is not visible to the caller's org/client (404)."""
    def __init__(self, store_id: str) -> None: ...

class ClientNotInOrgError(Exception):
    """Raised when ``client_id`` is not a member of ``org_id`` (404)."""
    def __init__(self, client_id: int, org_id: int) -> None: ...

class VenueValidationError(ValueError):
    """Raised when a geofence value is out of bounds or inconsistent (400)."""
    def __init__(self, field: str, message: str) -> None: ...

def validate_geofence(
    latitude: Any, longitude: Any, geofence_radius_m: Any,
) -> GeofenceParams: ...

# services/_db_utils.py
def is_check_violation(exc: Exception) -> bool: ...
def is_foreign_key_violation(exc: Exception) -> bool: ...

# services/fieldsync_schema.py — no new public API; ddl_statements() still returns the DDL only (18 statements);
# initialize() additionally executes _ADVISORY_LOCK_SQL first, inside one transaction.
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Schema v2 + converging ALTER block | yes | constraint names and bodies fixed in §2 Data Models; `_ALTER_VENUE_V2_SQL` list appended to `_ALL_DDL`; relation-scoped `DO $$` guard shape fixed; `ddl_statements()` == 18; `initialize()` = advisory lock + one transaction + the same loop | — |
| M2: `_db_utils` violation helpers | yes | two functions mirroring `is_unique_violation` (type name → sqlstate/pgcode → message text); codes `23514` / `23503` | — |
| M3: VenueService ownership guards | yes | SQL constants, exception classes, precedence rule, `validate_geofence` contract and error mapping fixed in §3/§6 | — |
| M4: Handler validation + mapping | yes | status codes and JSON shapes fixed; reuses the `_make_request` pattern from `test_api_feat302.py:46` for tests | — |
| M5: `stores_geographies` column verification | **no** | needs a human with `ENV=prod` DB access to run the catalog query; the edit itself is mechanical once the names are known | requires production credentials; orchestrator/human-run |
| M6: Closure (ledger issue, deployment note, PR wording) | yes | `wikitoolkit ledger open` arguments fixed below; note text location fixed | — |

### Module 1: Schema v2 + converging ALTER block
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/fieldsync_schema.py`,
  `packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py`
- **Responsibility**: v2 constraint set in the `CREATE TABLE` texts; idempotent
  ALTER block so an already-initialised database converges; DDL text tests and
  the statement-count update.
- **Depends on**: nothing in this spec (FEAT-302/330 DDL already on `dev`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # services/fieldsync_schema.py  (modifies fieldsync_schema.py:89-131)
  _CREATE_SITES_SQL: str       # verified: fieldsync_schema.py:89  — v2 text: uq_sites_org_store_name + uq_sites_id_org
  _CREATE_LOCATIONS_SQL: str   # verified: fieldsync_schema.py:103 — v2 text: no inline REFERENCES on site_id;
                               #   uq_locations_org_site_name, fk_locations_site_org, five ck_locations_* constraints

  _V1_VENUE_CONSTRAINTS: tuple[tuple[str, str], ...]
      """(table, constraint_name) pairs dropped with DROP CONSTRAINT IF EXISTS:
      ('fieldsync.sites', 'uq_sites_store_name'), ('fieldsync.locations', 'uq_locations_site_name'),
      ('fieldsync.locations', 'locations_site_id_fkey')."""

  _V2_VENUE_CONSTRAINTS: tuple[tuple[str, str, str], ...]
      """(table, constraint_name, definition) in dependency order — uq_sites_id_client_org BEFORE fk_locations_site_client_org."""

  _ADVISORY_LOCK_SQL: str
      """``SELECT pg_advisory_xact_lock(hashtext('fieldsync.schema_manager'));`` — executed first, inside the
      transaction, so concurrent initialize() calls serialise (released at COMMIT/ROLLBACK)."""

  def _drop_constraint_if_exists(table: str, name: str) -> str:
      """Return ``ALTER TABLE <table> DROP CONSTRAINT IF EXISTS <name>;``."""

  def _add_constraint_if_missing(table: str, name: str, definition: str) -> str:
      """Return a ``DO $$ … $$`` block that adds ``<name>`` to ``<table>`` only when
      ``pg_constraint`` has no row with ``conrelid = '<table>'::regclass AND conname = '<name>'``
      (relation-scoped, never name-only). ``definition`` is the text after ``ADD CONSTRAINT <name>``
      (e.g. ``UNIQUE (site_id, client_id, org_id)``)."""

  _ALTER_VENUE_V2_SQL: list[str]
      """3 drops followed by 9 catalog-guarded adds; appended to _ALL_DDL after _CREATE_LOCATIONS_SQL."""

  _ALL_DDL: list[str]          # verified: fieldsync_schema.py:124 — now 6 + 12 = 18 statements

  class FieldsyncSchemaManager:            # verified: fieldsync_schema.py:134
      async def initialize(self) -> None   # verified: fieldsync_schema.py:158 — body becomes:
          """async with self._pool.acquire() as conn:
                 async with conn.transaction():
                     await conn.execute(_ADVISORY_LOCK_SQL)
                     for sql in _ALL_DDL: await conn.execute(sql)
          All-or-nothing: a failing ADD CONSTRAINT rolls back the preceding DROPs. Any asyncpg error propagates."""
      @staticmethod
      def ddl_statements() -> list[str]    # verified: fieldsync_schema.py:178 — unchanged, returns 18
  ```
  Module docstring (lines 1-26) gains a paragraph describing the v1→v2 venue
  convergence and the rule "new constraint ⇒ new name + guarded ADD".

### Module 2: `_db_utils` violation helpers
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py`,
  tests appended to `packages/parrot-formdesigner/tests/unit/test_venue_service.py`
  (a `TestDbUtils` class; no dedicated test module exists for `_db_utils` today).
- **Responsibility**: driver-agnostic predicates for CHECK and FK violations.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # services/_db_utils.py  (modifies _db_utils.py:5-20)
  _UNIQUE_VIOLATION_CODE = "23505"        # verified: _db_utils.py:5
  _CHECK_VIOLATION_CODE = "23514"
  _FOREIGN_KEY_VIOLATION_CODE = "23503"

  def is_unique_violation(exc: Exception) -> bool:        # verified: _db_utils.py:8 — unchanged
  def is_check_violation(exc: Exception) -> bool:
      """True for asyncpg ``CheckViolationError``, any exc with sqlstate/pgcode 23514,
      or a message containing ``violates check constraint``."""
  def is_foreign_key_violation(exc: Exception) -> bool:
      """True for asyncpg ``ForeignKeyViolationError``, sqlstate/pgcode 23503,
      or a message containing ``violates foreign key constraint``."""
  ```

### Module 3: VenueService ownership guards
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py`,
  `packages/parrot-formdesigner/tests/unit/test_venue_service.py`
- **Responsibility**: `EXISTS`-guarded inserts, precise exception on a failed
  guard, geofence validation helper, DB-error mapping.
- **Depends on**: M2 (imports the two new helpers). The store predicate's column
  names are the ones M5 verifies; M3 is written against the assumed
  `store_id` / `client_id` / `orgid` and M5 adjusts `_SELECT_STORE_IN_ORG_SQL`
  and `_INSERT_SITE_SQL` if the catalog says otherwise (M5 lists both constants
  in its edit scope).
- **Interface Skeleton**:
  ```python
  # services/venue_service.py  (modifies venue_service.py:43, 64-86, 162-204, 234-266, 314-364)
  from ._db_utils import is_check_violation, is_foreign_key_violation, is_unique_violation  # verified: venue_service.py:43 (extend)

  class StoreNotFoundError(Exception):
      """Parent store ``store_id`` is not visible to (``client_id``, ``org_id``) — maps to 404."""
      def __init__(self, store_id: str) -> None: ...   # attribute: store_id

  class ClientNotInOrgError(Exception):
      """``client_id`` is not a member of ``org_id`` per auth.organization_clients — maps to 404."""
      def __init__(self, client_id: int, org_id: int) -> None: ...   # attributes: client_id, org_id

  class VenueValidationError(ValueError):
      """A geofence value is out of range or inconsistent — maps to 400."""
      def __init__(self, field: str, message: str) -> None: ...   # attributes: field, message

  class GeofenceParams(BaseModel): ...   # see §2 Data Models

  def validate_geofence(latitude: Any, longitude: Any, geofence_radius_m: Any) -> GeofenceParams:
      """Coerce and validate the trio. Rules: bool is rejected for every field; latitude/longitude
      accept int|float (finite) → float, latitude ∈ [-90, 90], longitude ∈ [-180, 180], both present
      or both None; geofence_radius_m accepts int > 0 (no float, no str) or None; a radius without
      coordinates is rejected. Raises VenueValidationError(field, message) naming the FIRST failing
      field in the order latitude, longitude, geofence_radius_m, then the pairing rules."""

  _INSERT_SITE_SQL: str          # verified: venue_service.py:162 — becomes
      # INSERT INTO fieldsync.sites (store_id, client_id, org_id, name)
      # SELECT $1, $2, $3, $4
      # WHERE EXISTS (SELECT 1 FROM networkninja.stores_geographies WHERE store_id = $1 AND client_id = $2 AND orgid = $3)
      #   AND EXISTS (SELECT 1 FROM auth.organization_clients WHERE client_id = $2 AND org_id = $3)
      # RETURNING site_id, store_id, client_id, org_id, name, is_active
  _INSERT_LOCATION_SQL: str      # verified: venue_service.py:182 — becomes
      # INSERT INTO fieldsync.locations (site_id, client_id, org_id, name, location_type, latitude, longitude, geofence_radius_m)
      # SELECT $1, $2, $3, $4, $5, $6, $7, $8
      # WHERE EXISTS (SELECT 1 FROM fieldsync.sites WHERE site_id = $1 AND client_id = $2 AND org_id = $3)
      #   AND EXISTS (SELECT 1 FROM auth.organization_clients WHERE client_id = $2 AND org_id = $3)
      # RETURNING location_id, site_id, client_id, org_id, name, location_type, latitude, longitude, geofence_radius_m, is_active
  _SELECT_STORE_IN_ORG_SQL: str  # new: SELECT 1 FROM networkninja.stores_geographies WHERE store_id = $1 AND client_id = $2 AND orgid = $3
  _SELECT_SITE_IN_ORG_SQL: str   # new: SELECT 1 FROM fieldsync.sites WHERE site_id = $1 AND client_id = $2 AND org_id = $3
                                 #   (a site of another client in the same org is "not found" for this client — S5)

  class VenueService:                                  # verified: venue_service.py:211
      async def create_site(self, *, store_id: str, client_id: int, org_id: int, name: str,
                            tenant: str | None = None) -> Site:                       # verified: venue_service.py:234
          """Unchanged signature. Raises DuplicateVenueError (23505), StoreNotFoundError (guard failed and the
          follow-up store probe returns no row), ClientNotInOrgError (guard failed, store probe found a row)."""
      async def create_location(self, *, site_id: int, client_id: int, org_id: int, name: str,
                                location_type: str = "kiosk", latitude: float | None = None,
                                longitude: float | None = None, geofence_radius_m: int | None = None,
                                tenant: str | None = None) -> Location:               # verified: venue_service.py:314
          """Unchanged signature. Calls validate_geofence() first (VenueValidationError before any DB call).
          Raises DuplicateVenueError (23505), VenueValidationError (23514), SiteNotFoundError (23503, or guard failed
          and the follow-up site probe returns no row), ClientNotInOrgError (guard failed, site probe found a row)."""
  ```
  Fake-pool contract for tests: the guarded insert is `conn.fetchrow(sql, …)`;
  the follow-up probe is a second `conn.fetchrow(probe_sql, …)` on the **same**
  acquired connection, so `_make_conn(fetchrow_side_effect=[None, None])`
  simulates "parent not in org" and `[None, row]` simulates "client not in org".

### Module 4: Handler validation + mapping
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`,
  `packages/parrot-formdesigner/tests/unit/api/test_venue_handlers.py` (new)
- **Responsibility**: 400 for bad geofence input before the service call;
  404 / 400 mapping for the new exceptions; the first handler tests for the
  venue routes.
- **Depends on**: M3 (exception names, `validate_geofence`).
- **Interface Skeleton**:
  ```python
  # api/handlers.py  (modifies handlers.py:2682-2739 and 2771-2844)
  class FormAPIHandler:                                                        # verified: handlers.py:110
      async def create_site(self, request: web.Request) -> web.Response:      # verified: handlers.py:2682
          """Docstring gains: 400 — body is not a JSON object; 404 — store not in org/client, or client not in org.
          After `body = await request.json()`: `if not isinstance(body, dict): return 400 {"error": "JSON body must be an object"}`.
          Lazy import extended to (DuplicateVenueError, StoreNotFoundError, ClientNotInOrgError);
          StoreNotFoundError | ClientNotInOrgError → JSONResponse({"error": str(exc)}, status=404)."""
      async def create_location(self, request: web.Request) -> web.Response:  # verified: handlers.py:2771
          """Docstring gains: 400 — body not a JSON object, or invalid geofence (body: {"error": <message>, "field": <name>});
          404 — site not in org/client, or client not in org. Same `isinstance(body, dict)` check as create_site.
          Calls validate_geofence(body.get("latitude"), body.get("longitude"), body.get("geofence_radius_m"))
          BEFORE the service call; VenueValidationError → 400 with the field name; passes the validated
          GeofenceParams values to the service. Lazy import extended to (DuplicateVenueError,
          SiteNotFoundError, ClientNotInOrgError, VenueValidationError); SiteNotFoundError |
          ClientNotInOrgError → 404; VenueValidationError → 400 (defensive — the pre-check already caught it)."""
  ```
  Tests build the handler as `FormAPIHandler(registry=MagicMock(spec=FormRegistry),
  venue_service=<AsyncMock service>)` and requests with a local copy of the
  `_make_request` helper shape from `tests/unit/test_api_feat302.py:46-85`
  (do **not** import it across test modules — see §7).

### Module 5: `networkninja.stores_geographies` column verification
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/org_graph.py`
  (and, only if the names differ, `_SELECT_STORE_IN_ORG_SQL` + `_INSERT_SITE_SQL`
  in `services/venue_service.py` plus their tests).
- **Responsibility**: resolve the FEAT-330 Q2 leftover. Run, with `ENV=prod`
  and the read-only DSN used by `OrgGraphService` (`FIELDSYNC_AUTH_RO_DSN`):
  ```sql
  SELECT column_name, data_type
  FROM information_schema.columns
  WHERE table_schema = 'networkninja' AND table_name = 'stores_geographies'
  ORDER BY ordinal_position;
  ```
  Record the full output in the task's Completion Note. If `store_id`,
  `store_name`, `market_id`, `client_id`, `orgid` all exist: delete the NOTE
  (`org_graph.py:154-156`) and leave the SQL. Otherwise edit
  `_SQL_GET_STORES_FOR_CLIENT` and the two M3 constants to the real physical
  names **with `AS store_id` / `AS store_name` / `AS market_id` aliases** so the
  row keys consumed by `_attach_store_substructure()` (`org_graph.py:416-424`)
  are unchanged, and update the SQL-text assertions in the tests. Either way
  add `test_stores_query_keeps_result_keys` (the SELECT list exposes exactly
  those three keys).
- **Depends on**: M3 (so the two venue constants exist to be adjusted).
- **Interface Skeleton**:
  ```python
  # services/org_graph.py  (modifies org_graph.py:154-161)
  _SQL_GET_STORES_FOR_CLIENT: str   # verified: org_graph.py:157 — column names confirmed; NOTE at 154-156 removed
  ```
- **Exclusive**: `parallel: false` — human-gated (production credentials), and
  it may touch M3's constants.

### Module 6: Closure
- **Path**: `docs/formdesigner/fieldsync-venue-v2.md` (new, short), the
  wikitoolkit ledger, the PR description.
- **Responsibility**:
  - `wikitoolkit ledger open --kind vulnerability --severity major
    --discovered-from spec:FEAT-640 --about
    sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/project_service.py#ProjectService.create_project
    --title "ProjectService.create_project accepts client_id without org-membership check"
    --body "<same EXISTS guard as FEAT-640 M3; see brainstorm formdesigner-venue-tables>"`.
  - Deployment note: the venue pool's role needs `SELECT` on
    `auth.organization_clients` and `networkninja.stores_geographies`; run
    `FieldsyncSchemaManager.initialize()` once after upgrading (v1 → v2
    constraints converge automatically); list the v2 constraint names.
  - PR body contains `Closes #1005`.
- **Depends on**: M1–M5 (documents their final shape).
- **Interface Skeleton**: none (docs + ledger only).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_sites_ddl_v2_constraints` | M1 | `_CREATE_SITES_SQL` contains `uq_sites_org_store_name UNIQUE (org_id, store_id, client_id, name)` and `uq_sites_id_client_org UNIQUE (site_id, client_id, org_id)`; does not contain `uq_sites_store_name` |
| `test_locations_ddl_v2_constraints` | M1 | contains `uq_locations_org_site_name`, `fk_locations_site_client_org … REFERENCES fieldsync.sites (site_id, client_id, org_id) ON DELETE CASCADE`, all five `ck_locations_*`; no inline `REFERENCES fieldsync.sites (site_id)` on the `site_id` column; no `uq_locations_site_name` |
| `test_alter_block_drops_v1_names` | M1 | the three `DROP CONSTRAINT IF EXISTS` statements name exactly `uq_sites_store_name`, `uq_locations_site_name`, `locations_site_id_fkey` |
| `test_alter_block_guarded_adds` | M1 | every ADD is wrapped in `DO $$` with a `pg_constraint` lookup; `uq_sites_id_client_org` precedes `fk_locations_site_client_org` in `_ALL_DDL` |
| `test_ddl_statements_returns_eighteen` | M1 | replaces `test_ddl_statements_returns_six` (`test_fieldsync_schema.py:95`); `test_ddl_statements_is_copy` updated to 18 |
| `test_initialize_executes_alter_block` | M1 | fake pool records 19 `execute` calls per run (`_ADVISORY_LOCK_SQL` first, then `_ALL_DDL` in order); twice → 38, no error |
| `test_initialize_runs_inside_one_transaction` | M1 | `_make_fake_pool()` gains `conn.transaction = MagicMock(return_value=<async CM>)`; assert it was entered once per run and the lock statement is the first `execute` |
| `test_initialize_propagates_db_error` (existing, `test_fieldsync_schema.py:140`) | M1 | still passes with the transaction double (error raised inside `__aenter__`'d CM propagates) |
| `test_add_constraint_guard_is_relation_scoped` | M1 | every `DO $$` block contains `conrelid = 'fieldsync.<table>'::regclass AND conname = '<name>'` |
| `test_is_check_violation_variants` / `test_is_foreign_key_violation_variants` | M2 | type-name match, `sqlstate`, `pgcode`, message text; negative cases (`23505` is not a check violation) |
| `test_site_insert_is_ownership_guarded` | M3 | `_INSERT_SITE_SQL` contains both `EXISTS` predicates (stores_geographies + organization_clients) and still targets `fieldsync.sites` (extends `TestSQLSafety`) |
| `test_location_insert_is_ownership_guarded` | M3 | `_INSERT_LOCATION_SQL` contains `EXISTS (SELECT 1 FROM fieldsync.sites WHERE site_id = $1 AND client_id = $2 AND org_id = $3)` and the client predicate |
| `test_create_location_other_client_same_org_is_not_found` | M3 | site belongs to another client of the same org ⇒ guard fails, probe (with `client_id`) returns no row ⇒ `SiteNotFoundError` (S5) |
| `test_create_location_cross_org_site_raises_404` | M3 | `fetchrow_side_effect=[None, None]` ⇒ `SiteNotFoundError(site_id)`; second call used `_SELECT_SITE_IN_ORG_SQL` |
| `test_create_location_client_not_in_org` | M3 | `fetchrow_side_effect=[None, _row({"?column?": 1})]` ⇒ `ClientNotInOrgError` with `client_id`, `org_id` |
| `test_create_site_store_not_in_org` / `test_create_site_client_not_in_org` | M3 | same two-call protocol with `_SELECT_STORE_IN_ORG_SQL` |
| `test_create_location_same_name_other_org_is_not_duplicate` | M3 | documents the new scoping: a row returns ⇒ 201 path (no `DuplicateVenueError`) |
| `test_create_location_check_violation_maps_to_validation_error` | M3 | `fetchrow_side_effect=<exc named CheckViolationError>` ⇒ `VenueValidationError` |
| `test_create_location_fk_violation_maps_to_site_not_found` | M3 | exc named `ForeignKeyViolationError` ⇒ `SiteNotFoundError` |
| `test_validate_geofence_accepts_valid` / `_rejects_out_of_range` / `_rejects_bool_and_str` / `_rejects_half_pair` / `_rejects_radius_without_center` / `_accepts_center_without_radius` / `_rejects_nan_inf` | M3 | table-driven; error `.field` is the first failing field in declared order |
| `test_create_location_validates_before_db` | M3 | invalid radius ⇒ `VenueValidationError` and `conn.fetchrow` never awaited |
| `test_create_handlers_400_on_non_object_body` | M4 | body `[]` / `"x"` / `null` ⇒ 400 for both handlers; service not called |
| `test_create_location_handler_400_on_bad_geofence` | M4 | body `latitude: 999` ⇒ 400, JSON has `field == "latitude"`; service not called; also `True`, `"12"`, `1.5` radius, `NaN`, one-sided coordinates |
| `test_create_location_handler_400_radius_without_center` | M4 | radius only ⇒ 400 `field == "geofence_radius_m"` |
| `test_create_location_handler_404_cross_org_site` | M4 | service raises `SiteNotFoundError` ⇒ 404 |
| `test_create_location_handler_404_client_not_in_org` | M4 | ⇒ 404 |
| `test_create_site_handler_404_store_not_in_org` / `_404_client_not_in_org` | M4 | ⇒ 404 |
| `test_create_location_handler_409_duplicate_unchanged` / `_201_passes_validated_values` | M4 | regression: 409 path intact; service receives floats/int from `GeofenceParams` |
| `test_create_handlers_501_without_service` | M4 | both handlers ⇒ 501 when `venue_service is None` (today's behaviour, now covered) |
| `test_stores_query_has_no_unverified_note` | M5 | `org_graph.py` source contains no `must be confirmed` NOTE; `_SQL_GET_STORES_FOR_CLIENT` names match the Completion-Note columns |

### Integration Tests

| Test | Description |
|---|---|
| *(manual, M1 validation evidence — §8 Q4)* | On a disposable Postgres: apply the **v1** DDL (from `git show 810a521eb:…/fieldsync_schema.py`), insert one site + one location, run v2 `initialize()` twice, then assert via `pg_constraint` that only v2 names exist, that a cross-org or cross-client `INSERT` into `locations` fails with `23503`, that `latitude = 999` fails with `23514`, and that two concurrent `initialize()` calls both succeed (advisory lock). Transcript saved to `artifacts/logs/FEAT-640-ddl-convergence.log` (git-ignored, `git add -f`). |

No automated Postgres fixture exists in `parrot-formdesigner/tests`; adding one
is out of scope (§8 Q4).

### Test Data / Fixtures

```python
# Reuse verbatim from tests/unit/test_venue_service.py:39-120
_row(data) ; _make_conn(fetchrow_result=None, fetch_result=None, fetchrow_side_effect=None)
_make_pool(conn) ; _site_row(...) ; _location_row(...)

# New in tests/unit/api/test_venue_handlers.py (local copy of the shape at tests/unit/test_api_feat302.py:46-85)
def _make_request(*, method="POST", body=None, match_info=None, org_id: int | None = 7) -> MagicMock: ...
def _make_handler(*, venue_service=None) -> FormAPIHandler: ...   # registry=MagicMock(spec=FormRegistry)

# Exception doubles for driver errors (no asyncpg import needed):
class CheckViolationError(Exception): ...        # type(exc).__name__ match
class ForeignKeyViolationError(Exception): ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `pytest packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py tests/unit/test_venue_service.py tests/unit/api/test_venue_handlers.py -q` passes (run with `PYTHONPATH=packages/parrot-formdesigner/src` inside the worktree).
- [ ] AC2. `ruff check` passes on every touched file.
- [ ] AC3. `_INSERT_LOCATION_SQL` carries `EXISTS (SELECT 1 FROM fieldsync.sites WHERE site_id = $1 AND client_id = $2 AND org_id = $3)`; a guarded insert returning no row raises `SiteNotFoundError`, which the handler maps to 404 with the same body as a missing site.
- [ ] AC4. `_INSERT_SITE_SQL` carries an `EXISTS` on `networkninja.stores_geographies` (`store_id`, `client_id`, `orgid` — or the names M5 verifies) and the handler maps `StoreNotFoundError` to 404.
- [ ] AC5. Both INSERTs carry `EXISTS (SELECT 1 FROM auth.organization_clients WHERE client_id = $2 AND org_id = $3)`; `ClientNotInOrgError` maps to 404 in both handlers.
- [ ] AC6. `_CREATE_SITES_SQL` / `_CREATE_LOCATIONS_SQL` contain exactly the v2 constraint set of §2 Data Models and none of the v1 names.
- [ ] AC7. `_ALL_DDL` ends with 3 `DROP CONSTRAINT IF EXISTS` statements followed by 9 `DO $$` relation-scoped (`conrelid = '…'::regclass AND conname = '…'`) `ADD CONSTRAINT` blocks, `uq_sites_id_client_org` before `fk_locations_site_client_org`; `ddl_statements()` returns 18; `initialize()` opens one `conn.transaction()` per run, executes `_ADVISORY_LOCK_SQL` first, and twice on the fake pool executes 38 statements without error.
- [ ] AC8. Manual convergence evidence (§4 Integration) shows a v1 database converging to v2 after one `initialize()` run and unchanged after the second, with the cross-org insert rejected by `23503` and the out-of-range latitude by `23514`; log committed under `artifacts/logs/`.
- [ ] AC9. `validate_geofence()` enforces: latitude ∈ [-90, 90], longitude ∈ [-180, 180], both-or-neither, radius positive int, radius requires coordinates, `bool`/`str`/`float` radius/NaN/inf rejected; both handlers return 400 for a non-object JSON body; the location handler returns 400 `{"error": …, "field": …}` and never calls the service on invalid input.
- [ ] AC10. `is_check_violation` / `is_foreign_key_violation` exist in `_db_utils.py`; `create_location` maps `23514` → `VenueValidationError` and `23503` → `SiteNotFoundError`.
- [ ] AC11. `org_graph.py` no longer contains the "must be confirmed" NOTE; the M5 task's Completion Note lists the real `networkninja.stores_geographies` columns with the catalog query output.
- [ ] AC12. A ledger issue exists for `ProjectService.create_project` (kind `vulnerability`, `discovered_from spec:FEAT-640`); `docs/formdesigner/fieldsync-venue-v2.md` documents the grant prerequisite and the one-time `initialize()` run; the PR body contains `Closes #1005`.
- [ ] AC13. No change to read paths or to the `Site` / `Location` models; 201 and 409 behaviour within one org is unchanged (regression tests in M3/M4).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

All paths relative to `packages/parrot-formdesigner/` unless noted. Re-verified
2026-10-08 on `dev` @ `288437532` (identical code to the brainstorm's `35ea61fb3`).

### Verified Imports
```python
from parrot_formdesigner.services.venue_service import (                 # verified: src/parrot_formdesigner/services/venue_service.py
    VenueService, Site, Location,                                        # lines 211, 93, 121
    DuplicateVenueError, SiteNotFoundError, LocationNotFoundError,       # lines 50, 64, 76
)
from parrot_formdesigner.services.fieldsync_schema import FieldsyncSchemaManager  # verified: services/fieldsync_schema.py:134
from parrot_formdesigner.services._db_utils import is_unique_violation            # verified: services/_db_utils.py:8
from parrot_formdesigner.services.org_graph import OrgGraphService, OrgNode, NodeType  # verified: services/org_graph.py:196, 65, 42
from parrot_formdesigner.api.handlers import FormAPIHandler                       # verified: src/parrot_formdesigner/api/handlers.py:110
from parrot_formdesigner.services.registry import FormRegistry                    # verified: used at tests/unit/test_api_feat302.py:38
from navigator.responses import JSONResponse                                      # verified: api/handlers.py:19
from pydantic import BaseModel, ConfigDict                                        # verified: services/venue_service.py:41
# venue_service.py imports the helper relatively:
from ._db_utils import is_unique_violation                                        # verified: services/venue_service.py:43
```

### Existing Class Signatures
```python
# services/fieldsync_schema.py
_CREATE_SCHEMA_SQL: str                                   # line 40
_CREATE_SITES_SQL: str                                    # line 89  — uq_sites_store_name at line 99
_CREATE_LOCATIONS_SQL: str                                # line 103 — inline FK lines 106-107; uq_locations_site_name line 118
_ALL_DDL: list[str]                                       # line 124 — 6 entries, last is _CREATE_LOCATIONS_SQL (line 130)
class FieldsyncSchemaManager:                             # line 134
    def __init__(self, pool: Any) -> None                 # line 154
    async def initialize(self) -> None                    # line 158 — `async with self._pool.acquire() as conn: for sql in _ALL_DDL: await conn.execute(sql)`
    @staticmethod
    def ddl_statements() -> list[str]                     # line 178 — `return list(_ALL_DDL)`

# services/venue_service.py
class DuplicateVenueError(Exception):  def __init__(self, kind: str, name: str)      # line 50
class SiteNotFoundError(Exception):    def __init__(self, site_id: int)              # line 64
class LocationNotFoundError(Exception): def __init__(self, location_id: int)         # line 76
class Site(BaseModel)       # line 93  — extra="forbid"; site_id:int, store_id:str, client_id:int, org_id:int, name:str, is_active:bool=True, tenant:str|None=None
class Location(BaseModel)   # line 121 — + location_type:str="kiosk", latitude:float|None, longitude:float|None, geofence_radius_m:int|None
_INSERT_SITE_SQL: str       # line 162 — INSERT … VALUES ($1, $2, $3, $4) RETURNING site_id, store_id, client_id, org_id, name, is_active
_SELECT_SITE_SQL: str       # line 169
_SELECT_SITES_BY_STORE_SQL: str  # line 175
_INSERT_LOCATION_SQL: str   # line 182 — INSERT … VALUES ($1..$8) RETURNING location_id, site_id, client_id, org_id, name, location_type, latitude, longitude, geofence_radius_m, is_active
_SELECT_LOCATION_SQL: str   # line 191
_SELECT_LOCATIONS_BY_SITE_SQL: str  # line 198
class VenueService:                                                   # line 211
    def __init__(self, pool: Any) -> None                             # line 226 — self._pool, self.logger
    async def create_site(self, *, store_id: str, client_id: int, org_id: int, name: str, tenant: str | None = None) -> Site   # line 234
        # body: async with self._pool.acquire() as conn: try: row = await conn.fetchrow(_INSERT_SITE_SQL, store_id, client_id, org_id, name)
        #       except Exception as exc: if is_unique_violation(exc): raise DuplicateVenueError("site", name) from exc; raise   (258-266)
    async def get_site(self, site_id: int, *, org_id: int, tenant: str | None = None) -> Site                                   # line 270
    async def list_sites(self, *, store_id: str, org_id: int, tenant: str | None = None) -> list[Site]                          # line 292
    async def create_location(self, *, site_id: int, client_id: int, org_id: int, name: str, location_type: str = "kiosk",
                              latitude: float | None = None, longitude: float | None = None,
                              geofence_radius_m: int | None = None, tenant: str | None = None) -> Location                      # line 314
        # body mirrors create_site with 8 params; DuplicateVenueError("location", name) at 361
    async def get_location(self, location_id: int, *, org_id: int, tenant: str | None = None) -> Location                      # line 366
    async def list_locations(self, *, site_id: int, org_id: int, tenant: str | None = None) -> list[Location]                   # line 389
    @staticmethod def _row_to_site(row: Any, *, tenant: str | None) -> Site            # line 411
    @staticmethod def _row_to_location(row: Any, *, tenant: str | None) -> Location    # line 424

# services/_db_utils.py
_UNIQUE_VIOLATION_CODE = "23505"                     # line 5
def is_unique_violation(exc: Exception) -> bool      # line 8 — type(exc).__name__ == "UniqueViolationError" | sqlstate/pgcode == code | "duplicate key"/"unique constraint" in str(exc).lower()

# services/org_graph.py
_SQL_GET_STORES_FOR_CLIENT: str   # line 157 — SELECT store_id, store_name, market_id FROM networkninja.stores_geographies WHERE client_id = $1 AND orgid = $2
                                  # NOTE comment lines 154-156
_SQL_GET_CLIENT_SCOPED: str       # line 179 — SELECT c.client_id, c.client_name FROM auth.clients c JOIN auth.organization_clients oc ON oc.client_id = c.client_id WHERE c.client_id = $1 AND oc.org_id = $2
class OrgGraphService:            # line 196 — __init__(pool) ; _get_pool() reads FIELDSYNC_AUTH_RO_DSN (line 232)
    async def get_node(self, node_type: NodeType, node_id: str, *, tenant: str, org_id: int) -> OrgNode   # line 474 — "client" branch 519-531 raises KeyError

# api/handlers.py
class FormAPIHandler:                                                                    # line 110
    def __init__(self, registry: FormRegistry, client=None, submission_storage=None, forwarder=None, partial_store=None,
                 org_graph_service=None, project_service=None, rbac_service=None, workday_adapter=None,
                 venue_service: "VenueService | None" = None, rbac_enforcing: bool = False, sink_factory=None) -> None   # lines 144-158
    def _get_org_id(self, request: web.Request) -> int | None                            # line 221 — request.user.organizations[0].org_id → int
    def _session_tenant(self, request: web.Request) -> str                               # line 297
    async def create_site(self, request: web.Request) -> web.Response                   # line 2682 — 501 if no service (2697); store_id = match_info (2700);
        #   body via await request.json() (2701-2704); name (2706-2708); client_id (2710-2716); org_id (2718-2720); tenant (2722);
        #   try/except: lazy `from ..services.venue_service import DuplicateVenueError` (2732) → 409 (2735); exception log (2736) → 500
    async def create_location(self, request: web.Request) -> web.Response               # line 2771 — site_id int parse (2800-2804); body (2806-2809);
        #   name (2811-2813); client_id (2815-2821); org_id (2823-2825); service call with latitude=body.get("latitude") (2831),
        #   longitude (2832), geofence_radius_m (2833); lazy import (2837) → 409 (2840); exception log (2841) → 500
    async def get_location(self, request: web.Request) -> web.Response                  # line 2846 — LocationNotFoundError → 404 pattern (2872-2876)

# api/routes.py
_wrap_auth(handler, *, tenant: str = "required")                                         # line 84
app.router.add_post(f"{bp}/org/stores/{{store_id}}/sites", _wrap_auth(handler.create_site, tenant="none"))        # 539-542
app.router.add_post(f"{bp}/org/sites/{{site_id}}/locations", _wrap_auth(handler.create_location, tenant="none"))  # 547-550
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_ALTER_VENUE_V2_SQL` | `_ALL_DDL` | list append after `_CREATE_LOCATIONS_SQL` | `services/fieldsync_schema.py:124-131` |
| `FieldsyncSchemaManager.initialize()` | `_ALL_DDL` | unchanged loop `for sql in _ALL_DDL: await conn.execute(sql)` | `services/fieldsync_schema.py:167-170` |
| `is_check_violation` / `is_foreign_key_violation` | `VenueService.create_location` except-block | predicate call next to `is_unique_violation(exc)` | `services/venue_service.py:359-362` |
| `validate_geofence` | `VenueService.create_location` | first statement, before `acquire()` | `services/venue_service.py:346` |
| `validate_geofence` | `FormAPIHandler.create_location` | called on `body.get(...)` values before the service call | `api/handlers.py:2826-2835` |
| `StoreNotFoundError` / `ClientNotInOrgError` | `FormAPIHandler.create_site` except-block | `isinstance` → 404 | `api/handlers.py:2731-2737` |
| `SiteNotFoundError` / `ClientNotInOrgError` / `VenueValidationError` | `FormAPIHandler.create_location` except-block | `isinstance` → 404 / 400 | `api/handlers.py:2836-2842` |
| `_SELECT_STORE_IN_ORG_SQL` | `networkninja.stores_geographies` | same column names as `_SQL_GET_STORES_FOR_CLIENT` | `services/org_graph.py:157-161` |
| `EXISTS (… auth.organization_clients …)` | navigator-auth table | predicate identical to `_SQL_GET_CLIENT_SCOPED`'s join condition | `services/org_graph.py:179-184` |
| `tests/unit/api/test_venue_handlers.py` | `FormAPIHandler(registry=…, venue_service=…)` | constructor kwargs | `api/handlers.py:144-158` |

### Does NOT Exist (Anti-Hallucination)
- ~~`StoreNotFoundError`~~, ~~`ClientNotInOrgError`~~, ~~`VenueValidationError`~~, ~~`GeofenceParams`~~, ~~`validate_geofence`~~ — introduced by M3.
- ~~`is_check_violation`~~, ~~`is_foreign_key_violation`~~, ~~`_CHECK_VIOLATION_CODE`~~, ~~`_FOREIGN_KEY_VIOLATION_CODE`~~ — introduced by M2; `_db_utils.py` has only `is_unique_violation` today.
- ~~`_SELECT_STORE_IN_ORG_SQL`~~, ~~`_SELECT_SITE_IN_ORG_SQL`~~ — introduced by M3.
- ~~`_ALTER_VENUE_V2_SQL`~~, ~~`_V1_VENUE_CONSTRAINTS`~~, ~~`_V2_VENUE_CONSTRAINTS`~~, ~~`_ADVISORY_LOCK_SQL`~~, ~~`_drop_constraint_if_exists`~~, ~~`_add_constraint_if_missing`~~ — introduced by M1.
- ~~`conn.transaction` double in `_make_fake_pool()`~~ (`tests/unit/test_fieldsync_schema.py:33-47`) — the fake conn only has `execute`; M1 adds the async-CM double.
- ~~`FieldsyncSchemaManager.migrate()`~~ / ~~`.upgrade()`~~ / ~~`.verify_constraints()`~~ — only `initialize()` and `ddl_statements()` exist; none are added.
- ~~`LocationCreate` / `SiteCreate` Pydantic input models~~ — the service takes keyword args; handlers read `body.get(...)`.
- ~~`fieldsync.clients`~~ — membership lives in `auth.organization_clients`.
- ~~`networkninja.stores`~~ — the table is `networkninja.stores_geographies`; its columns are what M5 verifies (the `store_id` / `client_id` / `orgid` names in this spec are the current *assumption* from `org_graph.py:157-161`).
- ~~`FormAPIHandler._get_tenant`~~ for venue routes — the survivor is `_session_tenant` (`handlers.py:297`).
- ~~`tests/unit/test_db_utils.py`~~ — no dedicated test module; M2 tests go into `test_venue_service.py`.
- ~~Any venue handler test~~ — none exist; `tests/unit/api/test_route_tenant_coverage.py:70-72` only lists the paths.
- ~~A Postgres test fixture / `FORMDESIGNER_TEST_DSN`~~ — not present (`tests/integration/conftest.py`, `tests/fixtures/persistence.py` checked); `survey_form_postgres` there is a `FormSchema`, not a database.
- ~~A wiki schema-plane page for `networkninja.stores_geographies`~~ — `wikitoolkit schema lookup` returns no candidates (checked 2026-10-08).
- ~~A call to `FieldsyncSchemaManager.initialize()` anywhere in this repo~~ — only its own docstring examples.
- ~~`ADD CONSTRAINT IF NOT EXISTS`~~ in PostgreSQL — does not exist; hence the `DO $$` guard.

### Edit Sites (Blueprint Anchors)

Verified against: `288437532` (dev, 2026-10-08). `/sdd-task` MUST re-run `grep -c` for every row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/fieldsync_schema.py` | MODIFY | `    CONSTRAINT uq_sites_store_name UNIQUE (store_id, client_id, name)` | `fieldsync_schema.py:99` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/fieldsync_schema.py` | MODIFY | `    CONSTRAINT uq_locations_site_name UNIQUE (site_id, name)` | `fieldsync_schema.py:118` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/fieldsync_schema.py` | MODIFY | `    _CREATE_LOCATIONS_SQL,` (last entry of `_ALL_DDL`, append the ALTER list after it) | `fieldsync_schema.py:130` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py` | MODIFY | `def is_unique_violation(exc: Exception) -> bool:` | `_db_utils.py:8` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `from ._db_utils import is_unique_violation` | `venue_service.py:43` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `class LocationNotFoundError(Exception):` (new exceptions go after this class) | `venue_service.py:76` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `_INSERT_SITE_SQL = """` | `venue_service.py:162` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `_INSERT_LOCATION_SQL = """` | `venue_service.py:182` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `                    raise DuplicateVenueError("site", name) from exc` | `venue_service.py:265` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py` | MODIFY | `                    raise DuplicateVenueError("location", name) from exc` | `venue_service.py:361` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/org_graph.py` | MODIFY | `# NOTE: the exact networkninja stores table/columns must be confirmed against` | `org_graph.py:154` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/org_graph.py` | MODIFY | `_SQL_GET_STORES_FOR_CLIENT = """` | `org_graph.py:157` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            self.logger.exception("create_site failed: %s", exc)` | `handlers.py:2736` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `                latitude=body.get("latitude"),` | `handlers.py:2831` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            self.logger.exception("create_location failed: %s", exc)` | `handlers.py:2841` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            from ..services.venue_service import DuplicateVenueError` — **ambiguous (2 hits)**: the `create_site` one is preceded by `        except Exception as exc:` at 2731 and followed by `if isinstance(exc, DuplicateVenueError):` + `return JSONResponse({"error": str(exc)}, status=409)` + `self.logger.exception("create_site failed: %s", exc)`; the `create_location` one (2837) is followed by `…"create_location failed: %s"…` | `handlers.py:2732`, `handlers.py:2837` | 2 |
| `packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py` | MODIFY | `    conn.execute = AsyncMock(return_value=None)` (in `_make_fake_pool`; add the `transaction` CM double after it) | `test_fieldsync_schema.py:36` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py` | MODIFY | `    def test_ddl_statements_returns_six(self) -> None:` | `test_fieldsync_schema.py:95` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py` | MODIFY | `    def test_locations_table_ddl(self) -> None:` | `test_fieldsync_schema.py:88` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | `class TestSQLSafety:` | `test_venue_service.py:122` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | `    async def test_duplicate_location_raises(self) -> None:` (new M3 tests appended after `TestLocations`) | `test_venue_service.py:251` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_venue_handlers.py` | CREATE | — | — | — |
| `docs/formdesigner/fieldsync-venue-v2.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **SQL in module constants, 100 % parameterised** (`venue_service.py:18`,
  enforced by `TestSQLSafety`). Table names never come from input; the `EXISTS`
  predicates reuse the same `$n` placeholders as the insert (no extra params).
- **Exception mapping style** of `get_location` (`handlers.py:2872-2876`): lazy
  import inside the `except`, `isinstance` chain, `JSONResponse({"error":
  str(exc)}, status=…)`. The 400 body adds `"field"`.
- **Error predicate style** of `is_unique_violation` (`_db_utils.py:8-20`):
  type name → `sqlstate`/`pgcode` → lowercase message text; never import
  asyncpg types.
- **DDL doctrine** (`fieldsync_schema.py:12-19`): every statement idempotent;
  convergence via `DROP CONSTRAINT IF EXISTS` + catalog-guarded `ADD`; new
  constraint ⇒ new name. Filter `pg_constraint` by `connamespace =
  'fieldsync'::regnamespace` so a same-named constraint in another schema
  cannot mask a missing one.
- **Dependency order inside the ALTER block**: `uq_sites_id_client_org` must
  exist before `fk_locations_site_client_org` is added (FK target must be
  unique).
- **One transaction + advisory lock** around the whole `initialize()` run
  (`pg_advisory_xact_lock`, released at commit): Postgres DDL is transactional,
  so a failing step rolls everything back and concurrent app workers serialise.
  Keep `initialize()` to `conn.transaction()` + `conn.execute()` calls — no
  `fetch`, no parameters.
- **Hard isolation**: every predicate carries `org_id`; `org_id` is only ever
  the session value (`_get_org_id`, `handlers.py:221`).
- **Fake-pool testing**: `fetchrow_side_effect=[…]` drives the two-call
  protocol; assert the second call's SQL constant by identity
  (`conn.fetchrow.await_args_list[1].args[0] is _SELECT_SITE_IN_ORG_SQL`).
- **Test-module hygiene**: copy the `_make_request` shape into the new handler
  test module; do **not** `from tests.unit.test_api_feat302 import …` (eight
  formdesigner test modules already shadow `sys.modules` at import scope —
  FEAT-617).
- Google-style docstrings, strict type hints, `self.logger`, 120 columns,
  `ruff check --fix` before commit; tests inside the worktree run with
  `PYTHONPATH=packages/parrot-formdesigner/src`.

### Known Risks / Gotchas
- **Oracle through precedence**: on a failed guard the service probes the
  *parent* first. For `create_location` the caller already supplied `site_id`
  in the URL, so learning "site not in my org" vs "client not in my org" reveals
  nothing about other orgs' data; both are 404 anyway. Never return 403 or 409
  for these.
- **Race between guard and write**: a site deleted after the `EXISTS` passes
  makes the composite FK fire (`23503`) → mapped to `SiteNotFoundError`, not a
  500.
- **CHECK violations from direct callers**: `validate_geofence()` runs first in
  `create_location`, so `23514` should be unreachable through the service; the
  mapping exists for hand-written rows and future writers.
- **Constraint names are not globally unique**: `pg_constraint.conname` can
  repeat across relations; the guard filters by `conrelid = '<table>'::regclass`
  so a same-named constraint on another table cannot mask a missing one. Do not
  reuse a v1 name for a v2 definition.
- **Invalid legacy rows** (cross-org locations, out-of-range coordinates) would
  make an `ADD CONSTRAINT` fail; the tables are empty today (brainstorm
  resolution), and with the transaction a failure leaves the v1 constraints in
  place rather than half-migrated. No preflight/remediation path is built
  (design research S2 rejected on that basis).
- **Hand-edited databases** with constraint names that match neither v1 nor
  v2 keep their extra constraints; the v2 ones are added alongside. No
  post-run constraint audit is implemented (design research S3b rejected:
  the transaction makes the outcome all-or-nothing and AC8 covers it once).
- **404 bodies stay specific** (`Site 42 not found` vs `Client 9 not found`):
  design research S7 asked for one indistinguishable body; rejected because
  the distinction only tells an authenticated caller facts about their *own*
  org (whether a site they named is theirs, whether a client is theirs) —
  never anything about another org. Cross-org probes always hit the parent
  check first and always read "Site … not found".
- **Grant prerequisite**: the venue pool's role needs `SELECT` on
  `auth.organization_clients` and `networkninja.stores_geographies`. Missing
  grant ⇒ `42501 insufficient_privilege` ⇒ 500 on every create. Documented in
  M6; probe is §8 Q1.
- **`bool` is an `int` subclass**: `validate_geofence` must reject `True`/
  `False` explicitly before numeric checks.
- **`DO $$` blocks and asyncpg**: `conn.execute()` accepts a multi-statement
  string only without parameters; each ALTER entry is a single statement with
  no `$n` placeholders — keep it that way (the `$$` quoting is not a parameter).
- **Statement count is pinned by tests** (`test_ddl_statements_returns_six`,
  `test_ddl_statements_is_copy`) — update both to 18 in M1.
- **Anchors in `handlers.py` drift** whenever another formdesigner feature
  lands first; `/sdd-task` re-greps every row.
- **Upstream spec is stale on purpose**: `Trocdigital/fieldsync` FEAT-330 v0.3
  still shows the v1 constraints; §8 Q6 decides whether it gets an errata.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncpg` | already pinned in `parrot-formdesigner` | driver; `conn.execute()` runs the `DO $$` blocks |
| `pydantic` | v2, already pinned | `GeofenceParams` |
| PostgreSQL | ≥ 9.x (server) | `DROP CONSTRAINT IF EXISTS`, composite FK, CHECK, `DO` blocks |

No new packages.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature` on `dev`.
- [x] Scope — *Resolved in brainstorm*: both HIGH findings plus all three medium items.
- [x] Have the venue tables received data anywhere? — *Resolved in brainstorm*: no, `initialize()` has not run against a shared environment; tables are empty.
- [x] Migration mechanics — *Resolved in brainstorm*: idempotent ALTER block inside `initialize()` (no separate script, no "DDL text only").
- [x] Where the `client_id` membership check lives — *Resolved in brainstorm*: service-level `WHERE EXISTS` on `auth.organization_clients`, same statement as the insert.
- [x] Composite FK `(site_id, org_id)` — *Resolved in brainstorm*: yes, add it (plus the `UNIQUE (site_id, org_id)` it requires on `sites`).
- [x] Geofence bounds — *Resolved in brainstorm*: handler returns 400 **and** the DDL adds CHECK constraints.
- [x] `networkninja.stores_geographies` columns — *Resolved in brainstorm*: a verification task inside the feature (documented catalog query, `ENV=prod`), not a brainstorm-time check.
- [x] Should `create_site` also verify `store_id` ownership? — *Resolved in brainstorm*: yes, same `EXISTS` pattern; 0 rows ⇒ 404 `StoreNotFoundError`; depends on the column-verification task.
- [x] Is `geofence_radius_m` without coordinates accepted? — *Resolved in brainstorm*: reject — radius requires coordinates (handler 400 + CHECK `geofence_radius_m IS NULL OR (latitude IS NOT NULL AND longitude IS NOT NULL)`); lat/lon both-or-neither; coordinates without radius stay allowed (`NULL ⇒ disabled`).
- [x] Does `ProjectService.create_project` get the same guard here? — *Resolved in brainstorm*: no — ledger follow-up only, feature stays scoped to #1005.
- [x] Location `client_id` must equal its site's `client_id` — *Resolved at spec time (design research S5, folded into M1/M3)*: the site predicate and the composite FK carry `client_id`; a site of another client in the same org is "not found".
- [ ] Q1. Does the DB role behind the **VenueService** pool have `SELECT` on `auth.organization_clients` and `networkninja.stores_geographies`? If not, the grant is a deployment prerequisite (documented in M6); should M6 also add a startup/readiness probe that fails before serving traffic (design research S11)? — *Owner: Jesus Lara / FieldSync ops*
- [ ] Q2. If M5 finds that `stores_geographies` uses different column names (e.g. `org_id` instead of `orgid`), M5 edits the two venue constants too; confirm this cross-module edit is acceptable rather than a separate task. — *Owner: Jesus Lara*
- [ ] Q3. Should the venue pool and the org-graph pool be the **same** pool object in the FieldSync app (one grant surface), or stay separate? Outside this repo; affects only the deployment note. — *Owner: FieldSync ops*
- [ ] Q4. Is a manual run against a disposable Postgres (v1 DDL → data → v2 `initialize()` twice, plus a concurrent-start check), with its transcript committed under `artifacts/logs/`, acceptable as AC8 evidence — or should this feature add a CI Postgres service / disposable-container fixture (design research S10)? Default assumed: manual run. — *Owner: Jesus Lara*
- [ ] Q5. Should `DuplicateVenueError`'s 409 message keep saying "already exists in its parent scope" now that the scope includes the org? (Cosmetic; no oracle either way.) — *Owner: Jesus Lara*
- [ ] Q6. Should the upstream `Trocdigital/fieldsync` FEAT-330 spec receive an errata note pointing at FEAT-640, or is the GitHub issue closure enough? — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning
> high, 89 s) · Status: completed · Transcript: `sdd/state/FEAT-640/design_research/`
> All 10 cited paths verified inside the repository and existing.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make schema convergence atomic and serialized (architecture) | CONFIRM | DDL is transactional in Postgres; a failed ADD must not leave the drops applied, and two app workers can race the catalog guard. `initialize()` now runs inside one transaction after `pg_advisory_xact_lock`. | §2 Overview ¶1, M1 skeleton, §7 Patterns, AC7 |
| S2 | Define remediation for invalid legacy rows (risk) | REJECT | Tables are empty everywhere (brainstorm resolution), so no legacy rows can block an ADD; with S1 a failure rolls back to v1 instead of half-migrating. A preflight/remediation lane is unnecessary cost. | §7 Known Risks (recorded) |
| S3a | Scope catalog checks to the target relation (architecture) | CONFIRM | `pg_constraint.conname` is per-relation, not unique; a name-only guard can be masked. Guard now filters `conrelid = '<table>'::regclass`. | §2 Overview ¶1, M1 `_add_constraint_if_missing`, AC7 |
| S3b | Verify the final constraint set after initialization (architecture) | REJECT | With S1 the run is all-or-nothing; AC8's manual evidence checks the catalog once. A runtime audit adds `fetch` calls to a method that is deliberately plain `execute`. | §7 Known Risks |
| S4 | Guard site creation against an unauthorized store (architecture) | CONFIRM | Already decided with the user before this run (brainstorm resolution); M3's `_INSERT_SITE_SQL` carries the store predicate and `StoreNotFoundError`. | M3, AC4 |
| S5 | Decide and enforce the location-to-client invariant (api) | CONFIRM | Real gap: `(site_id, org_id)` alone lets client B attach a location under client A's site in the same org. Site predicate and composite FK now include `client_id`. | §2 Overview ¶3 + Data Models, M1, M3, AC3, §8 |
| S6 | Narrow or strengthen the raw-write security claim (risk) | CONFIRM | The brainstorm's "impossible by any path" was only true for org-consistency of locations; membership/store predicates are service-level. Wording corrected and the limit stated. | §2 Overview (scope paragraph) |
| S7 | Return one indistinguishable 404 response (risk) | REJECT | The parent-first probe only reveals facts about the caller's own org (is this site mine, is this client mine); cross-org probes always read "Site … not found". No cross-tenant oracle is created by distinct bodies. | §7 Known Risks |
| S8 | Use strict JSON type validation for geofence inputs (api) | CONFIRM | `validate_geofence` already rejects bool/str/float-radius/NaN/inf; added the missing "body must be a JSON object" check (a list body is an `AttributeError` → 500 today) and the enumerated handler cases. | §2 Overview ¶4, M4, §4 tests, AC9 |
| S9 | Preserve stable graph result keys with SQL aliases (api) | CONFIRM | Verified: `_attach_store_substructure()` reads `s["store_id"]`, `s["store_name"]`, `s["market_id"]` (`org_graph.py:416-424`); a physical rename without `AS` would break the graph. M5 now mandates aliases + a key test. | M5, §4 tests |
| S10 | Add real-Postgres migration evidence (testing) | ESCALATE | No Postgres fixture exists; whether to add a CI service/container fixture versus the manual transcript is the user's call. | §8 Q4 |
| S11 | Make the membership grant a startup-checked contract (risk) | ESCALATE | Grant is documented (M6); a readiness probe touches app wiring outside this repo's control. | §8 Q1 |

Summary: **7** confirmed (S1, S3a, S4, S5, S6, S8, S9) · **3** rejected (S2, S3b, S7) · **2** escalated (S10, S11).

---

## Worktree Strategy

- **Isolation**: one feature worktree per spec —
  `.claude/worktrees/feat-FEAT-640-formdesigner-venue-tables` from
  `origin/dev` via `python -m scripts.sdd.ensure_worktree --slug
  formdesigner-venue-tables --feature-id FEAT-640`. The `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M2 (imports `is_check_violation`, `is_foreign_key_violation` from `_db_utils`).
  - M4 → M3 (imports `StoreNotFoundError`, `ClientNotInOrgError`, `VenueValidationError`, `validate_geofence`).
  - M5 → M3 (may edit `_SELECT_STORE_IN_ORG_SQL` / `_INSERT_SITE_SQL` once the columns are known).
  - M6 → M1, M3, M4, M5 (documents final names; ledger issue cites M3's pattern).
  - M1 and M2 have no inbound edges and no shared files → run concurrently; M1
    is independent of everything else in the feature.
- **Shared files**:
  - `services/venue_service.py` — M3 and (conditionally) M5 → serialised.
  - `tests/unit/test_venue_service.py` — M2 (TestDbUtils) and M3 → serialised (M2 first).
  - No other file is touched by more than one module.
- **Exclusive resources**: M5 is `parallel: false` — it needs production
  credentials (`ENV=prod`, `FIELDSYNC_AUTH_RO_DSN`) and is human/orchestrator-run;
  AC8's manual Postgres run (M1 validation evidence) is also human-run but
  does not block other modules.
- **Cross-feature dependencies**: none. The only in-flight formdesigner
  worktree (`feat-FEAT-551-msteams-formdesigner-renderer`) has no diff under
  `services/` or `api/` versus `origin/dev`. FEAT-429 (`fieldsync-tenant-url`)
  is merged; its `requires_tenant` bodies are untouched here (venue routes are
  `tenant="none"`). The upstream `Trocdigital/fieldsync` spec is read-only
  reference.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-08 | Jesus Lara + Claude | Initial draft from the accepted brainstorm (Option B); FEAT-640 reserved; codex design research folded (S1/S3a/S5/S6/S8/S9 confirmed) |
