<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/fieldsync_schema.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/org_graph.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/project_service.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py
packages/parrot-formdesigner/tests/fixtures/persistence.py
packages/parrot-formdesigner/tests/integration/conftest.py
packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py
packages/parrot-formdesigner/tests/unit/test_fieldsync_schema.py
packages/parrot-formdesigner/tests/unit/test_org_graph_service.py
packages/parrot-formdesigner/tests/unit/test_venue_service.py

### Questions still open in the exploration document
- [ ] Does the DB role behind the **VenueService** pool have `SELECT` on `auth.organization_clients`? (`OrgGraphService` uses `FIELDSYNC_AUTH_RO_DSN`; the venue pool is wired by the FieldSync app, not this repo.) If not, the grant is a deployment prerequisite to document in the spec. — *Owner: Jesus Lara / FieldSync ops*
- [ ] Is a manual run of `initialize()` against a disposable Postgres (v1 DDL applied first, then v2) acceptable as the validation evidence for the ALTER block, given there is no Postgres test fixture in this package? — *Owner: Jesus Lara*
- [ ] Should the upstream `Trocdigital/fieldsync` FEAT-330 spec receive an errata note pointing at this feature, or is the GitHub issue closure enough? — *Owner: Jesus Lara*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
