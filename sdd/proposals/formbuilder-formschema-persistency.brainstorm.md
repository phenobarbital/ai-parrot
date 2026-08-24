---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Autonomous FormSchema Persistence ("standalone forms")

**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Persistence in `parrot-formdesigner` is **fixed at application-wiring time**, not
per form:

- **Submission data** always lands in the one generic table owned by
  `FormSubmissionStorage`, which is injected once into
  `FormAPIHandler.__init__` (`api/handlers.py:142`) and used unconditionally
  for every submission (`api/handlers.py:1616`). A form cannot say *"my
  answers go somewhere else"*.
- **Form definitions** always land in the one `form_schemas` table owned by
  `PostgresFormStorage` (`services/storage.py:69`).
- The only per-form escape hatch is `SubmitAction(action_type="endpoint")`
  plus `SubmissionForwarder` — an outbound HTTP *forward* (a side effect),
  not a persistence destination. It cannot create a table, cannot write a
  spreadsheet row, and does not replace the generic table.

There is therefore no notion of a **"formulario suelto"** (standalone,
autonomous form): a form that owns its own storage end to end. The
motivating use case is a Microsoft-Forms-style survey — the author wants the
responses to land in *their own* Postgres table, or as one row appended to a
local CSV/Excel file, or in a Google Sheet — **not** co-mingled in the
shared `form_data` JSONB table inherited from the generic Form Storage.

**Who is affected**: form authors / survey owners (want data where their
downstream tooling already looks), integrators (today must write bespoke
Python event handlers per destination), and platform operators (a single
shared submissions table is a growing multi-tenant blast radius).

**Why now**: the form abstraction layer, per-form lifecycle events
(`core/events.py`), declared metadata (`FormMetadataField`), and versioned
definitions (FEAT-433) have all landed. Persistence is the last piece of the
form that is still globally wired instead of form-declared.

## Constraints & Requirements

Decisions taken with the user during discovery (Rounds 0–3) — these are
**closed**, not open questions:

- **Scope**: BOTH the submission data *and* the form definition become
  per-form configurable.
- **Declaration site**: inside the `FormSchema` itself, as a `persistence:`
  block. It travels and versions with the form.
- **Exclusivity**: a form with its own sink writes **only** there. No
  dual-write to the generic table.
- **v1 sinks**: arbitrary Postgres table; local CSV file (append); Google
  Sheets; any other `asyncdb`-backed store (Mongo / BigQuery / Arango).
- **Credentials**: NEVER in the schema. The schema names a **connection
  alias**; the server resolves it against a config **allowlist**.
- **Read path**: **capability-declared per sink**. Postgres/asyncdb implement
  write+read+list; CSV and Sheets are write-only and the API answers `501`
  for read/list on those forms.
- **Provisioning**: **auto-create + additive auto-extend**. Create the
  table/file/sheet if absent; add columns when the form gains fields. Never
  drop, never rename.
- **Failure semantics**: if the sink is unreachable at submit time, **fail
  the submit with 5xx**. No outbox, no queue, no fallback to the generic
  table. (Accepted trade-off: a real user's answer can be lost on a sink
  outage — see Edge Cases.)
- **Mapping**: one row per submission. GROUP flattened by path; ARRAY
  serialized as JSON in one column/cell; declared metadata gets its own
  columns.
- **Definition storage**: the registry still **indexes a pointer**, so
  listing, RBAC and multi-tenancy keep working; the schema body is read from
  the form's own store.
- **`SubmitAction` forwarder is untouched** — `submit` = where data is
  *forwarded* (an effect), `persistence` = where data is *recorded*. They
  coexist; unification is explicitly out of scope.
- **CSV concurrency**: base-directory-confined path (no traversal), plain
  append, **no lock**. `.xlsx` is out of scope for v1 (see Open Questions).
- Async-first throughout; `aiohttp`-only for HTTP; Pydantic for every model;
  Google-style docstrings and strict type hints (project non-negotiables).
- Backwards compatible: `persistence: None` (the default) must behave
  **exactly** as today.

---

## Options Explored

### Option A: `persistence:` block on `FormSchema` + pluggable sink ABC (mirroring `AuthConfig` / `AbstractBlobStorage`)

Add one optional field to `FormSchema` holding a Pydantic **discriminated
union** of persistence targets, and introduce an `AbstractSubmissionSink` ABC
with one concrete backend per target. The design deliberately copies two
patterns that already exist in this package and are already proven:

1. **`AuthConfig` (`core/auth.py:145`)** — a discriminated union
   (`NoAuth | BearerAuth | ApiKeyAuth`) where each member declares a
   `type: Literal[...]` discriminator and stores only the **name of an env
   var** (`token_env`, `key_env`), never a secret, resolving it at use time
   via `_get_env()` (`core/auth.py:22`, navconfig-first with `os.environ`
   fallback). `persistence:` adopts the identical shape: the schema carries
   `connection: "<alias>"`, and the alias resolves server-side through an
   allowlist. A form author can therefore never point a form at an arbitrary
   DSN.
2. **`AbstractBlobStorage` (`services/blob_storage.py:113`)** — an ABC with
   four concrete backends (`S3BlobStorage:341`, `GCSBlobStorage:422`,
   `LocalBlobStorage:476`, `TempBlobStorage:527`) sharing an intermediate
   `_ManagerBackedBlobStorage:193`. The sink family is structured the same
   way, so the package gains no new architectural idiom.

Sinks declare **capabilities** (`WRITE` / `READ` / `LIST` / `PROVISION` /
`EXTEND`) as a frozen set; `FormAPIHandler` consults them and returns `501`
for an operation the form's sink does not support. Provisioning is an
idempotent `ensure_target()` that creates the destination and applies
**additive** column/header extension — directly modelled on the existing
`FormSubmissionStorage._alter_table_sql` (`services/submissions.py:216`),
which already does additive `ALTER TABLE` for the generic table.

The definition side is handled by a **decorator** over `FormStorage` rather
than a new registry: the wrapper stores a pointer row (identity + the
persistence block + a `source_ref`) in the existing `form_schemas` table and
resolves the schema body from the form's own store on load, so
`FormRegistry._read_through` (`services/registry.py:1035`) keeps working
unchanged and `list_forms` / RBAC / tenancy are unaffected.

✅ **Pros:**
- Declarative and portable — exporting a form carries its destination.
- Zero new architectural concepts; two in-package precedents copied verbatim.
- Credentials structurally impossible to leak into the schema (alias only).
- Capabilities make the honest answer (`501` on a write-only sink) explicit
  in the contract instead of a runtime surprise.
- `persistence: None` is a trivially safe default → no migration, no
  behavioural change for existing forms.
- Sink backends are independent modules, each individually testable with a
  fake pool / tmp dir.

❌ **Cons:**
- Largest surface of the three: new config models, new ABC, 4 backends, alias
  registry, mapper, handler branching, definition decorator.
- Touches `core/schema.py` — the hottest shared file in the package.
- Auto-provisioning means the server issues DDL against a foreign table; the
  allowlist and the additive-only rule are load-bearing security controls.
- `FormSchema` grows an infra-shaped field, which is a mild layering smell
  (mitigated: it holds aliases and coordinates, never credentials).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic>=2.0` | Discriminated union for the persistence config | already a direct dep of `parrot-formdesigner` |
| `asyncdb>=2.0` | Postgres + Mongo/BigQuery/Arango sink drivers | **already a direct dep** (`packages/parrot-formdesigner/pyproject.toml:36`) — the multi-store sink is nearly free |
| `navconfig[default]` | Alias → credential resolution | already used by `core/auth.py:39` via a guarded import; NOT a direct dep of `parrot-formdesigner` — keep the same try/except-ImportError guard |
| `csv` (stdlib) | CSV append sink | no new dependency |
| `aiofiles` *(optional)* | non-blocking CSV append | verify availability; otherwise offload the append with `asyncio.to_thread` |
| `google-api-python-client>=2.151` | Google Sheets sink | present in `ai-parrot` extras (`packages/ai-parrot/pyproject.toml:311`) but **not** in `parrot-formdesigner` → new optional extra `[gsheet]` |
| `openpyxl>=3.1` | `.xlsx` sink (deferred) | present in `ai-parrot-loaders`/`-tools`/`-server`, **not** in `parrot-formdesigner` |

🔗 **Existing Code to Reuse:**
- `core/auth.py:22` `_get_env()` — the navconfig-first / `os.environ`-fallback
  resolver. Reuse verbatim for alias → DSN resolution.
- `core/auth.py:145` `AuthConfig` — the exact discriminated-union + `resolve()`
  shape the persistence union should copy.
- `services/blob_storage.py:113` `AbstractBlobStorage` — the multi-backend ABC
  precedent (ABC + intermediate + 4 concretes) to mirror for sinks.
- `services/_identifiers.py:24` `validate_identifier()` and `:45`
  `qualified_table()` — mandatory for every identifier reaching a sink's SQL,
  since schema/table/column names cannot be parameterised.
- `services/submissions.py:216` `_alter_table_sql()` — the additive-migration
  precedent for `EXTEND`.
- `services/submissions.py:173` `_create_table_sql()` — the DDL + index
  template for the Postgres sink's `ensure_target()`.
- `services/submissions.py:50` `FormSubmission` — the record to flatten; its
  promoted columns define the sink's reserved column set.
- `services/registry.py:63` `FormStorage` ABC — the interface the definition
  decorator must implement (**note the gotcha in Code Context**).
- `packages/ai-parrot/src/parrot/eval/sink.py:35` `EvalReportSink` — an
  existing in-repo "sink ABC + Postgres impl" naming precedent.
- `packages/ai-parrot/src/parrot/stores/__init__.py:6` `supported_stores` —
  the string-keyed backend dispatch table precedent for the sink registry.

---

### Option B: Express persistence through the existing lifecycle-event hooks

Do not extend `FormSchema` at all. Persistence destinations become async
handlers registered at boot via the existing event machinery: a form binds
`FormEventsConfig.onAfterSubmit` (`core/events.py:78`) to a `handler_ref`
(`core/events.py:69`), and that handler writes wherever it likes.
`submit_data` already dispatches these hooks, and `services/event_registry.py`
/ `services/callback_registry.py` already resolve them tenant-scoped.

✅ **Pros:**
- Almost no core change — the mechanism ships today; a survey-to-own-table
  integration is writable this afternoon.
- Zero risk to existing forms; nothing on the hot path changes.
- Naturally tenant-scoped through the existing registry.
- No server-issued DDL, no alias allowlist, no new security surface.

❌ **Cons:**
- **Not declarative** — the destination is Python registered at application
  boot, so a form author using the designer UI can *never* create an
  autonomous survey. This defeats the stated Microsoft-Forms goal.
- **Cannot be exclusive**: `onAfterSubmit` fires *after* the generic store
  call (`api/handlers.py:1616`), so the data is already in the shared table.
  Achieving exclusivity requires the same handler edit this option was meant
  to avoid.
- No provisioning, no capabilities, no schema-driven column mapping — every
  integrator re-implements flattening and DDL by hand.
- Nothing travels with the form: export/import loses the destination.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| *(none)* | uses only what already ships | no new dependency |

🔗 **Existing Code to Reuse:**
- `core/events.py:78` `FormEventsConfig` — `onAfterSubmit` binding.
- `core/events.py:106` `FormEventContext` — carries `payload` for submit events.
- `services/event_registry.py`, `services/callback_registry.py` — handler
  resolution, already tenant-scoped.

---

### Option C *(unconventional)*: Compile the `FormSchema` into a generated `python-datamodel` Model and let its driver be the persistence

Rather than a sink ABC, treat the form itself as a **data model definition**.
At registration time, compile the `FormSchema` into a dynamically-generated
`datamodel.BaseModel` subclass whose `Meta` (`datasource`, `schema`, `name`)
comes from the `persistence:` block, and then let `python-datamodel` +
`asyncdb` do the insert/select/DDL. Persistence becomes a *projection* of the
form's own type rather than a separate subsystem; CSV/Sheets are handled by a
thin non-model writer.

✅ **Pros:**
- Conceptually elegant: one abstraction (the model) instead of two (schema +
  sink), and a form's table becomes a first-class, queryable model.
- Read-path, filtering and pagination come largely free wherever the driver
  supports them — the strongest read story of the three options.
- Aligns with the wider Navigator stack; `python-datamodel>=0.10.17` is
  already used by `ai-parrot` (`packages/ai-parrot/pyproject.toml:44`).
- Additive schema evolution becomes a model-diff problem, which is a
  well-understood shape.

❌ **Cons:**
- `python-datamodel` is **not** a dependency of `parrot-formdesigner` — this
  either adds a heavy new dep or couples the packages the workspace has
  deliberately kept apart.
- Dynamic class generation is hostile to `mypy` and to reasoning about
  failures; errors surface from inside a third-party ORM rather than from our
  own code.
- CSV / Google Sheets do not fit the model idiom at all, so v1's sink set
  still needs a second, parallel mechanism — the elegance is partly illusory.
- The additive-only DDL guarantee is no longer ours to enforce; we inherit
  whatever the ORM decides to do on a model change.
- Form field types (GROUP, ARRAY, localized labels) do not map cleanly onto
  model fields, so the compiler is where all the complexity moves — a large
  new component with no in-repo precedent.

📊 **Effort:** Medium–High (deceptively — the compiler absorbs the cost)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-datamodel>=0.10.17` | dynamic model generation + persistence | in `ai-parrot`, NOT in `parrot-formdesigner` |
| `asyncdb>=2.0` | drivers behind the model | already a direct dep |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/stores/__init__.py:6` `supported_stores` —
  driver dispatch precedent.
- `services/_identifiers.py:24` — still needed to validate generated
  `Meta.name` / `Meta.schema`.

---

## Recommendation

**Option A** is recommended.

Option B is the cheapest and would ship fastest, but it fails the two things
the user actually asked for. The destination must be **declared by the form**
(so a survey author — not a Python developer at boot time — decides where the
data lands, and so the destination survives export/import), and the write
must be **exclusive**. `onAfterSubmit` fires *after* the generic store call at
`api/handlers.py:1616`, so exclusivity is unreachable without editing that
call site anyway — which is precisely the change Option B claimed to avoid.
Option B is still worth keeping as the documented **escape hatch** for
destinations too exotic to model as a sink.

Option C is the most intellectually appealing and has the best read story, but
it trades a small, boring, testable subsystem for a dynamic code generator
that must bridge GROUP/ARRAY/localized form fields onto ORM fields — with no
precedent in this repo, a cross-package dependency the workspace has kept
separate on purpose, and, worst of all, the loss of *our* control over DDL.
Given the user explicitly chose **additive-only, never-drop** provisioning,
handing DDL to a third-party ORM contradicts the requirement.

Option A's real cost is honest and bounded: it is the largest diff, and it
touches `core/schema.py`. What it buys is that every hard constraint from
discovery maps onto a mechanism that already exists in this package —
`AuthConfig` gives the credential-free declarative block, `AbstractBlobStorage`
gives the multi-backend shape, `_alter_table_sql` gives additive migration,
`_identifiers.py` gives injection safety. We are assembling proven local
patterns, not inventing a subsystem.

**What we are explicitly trading away**, and why it is acceptable:
- **Durability on sink outage.** Fail-5xx (the user's choice) means a
  submission can be lost if the sink is down. Accepted for v1 because it is
  honest to the submitter, needs no queue infrastructure, and an outbox can be
  added later without changing the schema contract.
- **Read/list parity.** CSV and Sheets forms will answer `501` for
  `get_submission` / `list_revisions`. Accepted because the capability set
  makes this explicit rather than surprising.
- **A slightly impure `FormSchema`.** It gains an infra-shaped field.
  Mitigated by the alias indirection: no credentials, no DSNs, no paths
  outside the configured base directory.

---

## Feature Description

### User-Facing Behavior

A form author adds one block to the form definition:

```yaml
persistence:
  data:
    type: postgres_table
    connection: survey_db        # ALIAS, resolved server-side
    schema: surveys
    table: nps_2026
  definition:
    type: file
    connection: forms_dir
    path: nps_2026.form.yaml
```

or, for the Microsoft-Forms-style case:

```yaml
persistence:
  data:
    type: csv_file
    connection: survey_exports   # alias → an allowed base directory
    path: nps_2026.csv
```

From then on:

- Submitting the form writes **one row** into that destination, and **nowhere
  else** — nothing lands in the shared generic submissions table.
- The destination is **created on first use** if it does not exist (table,
  CSV file with a header row, or sheet with a header row).
- Adding a question to the form later **adds a column** on the next write.
  Removing a question leaves the old column in place, untouched.
- The form still appears in `GET /api/v1/forms`, still honours RBAC, still
  resolves by slug and by tenant — the registry indexes it by pointer.
- `GET .../data/{submission_id}` and revision listing work for
  Postgres/asyncdb-backed forms and answer **`501 Not Implemented`** for
  CSV/Sheets-backed forms, which are write-only by declaration.
- If the destination is unreachable at submit time, the submitter gets a
  **`503`** with a retry hint and the answer is *not* accepted.
- A form with **no** `persistence:` block behaves exactly as today.

An unknown or non-allowlisted `connection` alias is rejected at **form
registration** time (`422`), not at submit time — the author finds out
immediately, not when the first respondent does.

### Internal Behavior

**Configuration layer** (`core/persistence.py`, new)
- `FormPersistenceConfig` with `data: SubmissionTarget` and
  `definition: DefinitionTarget | None`.
- `SubmissionTarget` is a discriminated union on `type`:
  `postgres_table | csv_file | gsheet | asyncdb`, each carrying a
  `connection` alias plus its coordinates. Modelled on `AuthConfig`
  (`core/auth.py:145`); like `BearerAuth.token_env`, no member ever holds a
  secret.
- Validated at `FormSchema` construction: identifiers via
  `validate_identifier()`, column-name collisions against the reserved set,
  and (for `csv_file`) rejection of any path escaping its base directory.

**Alias resolution** (`services/sink_aliases.py`, new)
- An allowlist mapping alias → credential source, populated from config at
  startup. Resolution reuses the `_get_env()` pattern from `core/auth.py:22`
  (navconfig first, `os.environ` fallback, guarded import). Aliases are
  tenant-scoped so tenant A cannot borrow tenant B's connection.
- Unknown alias → `ValueError` surfaced as `422` by the registry.

**Sink layer** (`services/sinks/`, new)
- `AbstractSubmissionSink` ABC: `capabilities` (frozen set),
  `ensure_target()`, `write(submission, row)`, and the optional
  `read(submission_id)` / `list_revisions(...)` guarded by capability.
  Structured after `AbstractBlobStorage` (`services/blob_storage.py:113`).
- Concretes: `PostgresTableSink` (write/read/list/provision/extend, DDL
  templated on `services/submissions.py:173` + `:216`), `AsyncDBSink` (same
  contract over the other `asyncdb` drivers), `CsvFileSink`
  (write/provision only), `GoogleSheetSink` (write/provision/extend).
- A string-keyed dispatch table maps `type` → sink class, following
  `parrot/stores/__init__.py:6`.
- Sink instances are built once and cached per `(tenant, form_uid, version)`.

**Row mapping** (`services/sinks/mapper.py`, new)
- `flatten_submission(form, submission) -> dict[str, Any]`, one row per
  submission:
  - scalar field → column named after `field_id`;
  - `GROUP` → recursive path flattening, `parent__child`;
  - `ARRAY` → **one** column holding serialized JSON;
  - declared `FormMetadataField.key` values → their own columns (already
    constrained to valid Postgres identifiers by the existing validator,
    `core/schema.py:292`);
  - reserved columns always written: `submission_id`, `form_uid`, `form_id`,
    `form_version`, `created_at`, `tenant`, plus the promoted metadata
    columns from `FormSubmission` (`services/submissions.py:50`).

**Submit path** (`api/handlers.py`, modified)
- The unconditional `await self._submission_storage.store(submission)` at
  `api/handlers.py:1616` becomes a branch: when `form.persistence` is set,
  resolve the sink, `ensure_target()`, map, `write()` — and **skip** the
  generic storage entirely. Otherwise, today's behaviour verbatim.
- A `SinkUnavailableError` becomes `503`; `onError` is still dispatched
  best-effort, consistent with the existing validation/metadata error paths.
- `onAfterSubmit` continues to fire, now reporting which sink accepted the row.

**Definition path** (`services/autonomous_storage.py`, new)
- `AutonomousFormStorage(FormStorage)` decorates the configured inner storage.
  `save()` writes a **pointer row** (identity + persistence block +
  `source_ref`) through the inner storage and the schema body to the
  definition target; `load()` / `load_by_slug()` read the pointer and hydrate
  the body from the target. `FormRegistry._read_through`
  (`services/registry.py:1035`) is untouched — it keeps calling `load()` /
  `load_by_slug()` and gets a complete `FormSchema` back.

### Edge Cases & Error Handling

- **Unknown / non-allowlisted alias** → `422` at registration. Never a
  submit-time surprise.
- **Sink unreachable at submit** → `503` + `Retry-After`; submission rejected,
  nothing persisted anywhere (by explicit decision — **this is the accepted
  data-loss window**, and it must be documented in the feature's user docs,
  not just the code).
- **Target exists with an incompatible column type** (e.g. the form now sends
  text into an `integer` column) → `ensure_target()` fails loudly at
  registration/first write. We never coerce and never drop.
- **Field renamed** → treated as *new column added*; the old column stays
  and simply stops receiving values. Documented, not "fixed".
- **Reserved-name collision** — a `field_id` colliding with `submission_id`,
  `form_uid`, `created_at`, … → rejected at `FormSchema` validation.
- **CSV concurrent appends** — no lock by decision. Multiple aiohttp workers
  appending simultaneously can interleave a long row. Mitigation: one
  `write()` = one `\n`-terminated line written in a single call; the risk is
  documented and `.xlsx` (which cannot be appended safely at all) is excluded
  from v1.
- **CSV header drift** — a file whose header predates a new field: append the
  new column to the header only when creating a fresh file; on an existing
  file, extra values go to trailing columns and a warning is logged
  (`EXTEND` is *not* claimed as a CSV capability).
- **Path traversal** — `csv_file.path` is resolved against the alias's base
  directory and rejected if the resolved real path escapes it.
- **Google Sheets rate limiting / 429** → surfaces as `SinkUnavailableError`
  → `503`. No retry loop inside the request.
- **Read/list on a write-only sink** → `501` with the sink type and its
  declared capabilities in the body.
- **Partial saves** are unaffected: `PartialSaveStore`
  (`services/partial_saves.py:24`) is Redis-backed and keyed by
  `(form_id, session_id)`, independent of the submissions table. The
  `?merge_partials=true` merge happens *before* the sink write and still
  works.
- **Blob/file fields** keep using `AbstractBlobStorage`; the sink stores the
  blob **reference**, not the bytes.
- **Definition target unreachable at form open** → `_read_through` already
  fail-softs to `None` (`services/registry.py:1070`), so the form 404s rather
  than 500s. The pointer row remains, so the form reappears once the store
  recovers.
- **Tenant crossing** — alias resolution is tenant-scoped and the resolved
  schema/table is validated per call, mirroring `_resolve_schema()`
  (`services/submissions.py:159`).

---

## Capabilities

### New Capabilities
- `form-persistence-config`: the `persistence:` block on `FormSchema` — the
  discriminated union of targets, its validation rules, and the reserved
  column set.
- `form-submission-sinks`: `AbstractSubmissionSink`, its capability model, the
  dispatch table, and the four v1 backends (Postgres table, CSV file, Google
  Sheet, generic `asyncdb`).
- `form-sink-alias-registry`: tenant-scoped alias → credential allowlist and
  its resolver.
- `form-submission-row-mapper`: submission → single-row flattening (GROUP by
  path, ARRAY as JSON, metadata as columns).
- `autonomous-form-definitions`: pointer-indexed definition storage
  (`AutonomousFormStorage`) so a form's body can live in its own store while
  the registry keeps listing/RBAC/tenancy.

### Modified Capabilities
- `form-abstraction-layer` — `FormSchema` gains the `persistence` field.
- `formdesigner-lifecycle-events` — `onAfterSubmit` now reports the sink that
  accepted the row; `onError` covers `SinkUnavailableError`.
- `formregistry-multi-tenancy` — alias resolution and target coordinates must
  be tenant-scoped.
- `formbuilder-list-created-forms` — `list_forms` must keep working for
  pointer-indexed forms.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `core/schema.py` (`FormSchema:313`) | modifies | new optional `persistence` field + validation. Hottest shared file in the package. |
| `core/persistence.py` | new | discriminated union of persistence targets. |
| `core/auth.py:22` `_get_env` | depends on | reused verbatim for alias resolution. |
| `services/sinks/` | new | ABC + 4 backends + dispatch + mapper. |
| `services/sink_aliases.py` | new | tenant-scoped allowlist + resolver. |
| `services/autonomous_storage.py` | new | `FormStorage` decorator for pointer-indexed definitions. |
| `api/handlers.py:1616` | modifies | branch the unconditional generic store call. |
| `api/handlers.py:138` | modifies | accept the sink resolver / alias registry. |
| `api/routes.py:160` | modifies | wire the new service through app setup. |
| `services/submissions.py` | depends on | `FormSubmission` shape + DDL/ALTER templates reused; class itself unchanged. |
| `services/registry.py:63` `FormStorage` | depends on | the decorator must satisfy this ABC **plus** the undeclared `load_by_slug` (see Code Context). |
| `services/_identifiers.py` | depends on | every identifier reaching sink SQL. |
| `services/partial_saves.py` | unaffected | Redis-keyed, independent of the submissions table. |
| `services/blob_storage.py` | unaffected | sinks store blob refs, not bytes. |
| `services/forwarder.py` / `SubmitAction` | unaffected | forwarder coexists by decision. |
| `packages/parrot-formdesigner/pyproject.toml` | modifies | new optional extras `[gsheet]` (and later `[excel]`). |
| API contract | extends | new `501` (capability) and `503` (sink down) responses. |
| Deployment | modifies | operators must configure the alias allowlist before authors can use it. |

**Breaking changes**: none. `persistence: None` is the default and preserves
current behaviour exactly.

---

## Code Context

### User-Provided Code

The user provided no code snippets — the request was described in prose
(paraphrased): *FormSchema persistence is currently a fixed model; there is
no "standalone forms" logic where the Form or the Renderer decides the
destination model. The goal is an autonomous form with its own persistence
that does not save into the generic table inherited from Form Storage but
into its own storage — e.g. a survey whose data goes to another Postgres
table, or even a row in a local Excel file, Microsoft-Forms style.*

### Verified Codebase References

All paths below are relative to
`packages/parrot-formdesigner/src/parrot_formdesigner/` unless stated
otherwise. Every line number was read from the working tree on 2026-08-24
(branch `dev`).

#### Classes & Signatures

```python
# core/schema.py:313 — the model that gains the new field
class FormSchema(BaseModel):
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)   # line 356
    form_id: str                                              # line 357
    version: str = "1.0"                                      # line 358
    title: LocalizedString                                    # line 359
    sections: list[FormSection]                               # line 361
    submit: SubmitAction | None = None                        # line 362
    meta: dict[str, Any] | None = None                        # line 364
    created_at: datetime | None = None                        # line 365
    tenant: str | None = None                                 # line 366
    metadata: list[FormMetadataField] | None = None           # line 367
    events: FormEventsConfig | None = None                    # line 368
    form_type: FormType = FormType.SIMPLE                     # line 370
    published_version: str | None = None                      # line 372
    is_public: bool = False                                   # line 374
    # NOTE: there is NO `persistence` field today.

# core/schema.py:208 — the existing outbound-forward config (NOT persistence)
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 218
    action_ref: str                                                    # line 219
    method: str = "POST"                                               # line 220
    confirm_message: LocalizedString | None = None                     # line 221
    auth: AuthConfig | None = None                                     # line 222

# core/auth.py:145 — THE pattern to copy for the persistence union
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth
# core/auth.py:22
def _get_env(var_name: str) -> str: ...
#   navconfig-first (`from navconfig import config`, line 39),
#   falls back to os.environ (line 47), raises ValueError if absent (line 51).
# core/auth.py:77  class BearerAuth: type: Literal["bearer"]="bearer" (90);
#                  token_env: str (91); def resolve(self) -> dict[str, str]
#   → members store the NAME of an env var, never the secret.

# services/submissions.py:50 — the record a sink must flatten
class FormSubmission(BaseModel):
    submission_id: str      # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID     # required (FEAT-389/TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime     # default_factory → now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None

# services/submissions.py:118 — the CURRENT fixed submission storage
class FormSubmissionStorage:            # NOTE: a plain class, NOT an ABC
    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA,
                 table_name: str = DEFAULT_TABLE,
                 tenant: str | None = None) -> None: ...          # line 136
    def _resolve_schema(self, tenant: str | None) -> str: ...      # line 159
    def _qualified(self, tenant: str | None) -> str: ...           # line 166
    def _create_table_sql(self, tenant: str | None) -> str: ...    # line 173
    def _alter_table_sql(self, tenant: str | None) -> str: ...     # line 216 ← additive-migration precedent
    def _insert_sql(self, tenant: str | None) -> str: ...          # line 254
    async def initialize(self, *, tenant: str | None = None) -> None: ...   # line 290
    async def store(self, submission: FormSubmission, *,
                    tenant: str | None = None) -> str: ...         # line 308
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...        # line 380
    async def get_submission(...)                                  # line 418
    async def list_revisions(...)                                  # line 440

# services/registry.py:63 — the ABC an autonomous definition storage must satisfy
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *,
                   tenant: str | None = None) -> str: ...          # line 73
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...  # line 95
    @abstractmethod
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool: ...  # line 116
    @abstractmethod
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 130
    async def list_versions(self, form_uid: uuid.UUID, *,
                            tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 149 (non-abstract, returns [])
    async def promote(self, form_uid: uuid.UUID, version: str, schema_json: str, *,
                      tenant: str | None = None) -> bool: ...      # line 180 (non-abstract)
    async def close(self) -> None: ...                             # line 230 (non-abstract)

# services/storage.py:69 — the concrete definition storage
class PostgresFormStorage(FormStorage):
    def __init__(self, *, pool: Any | None = None, dsn: str | None = None,
                 schema: str = DEFAULT_SCHEMA, table_name: str = DEFAULT_TABLE,
                 tenant: str | None = None, min_size: int = 2, max_size: int = 10,
                 **pool_kwargs: Any) -> None: ...                  # line 102
    async def load(self, form_uid: uuid.UUID, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...  # line 496
    async def load_by_slug(self, ...)                              # line 555
    async def list_forms(self, ...)                                # line 642
    async def list_versions(self, ...)                             # line 703
    def _create_table_sql(self, tenant: str | None) -> str: ...    # line 159
    def _upsert_sql(self, tenant: str | None) -> str: ...          # line 178 (see the ::text::jsonb comment — codec trap)

# services/registry.py:240
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None, *,
                 app: "web.Application | None" = None,
                 default_tenant: str = "navigator",
                 require_tenant: bool = True) -> None: ...         # line 275
    async def _read_through(self, resolved: str, *, form_uid: uuid.UUID | None = None,
                            form_id: str | None = None) -> FormSchema | None: ...  # line 1035
    #   line 1073: await self._storage.load(form_uid, tenant=resolved)
    #   line 1075: await self._storage.load_by_slug(form_id, resolved)   ← see gotcha
    #   lines 1070-1082: fail-soft — storage faults are logged and return None
    @property
    def storage(self) -> "FormStorage | None": ...                 # line 1389
    def has_storage(self) -> bool: ...                             # line 1378
    def set_storage(self, storage: FormStorage) -> None: ...       # line 685

# services/blob_storage.py:113 — the multi-backend ABC shape to mirror
class AbstractBlobStorage(ABC):
    async def put(...)                    # line 125
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]  # line 152
    async def delete(self, blob_ref: str) -> None               # line 163
    async def pre_persist_hook(self, ctx: PrePersistContext) -> None  # line 170
class _ManagerBackedBlobStorage(AbstractBlobStorage): ...       # line 193
class S3BlobStorage(_ManagerBackedBlobStorage): ...             # line 341
class GCSBlobStorage(_ManagerBackedBlobStorage): ...            # line 422
class LocalBlobStorage(_ManagerBackedBlobStorage): ...          # line 476
class TempBlobStorage(_ManagerBackedBlobStorage): ...           # line 527

# services/_identifiers.py — MANDATORY for any identifier reaching sink SQL
def validate_identifier(value: str, *, kind: str = "identifier") -> str: ...  # line 24
def qualified_table(schema: str, table: str) -> str: ...                       # line 45
#   _IDENTIFIER_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"                          # line 21

# api/handlers.py:108 — the submit path to branch
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None,
                 submission_storage: "FormSubmissionStorage | None" = None,
                 forwarder=None, partial_store=None, org_graph_service=None,
                 project_service=None, rbac_service=None, workday_adapter=None,
                 venue_service=None, rbac_enforcing: bool = False) -> None: ...  # line 138
    #   line 154: self._submission_storage = submission_storage
    async def submit_data(self, request: web.Request) -> web.Response: ...      # line 1440
    #   docstring lines 1443-1454 enumerate the 8-step flow
    #   line 1568: submission = FormSubmission(...)
    #   line 1582: metadata enrichment (enrich_submission)
    #   line 1616: await self._submission_storage.store(submission)  ← THE call site to branch
    #   line 1628: forwarder branch (SubmitAction endpoint) — leave untouched

# core/events.py — lifecycle hooks (Option B's mechanism; kept as escape hatch)
FormEventName = Literal["onBeforeOpen","onSchemaLoaded","onBeforeSubmit",
                        "onAfterSubmit","onError"]     # line 32
class FormEventBinding(BaseModel): handler_ref: str (69); remote: bool (74); required: bool (75)   # line 54
class FormEventsConfig(BaseModel): onBeforeOpen/onSchemaLoaded/onBeforeSubmit/
                                   onAfterSubmit/onError  # line 78
class FormEventContext(BaseModel): ...                    # line 106

# renderers/base.py — why the RENDERER is not the decider
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...
#   Renderers are stateless per-target formatters with no storage handle.
#   Concrete renderers: adaptive_card.py, html5.py, jsonschema.py, pdf.py,
#   xforms.py, audio.py, telegram/ — a renderer×sink matrix would multiply.

# services/partial_saves.py:24 — unaffected (Redis, keyed by form_id+session_id)
class PartialSaveStore:
    def __init__(...)   # line 52
    async def save/get/delete/close   # lines 67 / 123 / 145 / 165
    def _redis_key(self, form_id: str, session_id: str) -> str   # line 178

# --- cross-package precedents (outside parrot-formdesigner) ---
# packages/ai-parrot/src/parrot/eval/sink.py:35
class EvalReportSink(ABC):
    async def persist(self, report: Any) -> str: ...   # line 44
class PostgresEvalSink(EvalReportSink): ...            # line 100
# packages/ai-parrot/src/parrot/stores/__init__.py:6 — dispatch-table precedent
supported_stores = {'postgres': 'PgVectorStore', 'milvus': 'MilvusStore',
                    'kb': 'KnowledgeBaseStore', 'faiss_store': 'FaissStore',
                    'arango': 'ArangoStore', 'bigquery': 'BigQueryStore'}
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot_formdesigner.core.schema import FormSchema, SubmitAction, FormMetadataField, FormField, FormType
from parrot_formdesigner.core.auth import AuthConfig               # core/auth.py:145
from parrot_formdesigner.core.events import FormEventsConfig, FormEventContext
from parrot_formdesigner.services.registry import FormRegistry, FormStorage, FormAlreadyExistsError
from parrot_formdesigner.services.storage import PostgresFormStorage
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot_formdesigner.services._identifiers import validate_identifier, qualified_table
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# services/__init__.py:27 re-exports FormSubmissionStorage; :40 lists it in __all__.
```

#### Key Attributes & Constants
- `DEFAULT_SCHEMA = "navigator"` / `DEFAULT_TABLE = "form_data"` → **module-level**
  constants in `services/submissions.py:31-32` (the generic submissions table).
  `services/storage.py:65-66` defines its own pair, `"navigator"` /
  `"form_schemas"` (the definitions table).
- `FormRegistry.default_tenant` defaults to `"navigator"` to match that
  constant, per its own docstring (`services/registry.py:292-293`).
- `_IDENTIFIER_RE` → `^[A-Za-z_][A-Za-z0-9_]{0,62}$` (`services/_identifiers.py:21`).
  Every sink column/table/schema name must satisfy this.
- `FormMetadataField.key` is already validated as a safe Postgres identifier
  precisely so it can be promoted to a column (`core/schema.py:267-271`) —
  the mapper can rely on that.
- `asyncdb>=2.0` is a **direct** dependency of `parrot-formdesigner`
  (`packages/parrot-formdesigner/pyproject.toml:36`).
- Existing optional extras are only `ai-parrot`, `redis`, `test`
  (`packages/parrot-formdesigner/pyproject.toml:49-61`).

### Does NOT Exist (Anti-Hallucination)
- ~~`FormSchema.persistence`~~ — **no such field today**. The union of
  existing fields is listed above (lines 356–374); `persistence` is what this
  feature adds.
- ~~`AbstractSubmissionSink`, `FormSubmissionSink`, `SubmissionSink`~~ — no
  sink abstraction exists anywhere in `parrot-formdesigner`.
  `FormSubmissionStorage` (`services/submissions.py:118`) is a **plain
  class, not an ABC** — there is no interface to implement, so the ABC must
  be created.
- ~~`FormStorage.load_by_slug`~~ — **NOT declared on the ABC**
  (`services/registry.py:63-238` declares only `save`, `load`, `delete`,
  `list_forms`, `list_versions`, `promote`, `close`) — yet
  `FormRegistry._read_through` **calls it** at `services/registry.py:1075`,
  and `register()` calls it at `:418`. Any new `FormStorage` implementation
  or decorator MUST provide `load_by_slug` even though the ABC does not
  require it, or read-through lookups will `AttributeError`.
- **ABC/impl signature divergence**: `FormStorage.load()` is declared
  `load(form_id: str, ...)` (`services/registry.py:95`) but
  `PostgresFormStorage.load()` takes `form_uid: uuid.UUID`
  (`services/storage.py:496`), and the registry calls it with a UUID
  (`services/registry.py:1073`). Do not trust the ABC docstring — follow the
  concrete/caller contract (UUID).
- ~~`openpyxl` in `parrot-formdesigner`~~ — **not a dependency**. It exists in
  `ai-parrot-loaders`, `ai-parrot-tools` (`excel` extra) and
  `ai-parrot-server`, not here. `.xlsx` support needs a new extra.
- ~~`gspread`~~ — **not present anywhere in the workspace**. Google Sheets
  would go through `google-api-python-client` (in `ai-parrot` extras, not in
  `parrot-formdesigner`) or `aiogoogle`.
- ~~`python-datamodel` in `parrot-formdesigner`~~ — not a dependency (it is a
  dependency of `ai-parrot`, `packages/ai-parrot/pyproject.toml:44`). This is
  the cost that sinks Option C.
- ~~`navconfig` as a direct dependency of `parrot-formdesigner`~~ — it is
  **not** in the dependency list; `core/auth.py:39` imports it inside a
  `try/except` and falls back to `os.environ`. Alias resolution must keep the
  same guarded pattern.
- ~~a connection/alias registry~~ — nothing like it exists in
  `parrot-formdesigner`; only the per-`AuthConfig`-member `*_env` name
  indirection.
- ~~`PostgresFormStorage` auto-creating its schema~~ — explicitly documented
  as **not** auto-created (`services/storage.py:80-82`: *"The target schema is
  assumed to exist"*). The new sinks' auto-provisioning is therefore a
  **deliberate departure** from the existing convention and must be called
  out in the spec.
- ~~`FormSubmissionStorage.DEFAULT_SCHEMA` / `PostgresFormStorage.DEFAULT_SCHEMA`~~
  as **class** attributes — they do not exist as such. Both are **module-level**
  constants (`services/submissions.py:31-32`, `services/storage.py:65-66`),
  even though the `FormRegistry.__init__` docstring
  (`services/registry.py:293`) refers to one in dotted form. Import the
  module constant, not an attribute off the class.
- ~~an outbox / retry queue~~ — no such machinery exists in the package, which
  is part of why fail-5xx was chosen for v1.

---

## Parallelism Assessment

- **Internal parallelism**: Real but shallow. The four sink backends
  (`PostgresTableSink`, `AsyncDBSink`, `CsvFileSink`, `GoogleSheetSink`) are
  genuinely independent modules once the config union, the ABC, the alias
  registry and the mapper have landed. Everything before that is a strict
  chain: `core/persistence.py` → `AbstractSubmissionSink` + capabilities →
  mapper → backends → handler branch → definition decorator.
- **Cross-feature independence**: Clean **right now** — no `sdd/tasks/index/*form*.json`
  has any `pending` task, so no formdesigner feature is in flight. The shared
  files that would conflict if one starts are `core/schema.py`,
  `services/registry.py`, `api/handlers.py`, `services/__init__.py` and
  `packages/parrot-formdesigner/pyproject.toml`. **Re-check before
  `/sdd-start`** — `core/schema.py` is the hottest file in the package.
- **Recommended isolation**: `per-spec`
- **Rationale**: Although the four sinks look parallelizable, every task
  touches at least one of a small set of shared files — the sink dispatch
  table, `services/__init__.py` exports, `pyproject.toml` extras, and the
  handler branch. Splitting them into separate worktrees would trade a modest
  wall-clock gain for guaranteed merge conflicts in exactly those files, and
  the sinks share the ABC + mapper contract that is still settling while they
  are written. One worktree, sequential tasks in dependency order, is the
  right call for v1.

---

## Open Questions

- [x] Feature or hotfix, and on which base branch? — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] Is it the submission data, the form definition, or both that become per-form configurable? — *Owner: Jesus Lara*: both — definition and data.
- [x] Where is the destination declared? — *Owner: Jesus Lara*: in the `FormSchema`, as a `persistence:` block (versioned and portable with the form).
- [x] Does the own sink replace or coexist with the generic table? — *Owner: Jesus Lara*: exclusive — the autonomous form writes only to its own sink.
- [x] Which sinks are in v1? — *Owner: Jesus Lara*: arbitrary Postgres table, local CSV/Excel file append, Google Sheets, and other `asyncdb` stores (Mongo/BigQuery/Arango).
- [x] How are destination credentials handled given the schema is authored via API? — *Owner: Jesus Lara*: server-side alias resolved against an allowlist; no DSN or secret ever enters the schema.
- [x] What happens to the common read path (`get_submission`, `list_revisions`)? — *Owner: Jesus Lara*: per-sink capabilities — Postgres/asyncdb do write+read+list, CSV/Sheets are write-only and the API answers 501.
- [x] Does the sink provision its target, and what on schema evolution? — *Owner: Jesus Lara*: auto-create plus additive auto-extend; never drop, never rename.
- [x] What are the semantics when the sink is unavailable at submit time? — *Owner: Jesus Lara*: fail the submit with 5xx; the data is not accepted. No outbox, no fallback.
- [x] Does the registry still know an autonomous form? — *Owner: Jesus Lara*: yes — the registry indexes a pointer row, so listing, RBAC and multi-tenancy keep working.
- [x] How do nested GROUP/ARRAY fields and declared metadata map to columns? — *Owner: Jesus Lara*: path-flattened GROUP (`parent__child`), ARRAY as JSON in one column, metadata as its own columns; always one row per submission.
- [x] How does this relate to the existing `SubmitAction(endpoint)` forwarder? — *Owner: Jesus Lara*: they coexist — `submit` is the forwarding effect, `persistence` is the record of truth. Unification is out of scope.
- [x] Where does the local CSV/Excel file live and how is concurrency handled? — *Owner: Jesus Lara*: a configured base directory with no path traversal; plain CSV append with no lock. `.xlsx` deferred.
- [ ] `.xlsx` support: the user's example named Excel explicitly, but v1 was scoped to lock-free CSV append because `.xlsx` cannot be appended safely (the whole workbook must be rewritten). Do we (a) ship CSV only in v1 and document `.xlsx` as a follow-up, (b) add `.xlsx` behind a single-writer/lock guarantee, or (c) offer `.xlsx` as an *export* of a CSV/Postgres sink rather than a live sink? — *Owner: Jesus Lara*
- [ ] Do the `persistence:` coordinates participate in form **versioning**? If v1.0 wrote to `nps_2026` and v1.1 changes the table, does history split across two tables, and does `promote()` (`services/storage.py:447`) need to care? — *Owner: Jesus Lara*
- [ ] Should `clone_form()` (`services/registry.py:833`) copy the `persistence:` block? Copying it means two forms silently writing into the same table; dropping it means a clone quietly reverts to the generic table. — *Owner: Jesus Lara*
- [ ] Are RBAC-privileged authors allowed to declare a `persistence:` block at all, or is authoring it gated by a permission in `services/rbac.py`? Auto-provisioning DDL is a privileged act. — *Owner: Jesus Lara*
- [ ] Does the alias allowlist live in `navconfig` (project standard), in an aiohttp app key wired at `api/routes.py:160`, or in a DB table so operators can manage aliases without a restart? — *Owner: Jesus Lara*
- [ ] For the `asyncdb` sink (Mongo/BigQuery/Arango), does "one row per submission" mean one document/row with the flattened columns, or the nested `data` object as-is? Document stores make flattening pointless. — *Owner: Jesus Lara*
