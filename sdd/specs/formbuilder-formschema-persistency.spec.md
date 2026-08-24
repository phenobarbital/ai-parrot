---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Autonomous FormSchema Persistence (Standalone Forms)

**Feature ID**: FEAT-457
**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.11.0

> **Prior exploration**: `sdd/proposals/formbuilder-formschema-persistency.brainstorm.md`
> (Recommended Option A). 13 questions were resolved there and 4 more during
> this spec's clarifying round; all 17 decisions are recorded in §8.

---

## 1. Motivation & Business Requirements

### Problem Statement

Persistence in `parrot-formdesigner` is **fixed at application-wiring time**,
not per form:

- **Submission data** always lands in the single generic table owned by
  `FormSubmissionStorage`, injected once into `FormAPIHandler.__init__`
  (`api/handlers.py:138`) and used unconditionally for every submission
  (`api/handlers.py:1615-1622`). A form cannot declare *"my answers go
  somewhere else"*.
- **Form definitions** always land in the single `form_schemas` table owned
  by `PostgresFormStorage` (`services/storage.py:69`).
- The only per-form escape hatch is `SubmitAction(action_type="endpoint")`
  plus `SubmissionForwarder` — an outbound HTTP *forward* (a side effect),
  not a persistence destination. It cannot create a table, cannot append a
  spreadsheet row, and does not replace the generic table.

There is therefore no notion of a **"formulario suelto"** — a standalone,
autonomous form that owns its storage end to end. The motivating use case is
a Microsoft-Forms-style survey whose responses must land in *the author's own*
Postgres table, or as one appended row in a local CSV file, or in a Google
Sheet — **not** co-mingled in the shared `form_data` JSONB table inherited
from the generic Form Storage.

**Who is affected**: form authors and survey owners (want data where their
downstream tooling already looks), integrators (today must hand-write a Python
event handler per destination), and platform operators (one shared submissions
table is a growing multi-tenant blast radius).

**Why now**: the form abstraction layer, per-form lifecycle events
(`core/events.py`), declared metadata (`FormMetadataField`) and versioned
definitions (FEAT-433) have all landed. Persistence is the last part of a form
that is still globally wired instead of form-declared.

### Goals

1. A `FormSchema` may declare its **own** persistence destination for
   submission data, in a `persistence:` block that versions and travels with
   the form.
2. A `FormSchema` may declare that its **definition body** lives in its own
   store, while the registry keeps indexing it by pointer so listing, RBAC and
   multi-tenancy continue to work.
3. Support four v1 submission sinks: **arbitrary Postgres table**, **local CSV
   file (append)**, **Google Sheets**, and **any other `asyncdb`-backed store**
   (Mongo / BigQuery / Arango).
4. A form with its own sink writes **only** there — no dual write to the
   generic table (**exclusive**).
5. **No credential ever enters a `FormSchema`.** The schema names a connection
   **alias**; the server resolves it against an allowlist.
6. Declare **per-sink capabilities** so the API answers honestly (`501`) for
   operations a sink cannot perform, instead of failing at runtime.
7. **Auto-create** the destination and **additively auto-extend** it as the
   form gains fields. Never drop, never rename.
8. **Fail the submit with 5xx** when the sink is unreachable; never silently
   reroute a submission somewhere the author did not declare.
9. **Full backwards compatibility**: `persistence: None` (the default) behaves
   exactly as today, byte for byte.

### Non-Goals (explicitly out of scope)

- **`.xlsx` as a live sink.** `.xlsx` cannot be appended — the whole workbook
  must be rewritten — which is irreconcilable with the lock-free append model
  chosen for CSV. v1 ships CSV only; `.xlsx` is a documented follow-up
  (see §8).
- **An outbox / retry queue.** Fail-5xx was chosen deliberately; durable
  queueing is a separate feature (brainstorm Option A trade-offs).
- **Unifying `SubmitAction(action_type="endpoint")` into the sink pipeline.**
  `submit` remains the forwarding *effect*; `persistence` is the *record of
  truth*. They coexist; the forwarder code is untouched.
- **Changing a form's destination coordinates after its first write.** Schema,
  table, file path and sheet id are immutable once data exists — one
  destination per form, forever (see §8, resolved).
- **Read-back / listing on write-only sinks.** CSV and Google Sheets are
  write-only by declaration; `get_submission` / `list_revisions` answer `501`.
- **Fallback to the generic table on sink failure.** Rejected in the
  brainstorm — it would break the exclusivity guarantee the feature exists to
  provide.
- **Letting the Renderer choose the destination.** Rejected in the brainstorm:
  renderers are stateless per-target formatters with no storage handle
  (`renderers/base.py`), and a renderer×sink matrix would multiply across the
  seven existing render targets.

---

## 2. Architectural Design

### Overview

Add one optional field to `FormSchema` holding a Pydantic **discriminated
union** of persistence targets, and introduce an `AbstractSubmissionSink` ABC
with one concrete backend per target. The design deliberately reuses two
patterns that already exist in this package:

1. **`AuthConfig` (`core/auth.py:145`)** — a discriminated union
   (`NoAuth | BearerAuth | ApiKeyAuth`) where each member declares a
   `type: Literal[...]` discriminator and stores only the **name of an env
   var** (`token_env`, `key_env`), resolving it at use time through `_get_env()`
   (`core/auth.py:22`, navconfig-first with `os.environ` fallback). The
   `persistence:` union adopts the identical shape: the schema carries
   `connection: "<alias>"`, resolved server-side against an allowlist. A form
   author therefore *cannot* point a form at an arbitrary DSN.
2. **`AbstractBlobStorage` (`services/blob_storage.py:113`)** — an ABC with
   four concrete backends sharing an intermediate class. The sink family is
   structured the same way, so the package gains no new architectural idiom.

**Capabilities.** Each sink exposes a frozen set drawn from
`WRITE | READ | LIST | PROVISION | EXTEND`. `FormAPIHandler` consults it and
returns `501 Not Implemented` (naming the sink type and its capabilities) for
an unsupported operation.

**Provisioning** is an idempotent `ensure_target()` that creates the
destination and applies **additive-only** column/header extension, modelled on
the existing `FormSubmissionStorage._alter_table_sql`
(`services/submissions.py:216`), which already performs additive `ALTER TABLE`
for the generic table.

> **Deliberate departure from convention**: `PostgresFormStorage` documents
> that *"The target schema is assumed to exist — it is NOT auto-created"*
> (`services/storage.py:80-82`). The new sinks **do** provision their target.
> This is an explicit product decision (§8), not an oversight, and is bounded
> by two controls: the alias allowlist (the server only ever writes to
> operator-approved connections) and the additive-only rule (no `DROP`, no
> `RENAME`, ever).

**Mapping has two modes**, selected by the sink's data family:

- **Tabular** (`postgres_table`, `csv_file`, `gsheet`): one row per
  submission. Scalar field → column named after `field_id`; `GROUP` →
  recursive path flattening `parent__child`; `ARRAY` → one column holding
  serialized JSON; declared `FormMetadataField.key` values → their own
  columns; reserved columns always written.
- **Document** (`asyncdb` against Mongo / Arango): one document per
  submission, with `data` stored **nested, unflattened**, plus the reserved
  fields. Flattening a document store loses structure for no benefit
  (§8, resolved).

**Definition storage** is handled by a **decorator** over `FormStorage` rather
than a new registry: `AutonomousFormStorage` writes a pointer row (identity +
persistence block + `source_ref`) through the inner storage and the schema
body to the definition target, and hydrates the body on load. Because it
satisfies the same interface, `FormRegistry._read_through`
(`services/registry.py:1035`) is untouched and listing / RBAC / tenancy are
unaffected.

**Destination immutability.** The destination *coordinates* (schema, table,
path, sheet id) are frozen once the first submission has been written; only
the *mapping* may evolve, additively, across form versions. This keeps a
form's history in exactly one place forever and means `promote()`
(`services/storage.py:447`) needs no changes.

### Component Diagram

```
                       FormSchema.persistence  (core/persistence.py)
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
              data: SubmissionTarget      definition: DefinitionTarget
                    │                            │
                    ▼                            ▼
        SinkFactory (services/sinks/__init__.py)  AutonomousFormStorage
                    │                             (services/autonomous_storage.py)
                    │  resolves alias                     │  wraps
                    ▼                                     ▼
        SinkAliasRegistry ──── _get_env() ──────►   PostgresFormStorage
     (services/sink_aliases.py)  (core/auth.py:22)   (services/storage.py:69)
                    │                                     ▲
                    │ builds                              │ satisfies FormStorage ABC
                    ▼                                     │  (registry.py:63 + load_by_slug)
        AbstractSubmissionSink  (services/sinks/base.py)   │
        capabilities / ensure_target / write / read / list │
                    │                                     │
      ┌─────────┬───┴─────┬──────────────┐                 │
      ▼         ▼         ▼              ▼                 │
 PostgresTable AsyncDB  CsvFile      GoogleSheet           │
   Sink        Sink      Sink           Sink               │
 W R L P E    W R L P E  W - - P -    W - - P E            │
      │         │         │              │                 │
      └────┬────┴─────────┴──────────────┘                 │
           │ rows via                                      │
           ▼                                               │
   SubmissionMapper (services/sinks/mapper.py)              │
   tabular: flatten  |  document: nested                    │
           ▲                                               │
           │ FormSubmission (services/submissions.py:50)    │
           │                                               │
  FormAPIHandler.submit_data (api/handlers.py:1440) ────────┘
     branch at api/handlers.py:1615-1622
     persistence set? → sink.write()   (generic storage SKIPPED)
     persistence None? → today's path, unchanged
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` (`core/schema.py:313`) | extends | new optional `persistence` field + construction-time validation |
| `AuthConfig` / `_get_env` (`core/auth.py:145`, `:22`) | pattern + reuse | union shape copied; `_get_env` reused verbatim for alias resolution |
| `AbstractBlobStorage` (`services/blob_storage.py:113`) | pattern | ABC + multi-backend shape mirrored by the sink family |
| `FormSubmission` (`services/submissions.py:50`) | uses | the record every sink writes; its promoted columns define the reserved set |
| `FormSubmissionStorage` (`services/submissions.py:118`) | depends on | DDL (`:173`) and additive `ALTER` (`:216`) templates reused; the class itself is **unchanged** |
| `FormAPIHandler.submit_data` (`api/handlers.py:1440`) | modifies | branch the store call at `:1615-1622`; new `503`/`501` responses |
| `FormAPIHandler.__init__` (`api/handlers.py:138`) | modifies | accept the sink factory / alias registry |
| `api/routes.py:160` | modifies | wire `SinkAliasRegistry` as an aiohttp app key |
| `FormStorage` ABC (`services/registry.py:63`) | implements | `AutonomousFormStorage` satisfies it **plus** the undeclared `load_by_slug` (§6) |
| `FormRegistry._read_through` (`services/registry.py:1035`) | unchanged | keeps calling `load()` / `load_by_slug()`; gets a complete `FormSchema` back |
| `validate_identifier` / `qualified_table` (`services/_identifiers.py:24`, `:45`) | uses | mandatory for every identifier reaching sink SQL |
| `FormEventsConfig` (`core/events.py:78`) | extends behavior | `onAfterSubmit` reports the accepting sink; `onError` covers sink failure |
| `PartialSaveStore` (`services/partial_saves.py:24`) | unaffected | Redis-keyed by `(form_id, session_id)`; the `?merge_partials=true` merge still runs *before* the sink write |
| `AbstractBlobStorage` file fields | unaffected | sinks store the blob **reference**, never the bytes |
| `SubmissionForwarder` / `SubmitAction` | unaffected | forwarder path at `api/handlers.py:1628` left verbatim |
| `services/rbac.py` | depends on | authoring a `persistence:` block is a privileged act (see §8, open) |
| `packages/parrot-formdesigner/pyproject.toml` | modifies | new optional extra `[gsheet]` |

**Breaking changes**: none. `persistence: None` is the default and preserves
current behaviour exactly.

### Data Models

Design sketches — field names and shapes are normative, bodies are not.

```python
# core/persistence.py  (NEW)

class SinkCapability(str, Enum):
    WRITE = "write"
    READ = "read"
    LIST = "list"
    PROVISION = "provision"
    EXTEND = "extend"


class PostgresTableTarget(BaseModel):
    """Arbitrary Postgres table owned by this form."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["postgres_table"] = "postgres_table"
    connection: str          # ALIAS — never a DSN. Resolved server-side.
    schema_name: str         # NOT `schema` — shadows BaseModel.schema
    table: str
    # validated with validate_identifier() at construction


class AsyncDBTarget(BaseModel):
    """Any other asyncdb-backed store (mongo / bigquery / arango)."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["asyncdb"] = "asyncdb"
    connection: str          # ALIAS
    driver: str              # e.g. "mongo" | "bigquery" | "arango"
    collection: str          # collection / dataset.table / document collection
    # Document drivers (mongo, arango) store `data` NESTED — see mapper.


class CsvFileTarget(BaseModel):
    """One appended line per submission, inside an allowlisted base dir."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["csv_file"] = "csv_file"
    connection: str          # ALIAS → an allowed base directory
    path: str                # relative to the alias's base dir; traversal rejected
    delimiter: str = ","


class GoogleSheetTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["gsheet"] = "gsheet"
    connection: str          # ALIAS → service-account credentials
    spreadsheet_id: str
    worksheet: str = "Sheet1"


SubmissionTarget = Annotated[
    PostgresTableTarget | AsyncDBTarget | CsvFileTarget | GoogleSheetTarget,
    Field(discriminator="type"),
]


class FileDefinitionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["file"] = "file"
    connection: str          # ALIAS → an allowed base directory
    path: str                # e.g. "nps_2026.form.yaml"


DefinitionTarget = Annotated[FileDefinitionTarget, Field(discriminator="type")]


class FormPersistenceConfig(BaseModel):
    """Per-form persistence declaration. Absent → today's behaviour."""
    model_config = ConfigDict(extra="forbid")
    data: SubmissionTarget
    definition: DefinitionTarget | None = None
```

```python
# core/schema.py — the ONE new field on FormSchema (after line 374)
class FormSchema(BaseModel):
    ...
    persistence: FormPersistenceConfig | None = None
```

### New Public Interfaces

```python
# services/sinks/base.py  (NEW)

class SinkError(Exception): ...
class SinkUnavailableError(SinkError):
    """Destination unreachable/rate-limited. Maps to HTTP 503."""
class SinkNotCapableError(SinkError):
    """Operation not in the sink's capability set. Maps to HTTP 501."""
class SinkTargetMismatchError(SinkError):
    """Existing target incompatible with the form. Maps to HTTP 422."""


class AbstractSubmissionSink(ABC):
    """Destination for a single form's submissions."""

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[SinkCapability]: ...

    @abstractmethod
    async def ensure_target(self, form: FormSchema) -> None:
        """Idempotently create/extend the destination. Additive only."""

    @abstractmethod
    async def write(self, submission: FormSubmission, payload: Any) -> str:
        """Persist one submission; return its submission_id."""

    async def read(self, submission_id: str) -> FormSubmission | None:
        raise SinkNotCapableError(...)          # override when READ is declared

    async def list_revisions(self, root_submission_id: str) -> list[FormSubmission]:
        raise SinkNotCapableError(...)          # override when LIST is declared

    async def close(self) -> None: ...
```

```python
# services/sink_aliases.py  (NEW)

class SinkAliasRegistry:
    """Tenant-scoped allowlist mapping alias -> credential source.

    Wired as an aiohttp app key in api/routes.py (§8, resolved).
    Resolution reuses core/auth.py:_get_env (navconfig, then os.environ).
    """
    def register(self, alias: str, *, tenant: str, dsn_env: str | None = None,
                 base_dir: str | None = None,
                 credentials_env: str | None = None) -> None: ...
    def resolve_dsn(self, alias: str, *, tenant: str) -> str: ...
    def resolve_base_dir(self, alias: str, *, tenant: str) -> Path: ...
    def is_allowed(self, alias: str, *, tenant: str) -> bool: ...


# services/sinks/__init__.py  (NEW)
SUPPORTED_SINKS: dict[str, str] = {
    "postgres_table": "PostgresTableSink",
    "asyncdb": "AsyncDBSink",
    "csv_file": "CsvFileSink",
    "gsheet": "GoogleSheetSink",
}

class SinkFactory:
    """Builds and caches sinks per (tenant, form_uid, version)."""
    async def get(self, form: FormSchema, *, tenant: str) -> AbstractSubmissionSink: ...
```

```python
# services/sinks/mapper.py  (NEW)
RESERVED_COLUMNS: frozenset[str]   # submission_id, form_uid, form_id,
                                   # form_version, created_at, tenant, user_id,
                                   # username, org_id, submitted_at, ip,
                                   # user_agent, locale, root_submission_id,
                                   # revision, context

def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]:
    """Tabular mode: one flat row. GROUP -> parent__child, ARRAY -> JSON."""

def nest_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]:
    """Document mode: reserved fields + `data` nested, unflattened."""
```

---

## 3. Module Breakdown

### Module 1: Persistence configuration models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/persistence.py`
- **Responsibility**: `SinkCapability`, the four `*Target` models, the
  `SubmissionTarget` / `DefinitionTarget` discriminated unions, and
  `FormPersistenceConfig`. Every identifier field validated via
  `validate_identifier()`; `csv_file.path` / `file.path` rejected if they
  contain traversal segments. Mirrors the `AuthConfig` shape.
- **Depends on**: `services/_identifiers.py` (existing)

### Module 2: `FormSchema.persistence` field + validation
- **Path**: `core/schema.py` (modify)
- **Responsibility**: add the optional `persistence` field; extend the
  existing `@model_validator` to reject (a) a `field_id`/metadata `key`
  colliding with `RESERVED_COLUMNS`, and (b) a flattened column name that is
  not a valid Postgres identifier, for tabular targets only.
- **Depends on**: Module 1, Module 5 (for `RESERVED_COLUMNS`)

### Module 3: Sink alias registry
- **Path**: `services/sink_aliases.py`
- **Responsibility**: tenant-scoped allowlist alias → credential source;
  `resolve_dsn` / `resolve_base_dir` / `resolve_credentials`, each delegating
  to `core/auth.py:_get_env`. Unknown or cross-tenant alias → `ValueError`.
  Base-dir resolution returns a `Path` and rejects any resolved real path that
  escapes it.
- **Depends on**: `core/auth.py:22` (existing)

### Module 4: Sink ABC, capabilities and errors
- **Path**: `services/sinks/base.py`
- **Responsibility**: `AbstractSubmissionSink`, the four error types and their
  HTTP mapping contract. Default `read` / `list_revisions` raise
  `SinkNotCapableError` so a backend opts in by overriding.
- **Depends on**: Module 1

### Module 5: Submission mapper
- **Path**: `services/sinks/mapper.py`
- **Responsibility**: `RESERVED_COLUMNS`, `flatten_submission()` (tabular:
  `GROUP` → `parent__child` recursively, `ARRAY` → one JSON column, declared
  metadata → own columns) and `nest_submission()` (document: reserved fields +
  nested `data`). Also `column_names_for(form)`, used by `ensure_target()` to
  compute the additive column set.
- **Depends on**: Module 1

### Module 6: Postgres table sink
- **Path**: `services/sinks/postgres_table.py`
- **Responsibility**: `PostgresTableSink` with capabilities
  `{WRITE, READ, LIST, PROVISION, EXTEND}`. DDL templated on
  `services/submissions.py:173`; additive extension templated on
  `services/submissions.py:216` (`ADD COLUMN IF NOT EXISTS`). Uses
  `qualified_table()` for every reference and the `$n::text::jsonb` parameter
  form documented at `services/storage.py:178` (codec trap). Raises
  `SinkTargetMismatchError` when an existing column type is incompatible.
- **Depends on**: Modules 3, 4, 5

### Module 7: AsyncDB sink (Mongo / BigQuery / Arango)
- **Path**: `services/sinks/asyncdb_store.py`
- **Responsibility**: `AsyncDBSink` over the existing `asyncdb` dependency.
  Document drivers (`mongo`, `arango`) use `nest_submission()`; tabular
  drivers (`bigquery`) use `flatten_submission()`. Capabilities are
  driver-dependent and computed per driver.
- **Depends on**: Modules 3, 4, 5

### Module 8: CSV file sink
- **Path**: `services/sinks/csv_file.py`
- **Responsibility**: `CsvFileSink` with capabilities `{WRITE, PROVISION}` —
  deliberately **not** `EXTEND` (an existing file's header is never rewritten)
  and **not** `READ`/`LIST`. Creates the file with a header row when absent;
  appends exactly one `\n`-terminated line per write, in a single write call,
  with **no lock**. Path resolved against the alias base dir; traversal
  rejected. Blocking file I/O offloaded off the event loop.
- **Depends on**: Modules 3, 4, 5

### Module 9: Google Sheets sink
- **Path**: `services/sinks/gsheet.py`
- **Responsibility**: `GoogleSheetSink` with capabilities
  `{WRITE, PROVISION, EXTEND}`. Creates the worksheet with a header row when
  absent; appends a column when the form gains a field. `429`/transport
  failures surface as `SinkUnavailableError`. Import guarded so the package
  works without the `[gsheet]` extra installed.
- **Depends on**: Modules 3, 4, 5

### Module 10: Sink dispatch and factory
- **Path**: `services/sinks/__init__.py`
- **Responsibility**: `SUPPORTED_SINKS` string-keyed dispatch table (following
  `parrot/stores/__init__.py:6`), lazy backend import, and `SinkFactory`
  caching instances per `(tenant, form_uid, version)`. Also enforces
  **destination-coordinate immutability**: a cached/persisted destination
  fingerprint that disagrees with the incoming form raises
  `SinkTargetMismatchError`.
- **Depends on**: Modules 4, 6, 7, 8, 9

### Module 11: Autonomous definition storage
- **Path**: `services/autonomous_storage.py`
- **Responsibility**: `AutonomousFormStorage(FormStorage)` decorating an inner
  storage. `save()` writes a pointer row (identity + persistence block +
  `source_ref`) via the inner storage and the schema body to the definition
  target; `load()` / **`load_by_slug()`** hydrate the body from the target.
  Must implement `load_by_slug` even though the ABC omits it (§6).
- **Depends on**: Modules 1, 3

### Module 12: Submit-path integration
- **Path**: `api/handlers.py` (modify)
- **Responsibility**: replace the unconditional block at `:1615-1622` with a
  branch — when `form.persistence` is set, resolve the sink, `ensure_target()`,
  map, `write()`, and **skip** the generic storage; otherwise today's path
  verbatim. Map `SinkUnavailableError` → `503` (+ `Retry-After`),
  `SinkNotCapableError` → `501`, `SinkTargetMismatchError` → `422`. Gate
  `get_submission` / `list_revisions` on capabilities. `onError` still
  dispatched best-effort, consistent with the existing validation and metadata
  error paths.
- **Depends on**: Modules 10, 5

### Module 13: Application wiring
- **Path**: `api/routes.py` (modify), `services/__init__.py` (modify)
- **Responsibility**: construct `SinkAliasRegistry` from configuration and
  register it as an **aiohttp app key** (§8, resolved); pass the `SinkFactory`
  into `FormAPIHandler`; export the new public names.
- **Depends on**: Modules 3, 10

### Module 14: Packaging and documentation
- **Path**: `packages/parrot-formdesigner/pyproject.toml`, `docs/`
- **Responsibility**: add the `[gsheet]` optional extra; document the
  `persistence:` block, the alias allowlist an operator must configure, the
  capability matrix, and — prominently — the **accepted data-loss window** on
  sink outage (fail-5xx means a respondent's answer is rejected, not queued).
- **Depends on**: Modules 1, 9, 12

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_persistence_union_discriminates` | 1 | each `type` literal resolves to the right target model |
| `test_target_rejects_raw_dsn_field` | 1 | `extra="forbid"` blocks a `dsn`/`password` key sneaking in |
| `test_target_validates_identifiers` | 1 | invalid schema/table rejected via `validate_identifier` |
| `test_csv_path_traversal_rejected` | 1 | `../../etc/passwd` rejected at construction |
| `test_formschema_accepts_persistence` | 2 | round-trips through `model_dump_json` |
| `test_formschema_persistence_none_is_default` | 2 | absent field → `None`, no behaviour change |
| `test_reserved_column_collision_rejected` | 2 | a `field_id` named `submission_id` fails validation |
| `test_alias_unknown_raises` | 3 | unregistered alias → `ValueError` |
| `test_alias_is_tenant_scoped` | 3 | tenant A cannot resolve tenant B's alias |
| `test_alias_resolves_via_get_env` | 3 | monkeypatched env resolved through `_get_env` |
| `test_base_dir_escape_rejected` | 3 | resolved real path outside the base dir → `ValueError` |
| `test_default_read_raises_not_capable` | 4 | ABC default raises `SinkNotCapableError` |
| `test_flatten_group_path` | 5 | nested `GROUP` → `parent__child` |
| `test_flatten_array_as_json` | 5 | `ARRAY` → one column with serialized JSON |
| `test_flatten_promotes_metadata` | 5 | declared `FormMetadataField.key` → own column |
| `test_nest_keeps_data_nested` | 5 | document mode preserves nesting |
| `test_reserved_columns_always_present` | 5 | every reserved key emitted |
| `test_postgres_sink_create_table_sql` | 6 | DDL shape + quoted identifiers |
| `test_postgres_sink_additive_alter_only` | 6 | generated SQL contains no `DROP`/`RENAME` |
| `test_postgres_sink_type_mismatch_raises` | 6 | incompatible existing column → `SinkTargetMismatchError` |
| `test_asyncdb_sink_document_driver_nests` | 7 | mongo/arango use `nest_submission` |
| `test_asyncdb_sink_tabular_driver_flattens` | 7 | bigquery uses `flatten_submission` |
| `test_csv_sink_creates_header` | 8 | fresh file gets a header row |
| `test_csv_sink_appends_single_line` | 8 | one write == one `\n`-terminated line |
| `test_csv_sink_no_extend_capability` | 8 | `EXTEND` absent; existing header never rewritten |
| `test_csv_sink_read_raises_501_contract` | 8 | `SinkNotCapableError` on `read` |
| `test_gsheet_sink_rate_limit_maps_unavailable` | 9 | simulated `429` → `SinkUnavailableError` |
| `test_gsheet_import_guarded` | 9 | absent extra → clean error, package still imports |
| `test_factory_dispatch_table` | 10 | every `SUPPORTED_SINKS` key builds |
| `test_factory_caches_per_form_version` | 10 | same `(tenant, form_uid, version)` → same instance |
| `test_coordinate_change_rejected` | 10 | changed schema/table/path → `SinkTargetMismatchError` |
| `test_autonomous_storage_implements_load_by_slug` | 11 | the ABC-omitted method exists and works |
| `test_autonomous_storage_pointer_roundtrip` | 11 | pointer row + body → identical `FormSchema` |

### Integration Tests

| Test | Description |
|---|---|
| `test_submit_to_own_postgres_table` | full `POST /data` → row in the form's own table, **nothing** in the generic table |
| `test_submit_skips_generic_storage` | generic `FormSubmissionStorage` is never called when `persistence` is set (exclusivity) |
| `test_submit_without_persistence_unchanged` | regression: `persistence: None` behaves byte-for-byte as today |
| `test_submit_to_csv_appends_row` | `tmp_path` base dir; two submissions → header + 2 lines |
| `test_sink_down_returns_503` | unreachable sink → `503`, no row anywhere, `onError` dispatched |
| `test_read_on_csv_form_returns_501` | `GET .../data/{id}` on a CSV-backed form → `501` naming the capabilities |
| `test_read_on_postgres_form_returns_200` | same call on a Postgres-backed form → the submission |
| `test_new_field_adds_column` | add a field, re-submit → new column present, old rows untouched |
| `test_removed_field_leaves_column` | remove a field, re-submit → old column retained, no `DROP` issued |
| `test_merge_partials_then_sink_write` | `?merge_partials=true` merges from Redis **before** the sink write |
| `test_autonomous_form_still_listed` | pointer-indexed form appears in `GET /api/v1/forms` and resolves by slug |
| `test_unknown_alias_rejected_at_registration` | `POST /forms` with a bad alias → `422`, not a submit-time failure |
| `test_forwarder_still_runs_with_persistence` | `SubmitAction(endpoint)` forward happens **and** the sink write happens |

### Test Data / Fixtures

```python
# packages/parrot-formdesigner/tests/fixtures/persistence.py
@pytest.fixture
def alias_registry(tmp_path, monkeypatch):
    """SinkAliasRegistry with one DSN alias and one base-dir alias."""

@pytest.fixture
def survey_form_postgres():
    """FormSchema with PostgresTableTarget + a GROUP and an ARRAY field."""

@pytest.fixture
def survey_form_csv(tmp_path):
    """FormSchema with CsvFileTarget pointing inside tmp_path."""

@pytest.fixture
def fake_pool():
    """asyncpg-pool double recording executed SQL (see existing tests)."""
```

Reuse the existing suite's conventions:
`tests/test_registry_read_through.py` (read-through doubles),
`tests/test_submission_jsonb_shape.py` (JSONB/codec assertions),
`tests/test_submit_merge.py` (partial-merge submit path).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`)
- [ ] All integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/ -v`)
- [ ] Full package suite green (`pytest packages/parrot-formdesigner/tests/ -v`)
- [ ] `ruff check packages/parrot-formdesigner/` clean
- [ ] `mypy` clean on all new modules
- [ ] Documentation updated in `docs/` — including the `persistence:` block
      reference, the operator's alias-allowlist setup, the capability matrix,
      and the accepted data-loss window on sink outage
- [ ] **No breaking changes**: a `FormSchema` without `persistence` produces
      byte-identical behaviour to `dev` (proved by `test_submit_without_persistence_unchanged`)
- [ ] **Both layers configurable**: submission data *and* definition body can
      each be redirected per form
- [ ] **Declared in the schema**: the destination is a `FormSchema` field that
      survives `model_dump_json` → `model_validate` round-trip
- [ ] **Exclusive**: when `persistence` is set the generic `FormSubmissionStorage`
      is never invoked (asserted, not merely observed)
- [ ] **Four v1 sinks** implemented and tested: Postgres table, CSV file,
      Google Sheets, `asyncdb` store
- [ ] **No credential in the schema**: no target model accepts a DSN, password
      or key; `extra="forbid"` on every target; a schema JSON dump contains no
      secret
- [ ] **Alias allowlist enforced**: an unregistered or cross-tenant alias is
      rejected at form registration with `422`
- [ ] **Capabilities honoured**: `read`/`list` on a CSV- or Sheets-backed form
      returns `501` naming the sink type and its capabilities
- [ ] **Provisioning**: destination auto-created when absent; a new form field
      adds a column/header on the next write
- [ ] **Additive only**: no generated statement contains `DROP` or `RENAME`;
      a removed field leaves its column intact
- [ ] **Coordinates immutable**: changing schema/table/path/sheet after the
      first write is rejected with `422`
- [ ] **Fail-5xx**: an unreachable sink yields `503` and persists nothing
      anywhere — no fallback to the generic table, no queue
- [ ] **Mapping**: `GROUP` flattens to `parent__child`, `ARRAY` serializes to
      one JSON column, declared metadata gets its own columns, one row per
      submission — and document drivers store `data` nested instead
- [ ] **Registry unaffected**: a pointer-indexed autonomous form is listed by
      `GET /api/v1/forms`, resolves by slug, and honours tenant scoping
- [ ] **`load_by_slug` implemented** on `AutonomousFormStorage` (the ABC omits
      it but `FormRegistry` calls it — §6)
- [ ] **Forwarder untouched**: `SubmitAction(action_type="endpoint")`
      forwarding still runs alongside a sink write; no diff in `forwarder.py`
- [ ] **CSV safety**: path traversal rejected; one write emits exactly one
      `\n`-terminated line in a single call
- [ ] **Path traversal**: no alias can resolve outside its configured base dir
- [ ] `.xlsx` is **not** shipped and is recorded as a follow-up (Non-Goal)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was re-verified against the working tree on
> **2026-08-24** at `dev` = `79582147c`. `git diff` confirms
> `packages/parrot-formdesigner/` is **unchanged** between the brainstorm's
> verification point (`ece8bf580`) and this commit, so the brainstorm's
> Code Context carries forward intact — **with one correction noted below**.
>
> All paths are relative to
> `packages/parrot-formdesigner/src/parrot_formdesigner/` unless stated.

> ⚠️ **Correction to the brainstorm**: it cited the generic-store call site as
> `api/handlers.py:1616`. That line is the `if` guard; the actual
> `store(submission)` call is at **`:1617`**, and the full block to replace is
> **`:1615-1622`**. Use the numbers in this spec.

### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot_formdesigner.core.schema import (
    FormSchema, SubmitAction, FormMetadataField, FormField, FormType,
    FormSection, FormSubsection, RenderedForm,
)
from parrot_formdesigner.core.auth import AuthConfig, NoAuth, BearerAuth, ApiKeyAuth
from parrot_formdesigner.core.events import FormEventsConfig, FormEventContext
from parrot_formdesigner.services.registry import (
    FormRegistry, FormStorage, FormAlreadyExistsError,
)
from parrot_formdesigner.services.storage import PostgresFormStorage
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot_formdesigner.services._identifiers import validate_identifier, qualified_table
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage
from parrot_formdesigner.renderers.base import AbstractFormRenderer
# services/__init__.py:27 re-exports FormSubmissionStorage; :40 lists it in __all__.
# core/auth.py:22 `_get_env` is module-private — import it explicitly and
# deliberately (it is the project-standard resolver), or lift it to a shared
# helper as part of Module 3.
```

### Existing Class Signatures

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
    # ← `persistence` is added AFTER line 374. It does not exist today.

# core/schema.py:208 — existing outbound-forward config (NOT persistence)
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 218
    action_ref: str                                                    # line 219
    method: str = "POST"                                               # line 220
    confirm_message: LocalizedString | None = None                     # line 221
    auth: AuthConfig | None = None                                     # line 222

# core/schema.py:257 — declared metadata; `key` is ALREADY validated as a safe
# Postgres identifier precisely so it can be promoted to a column (docstring
# lines 267-271). The mapper may rely on that.
class FormMetadataField(BaseModel):
    key: str                     # line 292
    source: MetadataSource       # line 293
    label: LocalizedString | None = None      # line 294
    callback_ref: str | None = None           # line 295
    default: Any = None                       # line 296
    required: bool = False                    # line 297
    options: dict[str, Any] | None = None     # line 298

# core/auth.py — THE pattern to copy for the persistence union
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth          # line 145
def _get_env(var_name: str) -> str: ...                # line 22
#   navconfig first (`from navconfig import config`, line 39);
#   falls back to os.environ (line 47); raises ValueError if absent (line 51).
class BearerAuth(BaseModel):                           # line 77
    type: Literal["bearer"] = "bearer"                 # line 90
    token_env: str                                     # line 91
    def resolve(self) -> dict[str, str]: ...
#   → members store the NAME of an env var, never the secret. Copy this.

# services/submissions.py:50 — the record every sink writes
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory → datetime.now(timezone.utc)
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

# services/submissions.py:118 — the CURRENT fixed submission storage.
# NOTE: a PLAIN class, NOT an ABC. There is no existing interface to implement.
class FormSubmissionStorage:
    def __init__(self, pool: Any, *, schema: str = DEFAULT_SCHEMA,
                 table_name: str = DEFAULT_TABLE,
                 tenant: str | None = None) -> None: ...        # line 136
    def _resolve_schema(self, tenant: str | None) -> str: ...    # line 159
    def _qualified(self, tenant: str | None) -> str: ...         # line 166
    def _create_table_sql(self, tenant: str | None) -> str: ...  # line 173  ← DDL template
    def _alter_table_sql(self, tenant: str | None) -> str: ...   # line 216  ← ADDITIVE-migration precedent
    def _insert_sql(self, tenant: str | None) -> str: ...        # line 254
    async def initialize(self, *, tenant: str | None = None) -> None: ...  # line 290
    async def store(self, submission: FormSubmission, *,
                    tenant: str | None = None) -> str: ...       # line 308
    @staticmethod
    def _row_to_submission(row: Any) -> FormSubmission: ...      # line 380
    async def get_submission(...)                                # line 418
    async def list_revisions(...)                                # line 440

# services/registry.py:63 — the ABC AutonomousFormStorage must satisfy
class FormStorage(ABC):
    @abstractmethod
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *,
                   tenant: str | None = None) -> str: ...                     # line 73
    @abstractmethod
    async def load(self, form_id: str, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...       # line 95
    @abstractmethod
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool: ...  # line 116
    @abstractmethod
    async def list_forms(self, *, tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 130
    async def list_versions(self, form_uid: uuid.UUID, *,
                            tenant: str | None = None) -> list[dict[str, Any]]: ...  # line 149 (non-abstract, returns [])
    async def promote(self, form_uid: uuid.UUID, version: str, schema_json: str, *,
                      tenant: str | None = None) -> bool: ...                 # line 180 (non-abstract)
    async def close(self) -> None: ...                                        # line 230 (non-abstract)

# services/storage.py:69 — the concrete definition storage to decorate
class PostgresFormStorage(FormStorage):
    def __init__(self, *, pool: Any | None = None, dsn: str | None = None,
                 schema: str = DEFAULT_SCHEMA, table_name: str = DEFAULT_TABLE,
                 tenant: str | None = None, min_size: int = 2, max_size: int = 10,
                 **pool_kwargs: Any) -> None: ...                # line 102
    def _create_table_sql(self, tenant: str | None) -> str: ...   # line 159
    def _upsert_sql(self, tenant: str | None) -> str: ...         # line 178  ← read the ::text::jsonb comment
    def _promote_sql(self, tenant: str | None) -> str: ...        # line 201
    async def save(...)                                           # line 395
    async def promote(...)                                        # line 447
    async def load(self, form_uid: uuid.UUID, version: str | None = None, *,
                   tenant: str | None = None) -> FormSchema | None: ...  # line 496
    async def load_by_slug(...)                                   # line 555
    async def delete(...)                                         # line 615
    async def list_forms(...)                                     # line 642
    async def list_versions(...)                                  # line 703
    # docstring lines 80-82: "The target schema is assumed to exist — it is
    # NOT auto-created." The new sinks deliberately depart from this.

# services/registry.py:240
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None, *,
                 app: "web.Application | None" = None,
                 default_tenant: str = "navigator",
                 require_tenant: bool = True) -> None: ...        # line 275
    async def register(...)                                       # line 466
    def set_storage(self, storage: FormStorage) -> None: ...       # line 685
    async def unregister(...)                                     # line 770
    async def clone_form(...)                                     # line 833
    async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None  # line 976
    async def get_by_slug(...)                                    # line 1004
    async def _read_through(self, resolved: str, *, form_uid: uuid.UUID | None = None,
                            form_id: str | None = None) -> FormSchema | None: ...  # line 1035
    #   line 1073: await self._storage.load(form_uid, tenant=resolved)
    #   line 1075: await self._storage.load_by_slug(form_id, resolved)   ← see "Does NOT Exist"
    #   lines 1070-1082: fail-soft — storage faults are logged and return None
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]  # line 1102
    async def load_from_storage(self, *, tenant: str | None = None) -> int        # line 1320
    def has_storage(self) -> bool                                  # line 1378
    @property
    def storage(self) -> "FormStorage | None"                      # line 1389

# services/blob_storage.py:113 — the multi-backend ABC shape to mirror
class AbstractBlobStorage(ABC):
    async def put(...)                                             # line 125
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]     # line 152
    async def delete(self, blob_ref: str) -> None                  # line 163
    async def pre_persist_hook(self, ctx: PrePersistContext) -> None  # line 170
class _ManagerBackedBlobStorage(AbstractBlobStorage): ...          # line 193
class S3BlobStorage(_ManagerBackedBlobStorage): ...                # line 341
class GCSBlobStorage(_ManagerBackedBlobStorage): ...               # line 422
class LocalBlobStorage(_ManagerBackedBlobStorage): ...             # line 476
class TempBlobStorage(_ManagerBackedBlobStorage): ...              # line 527

# services/_identifiers.py — MANDATORY for any identifier reaching sink SQL
def validate_identifier(value: str, *, kind: str = "identifier") -> str: ...  # line 24
def qualified_table(schema: str, table: str) -> str: ...                      # line 45
_IDENTIFIER_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"                             # line 21

# api/handlers.py:108 — the submit path to branch
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None,
                 submission_storage: "FormSubmissionStorage | None" = None,
                 forwarder=None, partial_store=None, org_graph_service=None,
                 project_service=None, rbac_service=None, workday_adapter=None,
                 venue_service=None, rbac_enforcing: bool = False) -> None: ...  # line 138
    #   line 154: self._submission_storage = submission_storage
    async def submit_data(self, request: web.Request) -> web.Response: ...       # line 1440
    #   docstring lines 1443-1454: the documented 8-step flow (update it)
    #   line 1568: submission = FormSubmission(...)
    #   line 1582: metadata enrichment via enrich_submission
    #   line 1615: "# Store locally (if storage configured)"
    #   line 1616:     if self._submission_storage is not None:
    #   line 1617:         await self._submission_storage.store(submission)   ← THE call
    #   lines 1618-1622: else + debug log
    #   line 1624: "# Forward to endpoint ..."
    #   line 1628: if form.submit is not None and form.submit.action_type == "endpoint" ...
    #   line 1629:     await self._forwarder.forward(result.sanitized_data, form.submit)
    #   → REPLACE 1615-1622. LEAVE 1624-1631 untouched.
    async def delete_form(...)   # storage.delete at line 1433

# core/events.py — lifecycle hooks (kept as the escape hatch for exotic sinks)
FormEventName = Literal["onBeforeOpen","onSchemaLoaded","onBeforeSubmit",
                        "onAfterSubmit","onError"]                # line 32
class FormEventBinding(BaseModel):                                # line 54
    handler_ref: str   # line 69 — pattern requires at least one dot
    remote: bool = False    # line 74
    required: bool = False  # line 75
class FormEventsConfig(BaseModel): ...                            # line 78
class FormEventContext(BaseModel): ...                            # line 106

# renderers/base.py — why the RENDERER is not the decider
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...
# Stateless per-target formatters with no storage handle. Concrete renderers:
# adaptive_card.py, html5.py, jsonschema.py, pdf.py, xforms.py, audio.py,
# telegram/ — a renderer×sink matrix would multiply across all seven.

# services/partial_saves.py:24 — UNAFFECTED (Redis, keyed by form_id+session_id)
class PartialSaveStore:
    def __init__(...)                                # line 52
    async def save(...) / get(...) / delete(...) / close(...)   # 67 / 123 / 145 / 165
    def _redis_key(self, form_id: str, session_id: str) -> str  # line 178

# --- cross-package precedents (outside parrot-formdesigner) ---
# packages/ai-parrot/src/parrot/eval/sink.py:35 — "sink ABC + Postgres impl" naming precedent
class EvalReportSink(ABC):
    async def persist(self, report: Any) -> str: ...   # line 44
class PostgresEvalSink(EvalReportSink): ...            # line 100
# packages/ai-parrot/src/parrot/stores/__init__.py:6 — dispatch-table precedent
supported_stores = {'postgres': 'PgVectorStore', 'milvus': 'MilvusStore',
                    'kb': 'KnowledgeBaseStore', 'faiss_store': 'FaissStore',
                    'arango': 'ArangoStore', 'bigquery': 'BigQueryStore'}
```

### Key Attributes & Constants

- `DEFAULT_SCHEMA = "navigator"` / `DEFAULT_TABLE = "form_data"` →
  **module-level** constants in `services/submissions.py:31-32`.
- `DEFAULT_SCHEMA = "navigator"` / `DEFAULT_TABLE = "form_schemas"` →
  **module-level** constants in `services/storage.py:65-66`.
- `FormRegistry.default_tenant` defaults to `"navigator"` to match those
  constants, per its own docstring (`services/registry.py:292-293`).
- `_IDENTIFIER_RE` → `^[A-Za-z_][A-Za-z0-9_]{0,62}$` (`services/_identifiers.py:21`).
  Every sink column/table/schema name must satisfy it.
- `asyncdb>=2.0` is a **direct** dependency of `parrot-formdesigner`
  (`packages/parrot-formdesigner/pyproject.toml:36`) — the `asyncdb` sink adds
  no new dependency.
- Existing optional extras are only `ai-parrot`, `redis`, `test`
  (`packages/parrot-formdesigner/pyproject.toml:49-61`).
- Current package version: `0.10.0`
  (`packages/parrot-formdesigner/src/parrot_formdesigner/version.py`).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormPersistenceConfig` | `FormSchema` | new optional field after `is_public` | `core/schema.py:374` |
| `*Target.connection` | `SinkAliasRegistry` | alias lookup | `services/sink_aliases.py` (new) |
| `SinkAliasRegistry` | `_get_env()` | function call | `core/auth.py:22` |
| `PostgresTableSink.ensure_target` | DDL template | pattern copy | `services/submissions.py:173` |
| `PostgresTableSink.ensure_target` | additive `ALTER` | pattern copy | `services/submissions.py:216` |
| every sink's SQL | `qualified_table()` | function call | `services/_identifiers.py:45` |
| `SubmissionMapper` | `FormSubmission` | attribute read | `services/submissions.py:50` |
| `SubmissionMapper` | `FormMetadataField.key` | attribute read (pre-validated identifier) | `core/schema.py:292` |
| `SinkFactory` | `FormAPIHandler.submit_data` | replaces the store call | `api/handlers.py:1615-1622` |
| `SinkUnavailableError` | `web.Response(status=503)` | exception mapping | `api/handlers.py:1440` |
| `AutonomousFormStorage` | `FormStorage` ABC | subclass | `services/registry.py:63` |
| `AutonomousFormStorage.load_by_slug` | `FormRegistry._read_through` | method call | `services/registry.py:1075` |
| `SinkAliasRegistry` | aiohttp app key | app setup | `api/routes.py:160` |

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.persistence`~~ — **no such field today**. The complete current
  field set is listed above (lines 356-374); this feature adds it.
- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ — no
  sink abstraction exists anywhere in `parrot-formdesigner`.
  `FormSubmissionStorage` (`services/submissions.py:118`) is a **plain class,
  not an ABC** — there is no interface to implement, so the ABC must be
  created from scratch.
- ~~`FormStorage.load_by_slug`~~ — **NOT declared on the ABC**
  (`services/registry.py:63-238` declares only `save`, `load`, `delete`,
  `list_forms`, `list_versions`, `promote`, `close`) — yet `FormRegistry`
  **calls it** at `services/registry.py:418` and `:1075`. Any new
  `FormStorage` implementation or decorator MUST provide `load_by_slug` or
  read-through lookups will raise `AttributeError`.
- **ABC/impl signature divergence**: `FormStorage.load()` is declared
  `load(form_id: str, ...)` (`services/registry.py:95`) but
  `PostgresFormStorage.load()` takes `form_uid: uuid.UUID`
  (`services/storage.py:496`), and the registry calls it with a UUID
  (`services/registry.py:1073`). Follow the concrete/caller contract (UUID),
  not the ABC docstring.
- ~~`FormSubmissionStorage.DEFAULT_SCHEMA` / `PostgresFormStorage.DEFAULT_SCHEMA`~~
  as **class** attributes — they do not exist as such. Both are module-level
  constants (`services/submissions.py:31-32`, `services/storage.py:65-66`),
  even though the `FormRegistry.__init__` docstring
  (`services/registry.py:293`) refers to one in dotted form. Import the
  module constant, never an attribute off the class.
- ~~`openpyxl` in `parrot-formdesigner`~~ — **not a dependency**. It exists in
  `ai-parrot-loaders`, `ai-parrot-tools` (`excel` extra) and
  `ai-parrot-server`. `.xlsx` is a Non-Goal for v1 anyway.
- ~~`gspread`~~ — **not present anywhere in the workspace**. Google Sheets must
  go through `google-api-python-client` (in `ai-parrot` extras, not here) or
  `aiogoogle`, added as a new `[gsheet]` extra.
- ~~`python-datamodel` in `parrot-formdesigner`~~ — not a dependency (it belongs
  to `ai-parrot`, `packages/ai-parrot/pyproject.toml:44`). Do not reach for
  dynamic model generation.
- ~~`navconfig` as a direct dependency of `parrot-formdesigner`~~ — **not** in
  its dependency list; `core/auth.py:39` imports it inside `try/except` and
  falls back to `os.environ`. Alias resolution MUST keep the same guarded
  pattern.
- ~~a connection/alias registry~~ — nothing like it exists in
  `parrot-formdesigner` today; only the per-`AuthConfig`-member `*_env` name
  indirection.
- ~~an outbox / retry queue~~ — no such machinery exists in the package. This
  is part of why fail-5xx was chosen.
- ~~`FormSchema.schema` as a usable field name~~ — `schema` collides with
  Pydantic's `BaseModel.schema`. The Postgres target field is therefore named
  `schema_name`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Copy `AuthConfig`** (`core/auth.py:145`) for the target union: a
  `type: Literal[...]` discriminator per member, `extra="forbid"`, and only
  *names* of credential sources — never a secret, never a DSN.
- **Copy `AbstractBlobStorage`** (`services/blob_storage.py:113`) for the sink
  family shape: ABC with defaults that raise, concrete backends per target.
- **Copy the additive `ALTER`** from `services/submissions.py:216`. Generated
  SQL must never contain `DROP` or `RENAME` — assert this in a test.
- **Every** schema/table/column name goes through `validate_identifier()`
  before interpolation (`services/_identifiers.py:24`). Identifiers cannot be
  parameterised; this is the injection boundary.
- Use the **`$n::text::jsonb`** parameter form, never `$n::jsonb` — a
  host-provided pool may register a json codec and double-encode the value.
  The full explanation is in the comment at `services/storage.py:178`.
- String-keyed **dispatch table** with lazy import, following
  `parrot/stores/__init__.py:6`.
- Async-first: no blocking I/O on the event loop. CSV writes and any
  Google client call must be offloaded (`asyncio.to_thread`) or use an async
  client. Never `requests`/`httpx` — `aiohttp` only.
- Pydantic v2 models for all structured data; Google-style docstrings and
  strict type hints on every new function and class; `self.logger`, never
  `print`.
- Follow the existing test conventions in
  `packages/parrot-formdesigner/tests/` — see
  `test_registry_read_through.py`, `test_submission_jsonb_shape.py`,
  `test_submit_merge.py`.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **Accepted data-loss window.** Fail-5xx means a real respondent's answer is rejected when the sink is down, with nothing persisted anywhere. | Explicit product decision (§8). Must be documented in user-facing docs, not just code. `503` + `Retry-After` so clients can retry. An outbox is the natural follow-up. |
| **Server-issued DDL against a foreign database** — a new privilege for this service. | Bounded by two controls: the alias allowlist (only operator-approved connections) and the additive-only rule. Both are load-bearing; test them explicitly. |
| **Alias allowlist is a security control.** | Wired as an aiohttp app key at `api/routes.py:160`, not runtime-mutable. Unknown/cross-tenant alias → `422` at registration. |
| **Path traversal** via `csv_file.path` / `file.path`. | Resolve against the alias base dir and reject any resolved real path that escapes it. Test with `../../etc/passwd`. |
| **CSV interleaving.** No lock, so concurrent workers can interleave a long row. | One write = one `\n`-terminated line emitted in a single call. Documented limitation; `.xlsx` (unappendable) excluded entirely. |
| **CSV header drift.** An existing file's header predates a new field. | `CsvFileSink` deliberately does **not** declare `EXTEND`. Header written only on file creation; later extra values go to trailing columns with a logged warning. |
| **`load_by_slug` is not on the ABC** but `FormRegistry` calls it. | Implement it on `AutonomousFormStorage`; assert its presence in a test (`test_autonomous_storage_implements_load_by_slug`). |
| **`core/schema.py` is the hottest shared file** in the package. | Keep the change to one field plus validator extensions. Re-check for in-flight formdesigner work before `/sdd-start`. |
| **Reserved-column collision** — a `field_id` named `submission_id`. | Rejected at `FormSchema` validation, so the author learns at authoring time. |
| **Incompatible existing column type** (form now sends text into an `integer`). | `ensure_target()` raises `SinkTargetMismatchError` → `422`. Never coerce, never drop. |
| **Field rename** looks like an add. | Treated as *new column added*; the old column stays and stops receiving values. Documented, not "fixed". |
| **Google Sheets rate limits (429).** | Surface as `SinkUnavailableError` → `503`. No retry loop inside the request path. |
| **`[gsheet]` extra absent at runtime.** | Guard the import; the package must still import and the sink must fail with a clear, actionable error. |
| **Definition target unreachable at form open.** | `_read_through` already fail-softs to `None` (`services/registry.py:1070-1082`), so the form 404s rather than 500s. The pointer row survives, so the form reappears when the store recovers. |
| **Tenant crossing.** | Alias resolution is tenant-scoped; schema/table validated per call, mirroring `_resolve_schema` (`services/submissions.py:159`). |
| **Blob/file fields.** | Keep using `AbstractBlobStorage`; the sink stores the blob **reference**, never bytes. |
| **Pydantic name shadowing.** | `schema` shadows `BaseModel.schema` → the field is `schema_name`. |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | discriminated union for the persistence config — **already a direct dep** |
| `asyncdb` | `>=2.0` | Postgres + Mongo/BigQuery/Arango sinks — **already a direct dep** (`pyproject.toml:36`) |
| `google-api-python-client` | `>=2.151` | Google Sheets sink — **NEW**, behind a `[gsheet]` optional extra |
| `csv` | stdlib | CSV sink — no new dependency |
| `navconfig` | *(guarded import)* | alias → credential resolution; NOT a direct dep — keep the `try/except ImportError` guard from `core/auth.py:39` |
| `openpyxl` | — | **NOT added.** `.xlsx` is a Non-Goal for v1. |

---

## 8. Open Questions

### Resolved in brainstorm (carried forward)

- [x] Feature or hotfix, and on which base branch? — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Is it the submission data, the form definition, or both that become per-form configurable? — *Resolved in brainstorm*: both — definition and data. (§1 Goals 1-2, §3 Modules 1/11)
- [x] Where is the destination declared? — *Resolved in brainstorm*: in the `FormSchema`, as a `persistence:` block, versioned and portable with the form. (§2 Data Models, §3 Module 2)
- [x] Does the own sink replace or coexist with the generic table? — *Resolved in brainstorm*: exclusive — the autonomous form writes only to its own sink. (§1 Goal 4, §3 Module 12, AC "Exclusive")
- [x] Which sinks are in v1? — *Resolved in brainstorm*: arbitrary Postgres table, local CSV/Excel file append, Google Sheets, and other `asyncdb` stores. (§3 Modules 6-9; Excel narrowed to CSV below)
- [x] How are destination credentials handled given the schema is authored via API? — *Resolved in brainstorm*: server-side alias resolved against an allowlist; no DSN or secret ever enters the schema. (§3 Module 3, AC "No credential in the schema")
- [x] What happens to the common read path (`get_submission`, `list_revisions`)? — *Resolved in brainstorm*: per-sink capabilities — Postgres/asyncdb do write+read+list, CSV/Sheets are write-only and the API answers 501. (§2 Overview, §3 Module 12)
- [x] Does the sink provision its target, and what on schema evolution? — *Resolved in brainstorm*: auto-create plus additive auto-extend; never drop, never rename. (§1 Goal 7, AC "Additive only")
- [x] What are the semantics when the sink is unavailable at submit time? — *Resolved in brainstorm*: fail the submit with 5xx; the data is not accepted. No outbox, no fallback. (§1 Goal 8, §7 Known Risks row 1)
- [x] Does the registry still know an autonomous form? — *Resolved in brainstorm*: yes — the registry indexes a pointer row, so listing, RBAC and multi-tenancy keep working. (§3 Module 11, AC "Registry unaffected")
- [x] How do nested GROUP/ARRAY fields and declared metadata map to columns? — *Resolved in brainstorm*: path-flattened GROUP (`parent__child`), ARRAY as JSON in one column, metadata as its own columns; one row per submission. (§3 Module 5)
- [x] How does this relate to the existing `SubmitAction(endpoint)` forwarder? — *Resolved in brainstorm*: they coexist — `submit` is the forwarding effect, `persistence` is the record of truth. Unification is out of scope. (§1 Non-Goals, AC "Forwarder untouched")
- [x] Where does the local CSV/Excel file live and how is concurrency handled? — *Resolved in brainstorm*: a configured base directory with no path traversal; plain CSV append with no lock. `.xlsx` deferred. (§3 Module 8, §7 Known Risks)

### Resolved during this spec's clarifying round

- [x] `.xlsx` support in v1? — *Resolved 2026-08-24*: **CSV only in v1; `.xlsx` is a documented follow-up.** `.xlsx` cannot be appended (the whole workbook must be rewritten), which is irreconcilable with the lock-free append model. (§1 Non-Goals, §3 Module 8, AC final item)
- [x] Does the `persistence:` block participate in form versioning? — *Resolved 2026-08-24*: **mutable but additive only** — the destination *coordinates* (schema/table/path/sheet) are immutable once the first submission is written; only the *mapping* may evolve additively across versions. One destination per form, forever. `promote()` therefore needs no changes. (§2 Overview, §3 Module 10, AC "Coordinates immutable")
- [x] Where does the alias allowlist live? — *Resolved 2026-08-24*: an **aiohttp app key wired in `api/routes.py`** — explicitly injected at app construction, testable without touching the environment, and not runtime-mutable (it is a security control). (§3 Modules 3/13, §7 Known Risks)
- [x] For the `asyncdb` sink on document stores, what does "one row per submission" mean? — *Resolved 2026-08-24*: **nested document, no flattening.** Mongo/Arango store `data` as-is plus the reserved fields; flattening would lose structure for no benefit. Tabular drivers (BigQuery) still flatten. (§2 Overview, §3 Modules 5/7)

### Still open

- [x] Should `clone_form()` (`services/registry.py:833`) copy the `persistence:` block? Copying it means two forms silently writing into the same destination; dropping it means a clone quietly reverts to the generic table. **Proposed default for implementation: DROP the block on clone and require an explicit re-declaration**, because a silent shared destination is the more damaging failure. Confirm before Module 11 lands. — *Owner: Jesus Lara*: drop the block on clone.
- [x] Is authoring a `persistence:` block gated by an RBAC permission (`services/rbac.py`)? Auto-provisioning DDL against a foreign database is a privileged act. **Proposed default for implementation: a new permission checked in shadow mode**, consistent with the existing `rbac_enforcing: bool = False` convention (`api/handlers.py:138`), so it logs before it blocks. Confirm before Module 12 lands. — *Owner: Jesus Lara*: accepted the proposed change

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: The four sink backends (Modules 6-9) look parallelizable, and
  in principle they are — but every one of them touches a small set of shared
  files: the `services/sinks/__init__.py` dispatch table, `services/__init__.py`
  exports, `pyproject.toml` extras, and the shared ABC + mapper contract that
  is still settling while they are written. Splitting them into separate
  worktrees would trade a modest wall-clock gain for guaranteed merge conflicts
  in exactly those files. One worktree, sequential tasks in dependency order,
  is the right call for v1.
- **Dependency order**: 1 → (3, 4) → 5 → 2 → (6, 7, 8, 9) → 10 → 11 → 12 → 13 → 14.
- **Cross-feature dependencies**: none blocking. At the time of writing, no
  `sdd/tasks/index/*form*.json` has a `pending` task, so no formdesigner
  feature is in flight. The shared files that would conflict if one starts are
  `core/schema.py`, `services/registry.py`, `api/handlers.py`,
  `services/__init__.py` and `packages/parrot-formdesigner/pyproject.toml`.
  **Re-check immediately before `/sdd-start`** — `core/schema.py` is the
  hottest file in this package.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus Lara | Initial draft from `formbuilder-formschema-persistency.brainstorm.md` (Option A); 13 brainstorm decisions carried forward, 4 resolved in the clarifying round, 2 left open with proposed defaults. Corrected the brainstorm's `api/handlers.py:1616` reference to `:1617` (block `:1615-1622`). |
