# Form Designer — Autonomous FormSchema Persistence (Standalone Forms)

> **Feature**: FEAT-457
> **Applies to**: `parrot-formdesigner` >= 0.11.0

This document is the authoritative reference for the `persistence:` block
on `FormSchema` — the mechanism that lets a form declare its own
submission-data and definition-body destinations instead of the shared,
generic storage.

---

!!! warning "Submissions are not queued"
    A form with its own `persistence:` block writes **only** to that
    destination — never to the shared submissions table (this is
    **exclusive**, not additional). If the destination is unreachable
    when someone submits, the API returns **`503`** (with a `Retry-After`
    header) and the answer is **not stored anywhere** — not in the
    destination, and not in the shared submissions table. The respondent
    must retry.

    This is a deliberate product decision: it is honest to the submitter
    and needs no queue infrastructure. **A durable outbox is a known
    follow-up, not shipped in v1.**

---

## 1. Overview

By default (`persistence: None`, or the field simply absent), a form's
submissions go to the shared `form_data` table and its definition lives
in the shared `form_schemas` table — exactly as before this feature
existed. **No breaking change**: byte-identical behaviour for every form
that does not opt in.

A form opts in by declaring a `persistence:` block, which has two
independent parts:

- **`data`** (required) — where this form's *submission answers* go.
- **`definition`** (optional) — where this form's *own schema body*
  lives, while the registry keeps a lightweight pointer so listing, RBAC
  and multi-tenancy keep working unchanged.

```yaml
persistence:
  data:
    type: postgres_table
    connection: survey_db        # ALIAS — resolved server-side, never a DSN
    schema_name: surveys         # NOT `schema` — shadows Pydantic's BaseModel.schema
    table: nps_2026
  definition:
    type: file
    connection: forms_dir        # ALIAS — resolved server-side to a base directory
    path: nps_2026.form.json
```

**No credential ever appears in a `FormSchema`.** Every target names a
connection **alias**; the server resolves it against an operator-
configured allowlist (§3). A schema JSON dump can never contain a DSN,
password, or key — every target model uses `extra="forbid"`.

---

## 2. The `persistence:` block reference

### 2.1 `data` — submission target (required)

One of four discriminated types, selected by `type`:

#### `postgres_table`

```yaml
data:
  type: postgres_table
  connection: survey_db   # str, alias -> DSN
  schema_name: surveys    # str, valid Postgres identifier
  table: nps_2026         # str, valid Postgres identifier
```

Full capability set: `write`, `read`, `list`, `provision`, `extend`.

#### `asyncdb`

```yaml
data:
  type: asyncdb
  connection: mongo_alias   # str, alias -> credentials
  driver: mongo             # "mongo" | "arango" (document) | "bigquery" (tabular)
  collection: responses     # str, valid identifier (table id for bigquery — see below)
```

Document drivers (`mongo`, `arango`) store `data` **nested**, exactly as
submitted — no flattening. The tabular driver (`bigquery`) flattens like
`postgres_table` does. **`collection` cannot contain a `.`** (it is
validated as a single Postgres-style identifier); for `bigquery`, the
tenant is used as the dataset id and `collection` is the table id.

Capabilities: `write`, `read`, `list`, `provision`, and `extend` **only**
for the `bigquery` driver (BigQuery genuinely supports additive schema
change; document drivers do not need it).

#### `csv_file`

```yaml
data:
  type: csv_file
  connection: exports      # str, alias -> an allowed base directory
  path: nps_2026.csv       # str, relative to the alias's base dir
  delimiter: ","           # optional, default ","
```

Capabilities: **`write`, `provision` only** — deliberately no `read`, no
`list`, no `extend`. See §5 for why.

#### `gsheet`

```yaml
data:
  type: gsheet
  connection: sheets_alias        # str, alias -> service-account credentials
  spreadsheet_id: "1AbC...xyz"    # str
  worksheet: "Sheet1"             # optional, default "Sheet1"
```

Capabilities: `write`, `provision`, `extend` — no `read`, no `list`
(write-only by declaration). Requires the `[gsheet]` optional extra
(§6); the package imports cleanly without it, but constructing this sink
without it raises an actionable error naming the install command.

### 2.2 `definition` — definition-body target (optional)

```yaml
definition:
  type: file
  connection: forms_dir   # str, alias -> an allowed base directory
  path: nps_2026.form.json
```

When set, the form's body (sections/fields) is written to this file
instead of the shared `form_schemas` table; the registry keeps indexing
a pointer row (identity + this `persistence:` block) so `GET
/api/v1/forms`, slug resolution, and tenant scoping all keep working
unchanged.

---

## 3. Operator setup: the alias allowlist

**Before any author can use this feature**, an operator must configure a
`SinkAliasRegistry` and pass it to `setup_form_api(..., alias_registry=...)`.
This is an explicit, deliberately **NOT runtime-mutable** security
control — no HTTP endpoint can add, change, or list an alias.

```python
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.api.routes import setup_form_api

aliases = SinkAliasRegistry()
aliases.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
aliases.register("exports", tenant="navigator", base_dir="/srv/exports")
aliases.register("sheets_alias", tenant="navigator", credentials_env="GSHEET_CREDS_JSON")

setup_form_api(app, registry, alias_registry=aliases)
```

`setup_form_api` exposes the registry under the **`app["form_sink_aliases"]`**
app key, builds a `SinkFactory` from it, injects it into the request
handler, and registers a shutdown hook that closes every cached sink.
Omitting `alias_registry` (the default) leaves the feature entirely
inactive.

| Alias kind | Registration kwarg | Env var it resolves | Used by |
|---|---|---|---|
| Database connection | `dsn_env` | Any name you choose (e.g. `SURVEY_DB_DSN`) — holds a full DSN | `postgres_table`, `asyncdb` |
| Base directory | `base_dir` | *(not env-resolved — a literal path passed at registration)* | `csv_file`, `file` (definition) |
| Opaque credentials | `credentials_env` | Any name you choose — holds a JSON blob or a path to one | `gsheet` |

Every DSN/credential is resolved through the same `_get_env()` helper
`AuthConfig` already uses (navconfig first, then `os.environ`) — never
read from `os.environ` directly, and never logged.

Registering an alias under one tenant does **not** make it resolvable
for another tenant — cross-tenant alias use raises `ValueError`.

---

## 4. Capability matrix

| Sink | write | read | list | provision | extend |
|---|:---:|:---:|:---:|:---:|:---:|
| `postgres_table` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `asyncdb` (mongo / arango) | ✅ | ✅ | ✅ | ✅ | — |
| `asyncdb` (bigquery) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `csv_file` | ✅ | — | — | ✅ | — |
| `gsheet` | ✅ | — | — | ✅ | ✅ |

An operation outside a sink's declared capabilities answers **`501 Not
Implemented`**, naming the sink type and its capabilities in the response
body — never a silent no-op and never a 500. A CSV- or Sheets-backed
form is therefore **write-only by declaration**: there is no read-back or
revision listing for it, by design (see §5).

---

## 5. Provisioning and evolution rules

- **Auto-create.** The destination (table, worksheet, or CSV file) is
  created on first use if absent. This is a deliberate departure from
  `PostgresFormStorage`'s own convention (which assumes its schema
  already exists) — bounded by the alias allowlist and the additive-only
  rule below.
- **Additive-only extension.** When a form gains a field, its sink
  extends the destination with a new column/header. **No generated
  statement ever contains `DROP` or `RENAME`.**
- **A removed field leaves its column/header alone.** It simply stops
  receiving new values; the historical data stays intact.
- **A "renamed" field is really "add a column."** The old column stays
  and stops receiving values; a new one is added for the new name. This
  is documented behaviour, not a bug.
- **CSV headers are a special case.** `csv_file` does **not** declare
  `extend`: the header row is written once, on file creation, and is
  **never** rewritten. A field added after the file exists is simply not
  reflected in the header — its values are appended as trailing columns.
  Because CSV writes are lock-free (see below), rewriting a shared header
  safely is not possible; this is the accepted trade-off.
- **Destination coordinates are immutable, forever.** Once a form's
  first submission exists, its `schema_name`/`table` (or `path`, or
  `spreadsheet_id`) can never change — only the *mapping* (which fields
  produce which columns) may evolve. Attempting to change coordinates
  raises `SinkTargetMismatchError` (mapped to **`422`**). This keeps a
  form's entire history in exactly one place forever, and means
  `promote()` needs no special handling for autonomous forms.
- **CSV concurrency.** There is **no lock**. One write emits exactly one
  `\n`-terminated line, in a single write call — concurrent workers can
  still interleave a long row under heavy load. This is a documented,
  accepted limitation, not an oversight.

---

## 6. What is NOT supported in v1

- **`.xlsx` is not a supported sink.** A `.xlsx` workbook cannot be
  appended — the entire file must be rewritten on every change, which is
  irreconcilable with the lock-free, single-write-per-submission model
  chosen for local file export. `.xlsx` support is a documented follow-up,
  not shipped in v1; **CSV is the only local-file sink.**
- **No outbox / retry queue.** See the warning at the top of this page.
- **No fallback to the shared submissions table on sink failure.** A
  form with `persistence` set never silently reroutes to the generic
  table — that would break the exclusivity guarantee this feature exists
  to provide.
- **The `[gsheet]` extra is optional.** Install it explicitly if you use
  Google Sheets as a destination:

  ```bash
  pip install 'parrot-formdesigner[gsheet]'
  ```

  Without it, the package still imports cleanly; only *constructing* a
  Google Sheets sink raises an actionable error naming this command.

---

## 7. Worked examples

### 7.1 A survey answering into its own Postgres table

```python
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

form = FormSchema(
    form_id="nps-2026",
    title="NPS Survey 2026",
    tenant="navigator",
    sections=[
        FormSection(
            section_id="s1",
            fields=[
                FormField(field_id="score", field_type=FieldType.NUMBER, label="Score"),
                FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
            ],
        )
    ],
    persistence=FormPersistenceConfig.model_validate({
        "data": {
            "type": "postgres_table",
            "connection": "survey_db",
            "schema_name": "surveys",
            "table": "nps_2026",
        }
    }),
)
```

Every submission becomes one row in `surveys.nps_2026`, with `score` and
`comment` as their own columns alongside the reserved columns
(`submission_id`, `form_uid`, `created_at`, …) — the generic
`form_data` table is never touched for this form.

### 7.2 A local export to CSV

```python
form = FormSchema(
    form_id="feedback",
    title="Quick Feedback",
    tenant="navigator",
    sections=[
        FormSection(
            section_id="s1",
            fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
        )
    ],
    persistence=FormPersistenceConfig.model_validate({
        "data": {
            "type": "csv_file",
            "connection": "exports",
            "path": "feedback.csv",
        }
    }),
)
```

The first submission creates `feedback.csv` (relative to the `exports`
alias's configured base directory) with a header row; every subsequent
submission appends exactly one line.

Both examples above were run against the implemented API
(`packages/parrot-formdesigner/tests/integration/test_autonomous_persistence.py`,
FEAT-457/TASK-2430) — every field name and target shape here matches
`core/persistence.py` exactly, not the earlier design sketch.

---

## 8. Reserved column names

The following names are reserved for every tabular sink's own columns
and **cannot** be used as a `field_id` or a declared metadata `key` when
`persistence.data` targets a tabular sink (rejected with `422` at form
construction):

```text
submission_id, form_uid, form_id, form_version, created_at, tenant,
user_id, username, org_id, submitted_at, ip, user_agent, locale,
root_submission_id, revision, context, extra_data
```

`extra_data` was added by FEAT-458 (Unknown-Field Capture) — see
[`formdesigner-unknown-fields-capture.md`](formdesigner-unknown-fields-capture.md).

Document targets (`asyncdb` with `driver: mongo` or `driver: arango`)
skip this check entirely — nesting has no column namespace to collide
with.
