---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: CommCenter — Bulk Notification Sender over NotifyWorker

**Feature ID**: FEAT-417
**Date**: 2026-08-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.26.0

**Brainstorm**: `sdd/proposals/commcenter-notify.brainstorm.md` (Option B — Partial-Render Gateway)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot can host agents and REST surfaces, but it has **no way to send a
templated communication blast** (email / Teams / Zoom / SMS) to a list of
people. The two halves of that capability exist but are not connected:

- **`async-notify`** (installed as `async-notify 1.5.5`) knows how to talk to
  every provider (SMTP, Gmail, O365, Teams, Zoom, Twilio, Telegram, Slack,
  SES, …) and how to render Jinja2 templates.
- **Qworker** runs a **`NotifyWorker`** process
  (`qw/process.py:10` → `from notify.server import NotifyWorker`) that consumes
  a Redis Stream and dispatches those notifications asynchronously — so the
  sending work is already distributed and out-of-process.

What is missing is the **front door**: an HTTP surface where an operator (or
the Navigator UI) can drop a recipient list — typed inline as JSON, or
uploaded as an Excel/CSV — pick a Jinja2 template and a provider, and have one
personalized message published per recipient into the NotifyWorker stream.

Three concrete gaps:

1. **No sender endpoint.** Nothing in `parrot.handlers` publishes to the
   NotifyWorker stream. Every blast today is a hand-written script.
2. **No template store.** Jinja2 templates only exist as files under
   `TEMPLATE_DIR`. A non-developer cannot author, version or edit one; there is
   no CRUD and no database table.
3. **No placeholder discovery.** A person writing a template has no way to
   learn which variables are available (`{{name}}`, `{{email}}`, …) or which
   computed functions exist (`{{today}}`). They guess, and the blast renders
   with holes.

**Who is affected**: operations / marketing staff who send the blasts, the
Navigator frontend team who need a documented API to build the composer UI, and
the developers who currently absorb every "can you send this out" request as
manual work.

### Goals

- **G1** — Ship `CommCenterHandler(BaseHandler)`, *instantiable*, registering
  three endpoint groups via a `setup(app)` method.
- **G2** — `POST /api/v1/comm_center/sender` accepts recipients through **three
  transports**: inline JSON list, `multipart/form-data` file upload, and a
  base64-embedded file. Excel/CSV columns `name | username | email | phone` are
  the Jinja2 placeholders.
- **G3** — Resolve the message body from a stored template, an inline Jinja2
  string, or a `TEMPLATE_DIR` filename; **partial-render** it once per batch so
  computed functions (`{{today}}`) are substituted while per-recipient
  placeholders survive literally for the worker's second pass.
- **G4** — Publish **one `xadd` per recipient** to the NotifyWorker stream via
  `NotifyClient.stream()`, carrying no credentials.
- **G5** — Provider selectable globally with a per-record column override;
  rows missing the contact field their provider needs are **skipped with a
  reason and reported**, never silently dropped, and never aborting the batch.
- **G6** — Return `202 Accepted` with a `batch_id` immediately; fan out in a
  background task; expose progress at `GET /sender/{batch_id}`.
- **G7** — Full CRUD at `/api/v1/comm_center/templates` over a new
  `navigator.notification_templates` table, with `updated_at` maintained by a
  `BEFORE UPDATE` trigger.
- **G8** — GET-only placeholder catalog (static, in-module) listing recipient
  fields and computed functions with live sample values **and the documented
  template-language limitation**.
- **G9** — All three endpoints require `@is_authenticated`; templates are
  global with `created_by` / `updated_by` audit columns.
- **G10** — Hard cap on recipients per batch (10 000); `POST
  /sender/{batch_id}/retry` to re-publish rows orphaned by a restart.
- **G11** — `async-notify` stays an optional dependency: a new
  `ai-parrot-server[comm-center]` extra plus **lazy imports** with an
  actionable error when absent.
- **G12** — Factor the sending core as a `CommCenterService` the handler calls,
  so a future toolkit can reuse it without a rewrite.

### Non-Goals (explicitly out of scope)

- **Delivery confirmation.** `NotifyWorker.check_stream()` `xack`s and logs but
  publishes **no result stream** (`notify/server/server.py:269-280`). Tracking
  tops out at `queued` / `skipped` / `publish_failed`. The API must not promise
  what it cannot observe.
- **Per-user rate limiting / quotas.** Considered and deferred; only the
  per-batch recipient cap (G10) ships in v1.
- **Exposing bulk send as an agent tool.** Rejected in brainstorm — see
  `sdd/proposals/commcenter-notify.brainstorm.md` Option C. Handing an LLM an
  unguarded mass-send tool imports a prompt-injection blast radius needing its
  own approval-gating spec. G12 keeps the door open.
- **Worker-side rendering of computed functions.** Rejected in brainstorm —
  see Option A. Functions resolve handler-side so a bad template fails before
  anything is published.
- **Modifying `qworker` / `NotifyWorker`.** Consumed exactly as-is.
- **Executing the DDL.** Both `.sql` files are authored, not run — applying
  them is an operator/deployment step, per repo convention
  (`users_prompts_creation.sql`, `users_bots_creation.sql`).
- **Template versioning / history.** One row per template; `updated_at` only.
- **Scheduling / recurring blasts.**

---

## 2. Architectural Design

### Overview

`CommCenterHandler` is a **partial-render gateway**. It owns a Jinja2
`Environment(undefined=DebugUndefined)`, loads the template body, and renders
it **once per batch** with only the computed-function context bound. Because
the environment uses `DebugUndefined`, every placeholder it cannot resolve is
re-emitted literally:

```
"Hola {{ name }}, hoy es {{ today }}"  →  "Hola {{ name }}, hoy es 2026-08-06"
```

*(verified executing in `.venv` — see §6.)*

That partially-rendered string travels in `template=` to the worker, where
Notify performs the second pass and substitutes the per-recipient fields.

The design's core trade is **failing fast**: a malformed Jinja2 template raises
during the single batch-level render and returns `400` *before* a single
message is published, instead of producing N silent worker failures the
operator cannot see.

**Two-pass render contract:**

| Pass | Where | Resolves | Preserves |
|---|---|---|---|
| 1 | `CommCenterService`, once per batch | computed functions (`today`, `now`, …) | `{{name}}`, `{{email}}`, `{{username}}`, `{{phone}}`, … |
| 2 | `NotifyWorker` → `AbstractProvider._render_`, once per recipient | recipient fields from the row kwargs | — |

Both passes run with **autoescape disabled** — pass 2 is fixed by
`notify.templates.jinja_config`, which sets only `enable_async` and
`extensions` (`notify/templates.py:7-10`), so Jinja2's default
`autoescape=False` applies. Pass 1 matches it deliberately; enabling autoescape
in pass 1 would HTML-escape the preserved `{{ }}` braces and corrupt the
template. **Consequence** — recipient values are interpolated into HTML
unescaped; see §7 Known Risks.

### Component Diagram

```
                    HTTP (aiohttp, @is_authenticated)
                              │
                    ┌─────────▼──────────┐
                    │ CommCenterHandler  │  (navigator.views.BaseHandler)
                    │  setup(app)        │
                    └─────────┬──────────┘
          ┌───────────────────┼───────────────────┬──────────────────┐
          │                   │                   │                  │
   POST /sender        /templates CRUD     GET /placeholders   GET /sender/{id}
   POST /sender/{id}/retry                                     (progress)
          │                   │                   │                  │
          ▼                   ▼                   ▼                  ▼
 ┌──────────────────┐  ┌──────────────┐  ┌────────────────┐  ┌──────────────┐
 │ CommCenterService│  │NotificationT-│  │  PLACEHOLDERS  │  │ tracking     │
 │  ingest          │  │emplate Model │  │  (static dict) │  │ aggregation  │
 │  partial_render  │  │ (asyncdb pg) │  └────────────────┘  └──────────────┘
 │  validate        │  └──────┬───────┘
 │  fan_out         │         │
 └────────┬─────────┘         ▼
          │            navigator.notification_templates
          │                  (trigger → updated_at)
          │
          ├─── writes ──→ navigator.notification_batch_recipients  (flat, 1 row/recipient)
          │
          ▼
   NotifyClient.stream(msg, NOTIFY_WORKER_STREAM)   ← one xadd per recipient
          │
          ▼  Redis Stream "NotifyWorkerStream"
   ┌──────────────────────────────────────────┐
   │ NotifyWorker (qworker — UNCHANGED)       │
   │  check_stream → NotifyWrapper → Notify   │
   │  → pass-2 render → provider dispatch     │
   │  credentials from ITS OWN environment    │
   └──────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseHandler` | extends | `CommCenterHandler`; uses `handle_upload`, `get_json`, `json_response`, `error`, `get_userid`, `query_parameters` |
| `notify.server.NotifyClient` | uses | `stream(message, stream, use_wrapper=False)` — the publish path. **Lazy import** |
| `notify.conf` | reads | `NOTIFY_WORKER_STREAM`, `NOTIFY_REDIS` |
| `NotifyWorker` (qworker) | depends on | Consumed as-is. **No changes** |
| `asyncdb.AsyncDB` / `asyncdb.models.Model` | uses | `pg` driver; `Meta(driver="pg", schema=PARROT_SCHEMA)` |
| `parrot.outputs.a2ui.recipes.params` | uses | `resolve_date()` + `DATE_RESOLVERS` — the computed-function engine. **Do not write a new one** |
| `parrot.bots.dynamic_values` | mirrors | Registry *pattern* for the catalog. Note: different names (`current_date` vs `today`) — see §6 |
| `navigator_auth.decorators.is_authenticated` | uses | On all endpoints |
| `parrot.conf.PARROT_SCHEMA` | reads | `"navigator"` |
| `packages/ai-parrot-server/pyproject.toml` | modifies | New `comm-center` extra + add to `all` aggregator |
| App route wiring | modifies | Instantiate handler, call `.setup(app)` — mirrors `ScrapingInfoHandler` |
| Redis (`NOTIFY_REDIS`) | depends on | **Deployment change**: web process needs write access to the NotifyWorker stream |

### Data Models

```python
# Request/response models — datamodel BaseModel (repo convention)

class RecipientIn(BaseModel):
    """One row from JSON / Excel / CSV. Extra columns are preserved
    and forwarded as render kwargs."""
    name: str
    username: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    provider: Optional[str]          # per-record override (G5)
    extra: dict                      # any additional columns

class SenderRequest(BaseModel):
    provider: str                    # global default
    template_id: Optional[uuid.UUID] # stored template  ─┐
    template_name: Optional[str]     # stored template   ├─ exactly one
    template: Optional[str]          # inline Jinja2 str │
    template_file: Optional[str]     # TEMPLATE_DIR file ─┘
    subject: Optional[str]
    recipients: Optional[list[RecipientIn]]
    file_b64: Optional[str]
    filename: Optional[str]
    dry_run: bool = False            # validate + render, publish NOTHING (Q3)

class SkippedRow(BaseModel):
    row: int
    reason: str

class SenderResponse(BaseModel):
    batch_id: Optional[uuid.UUID]    # None when dry_run=True (no batch persisted)
    status: str                      # publishing | completed | failed | dry_run
    total: int
    queued: int
    skipped: int
    resolved_functions: dict         # {"today": "2026-08-06"} — auditable
    skipped_details: list[SkippedRow]
    preview: Optional[str]           # dry_run only: first queued row, both passes
```

```python
# Persistence — asyncdb Model, mirrors models/users_prompts.py

class NotificationTemplate(Model):
    template_id: uuid.UUID = Field(primary_key=True, required=False,
                                   default_factory=uuid.uuid4)
    name: str = Field(required=True)          # UNIQUE
    template_string: str = Field(required=True)
    subject: Optional[str]
    provider: Optional[str]                   # default provider
    description: Optional[str]
    tags: list = Field(required=False, default_factory=list)
    is_active: bool = Field(required=False, default=True)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int]
    updated_at: datetime = Field(required=False, default=datetime.now)
    updated_by: Optional[int]

    class Meta:
        driver = "pg"
        name = "notification_templates"
        schema = PARROT_SCHEMA        # "navigator"
        strict = True
        frozen = False


class NotificationBatchRecipient(Model):
    """FLAT tracking table — one row per recipient, batch_id repeated.
    Batch totals come from aggregation; there is NO separate batches table."""
    id: uuid.UUID = Field(primary_key=True, required=False,
                          default_factory=uuid.uuid4)
    batch_id: uuid.UUID = Field(required=True)     # indexed
    row_number: int
    provider: str
    recipient_name: Optional[str]
    recipient_address: Optional[str]   # email / phone / channel id
    status: str                        # pending|publishing|queued|skipped|publish_failed
    reason: Optional[str]
    message_id: Optional[str]          # Redis stream entry id returned by xadd
    published_at: Optional[datetime]   # set when xadd returns — the retry marker
    attempts: int = 0                  # incremented on each publish attempt
    template_ref: Optional[str]
    subject: Optional[str]
    created_at: datetime
    created_by: Optional[int]
    updated_at: datetime
```

**Row status state machine (Q4 — duplicate-delivery containment).** The naive
design ("retry everything still `queued`") double-sends after a crash, because
`queued` cannot distinguish "never published" from "published, status update
lost". A pre-`xadd` marker shrinks that ambiguity to a single state:

```
  created ──► pending ──(set publishing, THEN xadd)──► publishing
                 │                                          │
                 │                              xadd returns entry id
                 │                                          ▼
                 │                                       queued  ── terminal, NEVER retried
                 │                                          
                 └── validation failed ──► skipped ── terminal, NEVER retried
                                    
              xadd raised ──► publish_failed ── safe to retry (nothing landed)
```

| Status | Meaning | Retry behavior |
|---|---|---|
| `pending` | Row persisted, `xadd` not yet attempted | **Retried** — definitively never published |
| `publishing` | Marker written, `xadd` outcome unknown (process died mid-call) | **Ambiguous** — reported, retried only with explicit `?force=true` |
| `queued` | `xadd` returned an entry id (`message_id` set) | **Never** retried |
| `skipped` | Failed validation; never eligible | **Never** retried |
| `publish_failed` | `xadd` raised — nothing landed | **Retried** |

This makes duplicate delivery possible **only** for rows caught mid-`xadd`, and
those are surfaced to the operator rather than silently re-sent.

**Wire format published to Redis** (verified round-trip — §6):

```python
{
  "provider": "email",
  "recipient": [ {...}  ],          # per-provider shape, table below
  "template":  "<partially-rendered string>",
  "subject":   "…",
  # row fields forwarded as pass-2 render kwargs:
  "name": "Ana Gomez", "username": "agomez",
  "email": "ana@example.com", "phone": "+34600000000",
}
```

**Per-provider recipient shape** — `NotifyWrapper.__init__` discriminates on
dict keys in this order (`notify/server/wrapper.py:45-58`): `chat_id` → `Chat`,
`team_id` → `TeamsChannel`, `channel_id` → `Channel`, else → `Actor`:

| Provider | Emitted dict | Builds |
|---|---|---|
| `email`, `gmail`, `smtp`, `ses`, `sendgrid`, `office365`, `outlook` | `{"name": …, "account": {"provider": …, "address": <email>}}` | `Actor` + `Account` |
| `twilio`, SMS-like | `{"name": …, "account": {"provider": …, "number": <phone>}}` | `Actor` + `Account` |
| `teams` | `{"name": …, "team_id": …, "channel_id": …}` | `TeamsChannel` |
| `telegram` | `{"chat_name": …, "chat_id": …}` | `Chat` |
| `slack`, `zoom` | `{"channel_name": …, "channel_id": …}` | `Channel` |

⚠️ **`team_id` is checked before `channel_id`** — a dict carrying both becomes a
`TeamsChannel`, never a `Channel`. Emit only the keys the target provider needs.

### Pass-2 binding precedence (and the `username` trap)

`AbstractProvider._render_` builds its template context as
(`notify/providers/base.py:177-183`):

```python
{"recipient": to, "username": to, "message": message, "subject": subject, **kwargs}
```

`**kwargs` is **last**, so the row fields we publish override the defaults. Two
consequences that are **not** optional to handle:

1. **`username` defaults to the `Actor` object, not a string.** If a row has no
   `username` column, `{{ username }}` renders the Actor's `__str__` —
   verified output: `<Ana Gomez: c1c4f2c8-deda-46e8-bda2-c9b5f6018b97>`. A raw
   UUID would ship inside a real email.
   **Requirement**: `CommCenterService.build_wire_payload()` MUST always emit a
   `username` key, falling back to the row's `name` when the column is absent.
   The same defensive rule applies to any canonical field the catalog advertises.
2. **`recipient`, `message` and `subject` are reserved.** `{{ recipient }}`
   renders an object repr, not a name. The catalog marks all three `reserved`
   with "do not use in templates".

### New Public Interfaces

```python
# packages/ai-parrot-server/src/parrot/handlers/comm_center.py

class CommCenterHandler(BaseHandler):
    """Bulk notification sender + Jinja2 template CRUD + placeholder catalog."""

    def __init__(self, *args, **kwargs) -> None: ...

    # --- sender ---
    async def post_sender(self, request: web.Request) -> web.Response: ...
    async def get_batch(self, request: web.Request) -> web.Response: ...
    async def retry_batch(self, request: web.Request) -> web.Response: ...

    # --- templates CRUD (hand-written, same class per requirement) ---
    async def list_templates(self, request: web.Request) -> web.Response: ...
    async def get_template(self, request: web.Request) -> web.Response: ...
    async def create_template(self, request: web.Request) -> web.Response: ...
    async def update_template(self, request: web.Request) -> web.Response: ...
    async def delete_template(self, request: web.Request) -> web.Response: ...

    # --- placeholders (static catalog) ---
    async def get_placeholders(self, request: web.Request) -> web.Response: ...

    def setup(self, app: web.Application) -> None:
        """Register every comm_center route. Repo convention, NOT inherited."""


# packages/ai-parrot-server/src/parrot/services/comm_center.py

class CommCenterService:
    """Transport-agnostic sending core (G12 — reusable by a future toolkit)."""

    async def ingest_recipients(self, *, rows=None, file_path=None,
                                file_bytes=None) -> list[RecipientIn]: ...
    def resolve_functions(self, *, now: datetime | None = None) -> dict: ...
    def partial_render(self, template_string: str, context: dict) -> str: ...
    def validate_and_resolve_provider(self, recipients, default_provider
                                      ) -> tuple[list, list[SkippedRow]]: ...
    def build_wire_payload(self, recipient, provider, template, subject) -> dict: ...
    async def fan_out(self, batch_id, payloads) -> None: ...
```

**Routes**

| Method | Path | Query parameters |
|---|---|---|
| `POST` | `/api/v1/comm_center/sender` | — (`dry_run` is a body field) |
| `GET` | `/api/v1/comm_center/sender/{batch_id}` | `details` (bool, default `false`), `status` (filter), `limit` (default `100`, max `1000`), `offset` (default `0`) |
| `POST` | `/api/v1/comm_center/sender/{batch_id}/retry` | `force` (bool, default `false` — include `publishing` rows) |
| `GET` | `/api/v1/comm_center/templates` |
| `GET` | `/api/v1/comm_center/templates/{template_id}` |
| `POST` | `/api/v1/comm_center/templates` |
| `PUT` / `PATCH` | `/api/v1/comm_center/templates/{template_id}` |
| `DELETE` | `/api/v1/comm_center/templates/{template_id}` |
| `GET` | `/api/v1/comm_center/placeholders` |

---

## 3. Module Breakdown

### Module 1: Notification Templates — Model + DDL
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/notification_templates.py`
  and `.../models/notification_templates_creation.sql`
- **Responsibility**: `NotificationTemplate` asyncdb `Model` +
  `CREATE TABLE navigator.notification_templates` with `UNIQUE(name)`, index on
  `name`, `update_notification_templates_updated_at()` function + `BEFORE
  UPDATE` trigger, and `COMMENT ON` statements. Export from
  `models/__init__.py`.
- **Depends on**: nothing (leaf).
- **Capability**: `comm-center-templates`

### Module 2: Batch Tracking — Model + DDL
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/notification_batches.py`
  and `.../models/notification_batches_creation.sql`
- **Responsibility**: `NotificationBatchRecipient` model + flat table
  `navigator.notification_batch_recipients`, indexed on `batch_id` and
  `status`, with its own `updated_at` trigger. **No separate batches table** —
  totals are aggregated.
- **Depends on**: nothing (leaf).
- **Capability**: `comm-center-batch-tracking`

### Module 3: Placeholder Catalog
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/comm_center_placeholders.py`
- **Responsibility**: Static catalog in three groups, each entry carrying
  `name`, `description`, `example`, and (for functions) a live `sample` value.
  Mirrors the cached-static-catalog pattern of `ScrapingInfoHandler`.
- **Depends on**: `parrot.outputs.a2ui.recipes.params`.
- **Capability**: `comm-center-placeholders`

**Final catalog (Q1 — resolved).**

*Group 1 — recipient fields* (pass 2, worker-side; sourced from the row):

| Placeholder | Required | Notes |
|---|---|---|
| `{{name}}` | yes | The only mandatory column |
| `{{username}}` | no | **Always emitted**; falls back to `name` — see §2 trap |
| `{{email}}` | conditional | Required when the resolved provider is email-like |
| `{{phone}}` | conditional | Required when the resolved provider is SMS-like |
| `{{address}}` | no | Free-form postal/other address |

*Group 2 — computed functions* (pass 1, handler-side). The five
`DATE_RESOLVERS` verbatim plus two module-local extras:

| Placeholder | Source | Output |
|---|---|---|
| `{{today}}` | `resolve_date("today")` | `YYYY-MM-DD` |
| `{{yesterday}}` | `resolve_date("yesterday")` | `YYYY-MM-DD` |
| `{{first_of_month}}` | `resolve_date("first_of_month")` | `YYYY-MM-DD` |
| `{{current_month}}` | `resolve_date("current_month")` | `YYYY-MM` |
| `{{previous_month}}` | `resolve_date("previous_month")` | `YYYY-MM` |
| `{{now}}` | module-local | ISO-8601 timestamp |
| `{{current_year}}` | module-local | `YYYY` |

*Group 3 — reserved* (bound by Notify; **must not** be used in templates):
`{{recipient}}`, `{{message}}`, `{{subject}}` — `{{recipient}}` renders an
object repr, not a name.

**Extra columns**: any column beyond the canonical five is forwarded verbatim
as a pass-2 placeholder. The response documents this, plus the bare-placeholder
limitation (no filters/conditionals on record fields — §7).

### Module 4: Recipient Ingestion
- **Path**: `packages/ai-parrot-server/src/parrot/services/comm_center/ingest.py`
- **Responsibility**: Normalize all three transports into `list[RecipientIn]`.
  Multipart via `BaseHandler.handle_upload()` (**do not hand-roll multipart**);
  base64 decode; inline JSON. `pandas.read_excel` / `read_csv` executed via
  `asyncio.to_thread` (**never block the loop**). Column normalization:
  case-insensitive, trimmed, alias map (`e-mail`/`correo` → `email`,
  `nombre` → `name`, `teléfono`/`telefono`/`mobile` → `phone`,
  `user`/`usuario` → `username`). Enforce 50 MB size cap and the 10 000-recipient
  ceiling.
- **Depends on**: nothing from this spec.
- **Capability**: `comm-center-sender`

### Module 5: Render + Validation Core
- **Path**: `packages/ai-parrot-server/src/parrot/services/comm_center/render.py`
- **Responsibility**: `Environment(undefined=DebugUndefined, autoescape=False,
  enable_async=True)`; `resolve_functions()`; `partial_render()` raising a
  typed error on `TemplateSyntaxError`; per-row provider resolution and
  contact-field validation producing `(queued, skipped)`;
  `build_wire_payload()` implementing the per-provider shape table from §2.
- **Depends on**: Module 3 (function names), Module 4 (row shape).
- **Capability**: `comm-center-sender`

### Module 6: Fan-out + Batch Persistence
- **Path**: `packages/ai-parrot-server/src/parrot/services/comm_center/dispatch.py`
- **Responsibility**: Lazy-import `NotifyClient`; publish one `xadd` per
  recipient driving the §2 status state machine (`pending` → set `publishing`
  **before** the call → `queued` + `message_id` + `published_at` on success,
  `publish_failed` on exception); background `asyncio.Task` with a done-callback
  that logs and finalizes batch status so no batch is stranded in `publishing`;
  batch aggregation query with optional paginated row details; retry that
  re-publishes `pending` + `publish_failed`, and `publishing` only under
  `?force=true`.
- **Depends on**: Modules 2, 5.
- **Capability**: `comm-center-sender`, `comm-center-batch-tracking`

### Module 7: CommCenterHandler + Route Wiring
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/comm_center.py`
- **Responsibility**: The `BaseHandler` subclass — auth, content-type dispatch,
  request/response models, hand-written templates CRUD, `setup(app)`. Thin: all
  logic delegates to Modules 4–6.
- **Depends on**: Modules 1–6.
- **Capability**: all four

### Module 8: Packaging + Tests
- **Path**: `packages/ai-parrot-server/pyproject.toml`,
  `packages/ai-parrot-server/tests/handlers/test_comm_center*.py`
- **Responsibility**: `comm-center` extra (`async-notify`, `pandas`,
  `openpyxl`) added to the `all` aggregator; the full test suite from §4;
  Excel/CSV fixtures.
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

Handler tests live in `packages/ai-parrot-server/tests/handlers/` (verified
convention — e.g. `test_infographic_render_route.py`).

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_partial_render_preserves_record_placeholders` | 5 | `"Hola {{name}}, {{today}}"` → functions resolved, `{{ name }}` literal |
| `test_partial_render_syntax_error_raises` | 5 | Malformed Jinja2 raises before publishing |
| `test_partial_render_is_idempotent_on_second_pass` | 5 | Output of pass 1 renders cleanly in pass 2 with row kwargs |
| `test_resolve_functions_deterministic` | 5 | Injected `now` → fixed values (no wall-clock flake) |
| `test_wire_payload_email_shape` | 5 | Emits `Actor`+`Account(address=…)`; asserts `NotifyWrapper` builds `Actor` |
| `test_wire_payload_teams_shape` | 5 | `team_id` present → `TeamsChannel` |
| `test_wire_payload_telegram_and_slack_shapes` | 5 | `chat_id` → `Chat`; `channel_id` → `Channel` |
| `test_provider_override_per_row` | 5 | Row `provider` column beats the global default |
| `test_unknown_provider_is_skipped_not_defaulted` | 5 | Unknown value → `skipped`, never silent fallback |
| `test_missing_contact_field_skipped_with_reason` | 5 | `provider=email`, no email → `skipped` + reason; batch proceeds |
| `test_ingest_csv_columns_normalized` | 4 | `E-Mail`, ` Nombre `, `Teléfono` → `email`, `name`, `phone` |
| `test_ingest_xlsx_via_openpyxl` | 4 | `.xlsx` fixture → rows |
| `test_ingest_base64_roundtrip` | 4 | base64 CSV → same rows as multipart |
| `test_ingest_rejects_over_size_cap` | 4 | > 50 MB → `413` |
| `test_ingest_rejects_over_recipient_cap` | 4 | > 10 000 rows → `400` |
| `test_ingest_rejects_file_without_known_columns` | 4 | No `name/username/email/phone` → `400` |
| `test_ingest_rejects_empty_file` | 4 | 0 rows → `400` |
| `test_ingest_does_not_block_event_loop` | 4 | pandas call goes through `asyncio.to_thread` |
| `test_placeholders_catalog_shape` | 3 | Both groups present, samples non-empty, limitation string present |
| `test_placeholders_functions_match_date_resolvers` | 3 | Catalog names ⊆ `DATE_RESOLVERS` ∪ explicit extras |
| `test_template_crud_create_read_update_delete` | 1,7 | Round-trip against a mocked/eph. pg |
| `test_template_duplicate_name_conflicts` | 1,7 | Unique violation → `409` |
| `test_template_inactive_rejected_by_sender` | 5,7 | `is_active=false` → `400` |
| `test_sender_requires_authentication` | 7 | Unauthenticated → 401/403 |
| `test_sender_returns_202_with_batch_id` | 7 | Shape of `SenderResponse` incl. `resolved_functions` |
| `test_sender_publishes_one_xadd_per_recipient` | 6 | **Mocked `NotifyClient.stream`** — call count == queued count |
| `test_sender_payload_carries_no_credentials` | 6 | Published dict has no secret-ish keys |
| `test_publish_failure_marks_row_failed` | 6 | `stream()` raises → row `publish_failed`, batch continues |
| `test_batch_progress_aggregation` | 6 | `GET /sender/{id}` totals from the flat table |
| `test_lazy_import_missing_async_notify` | 6,7 | Absent dep → actionable error naming the `comm-center` extra |
| `test_publishing_marker_written_before_xadd` | 6 | Status is `publishing` at the moment `stream()` is entered (assert inside the mock) |
| `test_queued_rows_never_retried` | 6 | Retry skips `queued` and `skipped` — no duplicate send |
| `test_retry_republishes_pending_and_failed` | 6 | Both states re-published; `attempts` incremented |
| `test_retry_excludes_publishing_without_force` | 6 | `publishing` rows reported `ambiguous`, not re-sent |
| `test_retry_includes_publishing_with_force` | 6 | `?force=true` re-publishes them |
| `test_batch_details_paginated` | 6 | `?details=true&limit=…&offset=…`; `limit` clamped to 1000 |
| `test_batch_details_status_filter` | 6 | `?status=skipped` returns only those rows |
| `test_dry_run_publishes_nothing` | 5,7 | `dry_run=true` → `200`, `stream()` never called, **no tracking rows written** |
| `test_dry_run_returns_preview_and_validation` | 5,7 | Preview shows both passes applied; skipped rows still reported |
| `test_username_always_emitted_falls_back_to_name` | 5 | Row without `username` → payload carries `username == name` |
| `test_username_absent_would_leak_actor_repr` | 5 | Regression guard: pinning the upstream behavior the fallback defends against |
| `test_reserved_placeholders_flagged_in_catalog` | 3 | `recipient`/`message`/`subject` marked reserved |
| `test_catalog_functions_are_five_resolvers_plus_two` | 3 | Exactly `DATE_RESOLVERS` + `now` + `current_year` |
| `test_extra_columns_forwarded_as_placeholders` | 4,5 | A non-canonical column reaches the payload kwargs |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_json_recipients_mocked_worker` | JSON list → 202 → assert exact payloads captured from a fake `NotifyClient` |
| `test_end_to_end_multipart_xlsx_mocked_worker` | `.xlsx` upload → 202 → per-recipient payloads with correct personalization |
| `test_end_to_end_stored_template_partial_render` | Template row → partial render → payload carries resolved `{{today}}` and literal `{{ name }}` |
| `test_smoke_template_file_path_real_notify` | **Real `TEMPLATE_DIR` filename** through `NotifyWrapper` — the path that works on async-notify 1.5.5 today (see §7 gating) |
| `test_mixed_valid_invalid_rows_partial_send` | Some rows skipped, rest published; response reports both |

### Test Data / Fixtures

```python
@pytest.fixture
def recipients_csv(tmp_path) -> Path:
    """CSV with aliased/messy headers: 'Nombre', ' E-Mail ', 'Teléfono', 'user'."""

@pytest.fixture
def recipients_xlsx(tmp_path) -> Path:
    """Same data as .xlsx (exercises the openpyxl engine)."""

@pytest.fixture
def fake_notify_client(monkeypatch):
    """Captures every stream() call: (message, stream, use_wrapper).
    Asserting on captured payloads is how §5 sender criteria are verified
    without a live worker."""

@pytest.fixture
def frozen_now() -> datetime:
    """Injected into resolve_functions() so {{today}} is deterministic."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Endpoints & behavior**
- [ ] `CommCenterHandler` subclasses `navigator.views.BaseHandler`, is
      instantiable, and registers every §2 route via `setup(app)`.
- [ ] All three transports accepted: inline JSON, `multipart/form-data`, base64.
- [ ] `POST /sender` returns `202` with `batch_id`, `total`, `queued`,
      `skipped`, `resolved_functions`, and `skipped_details`.
- [ ] Exactly one `xadd` is published per queued recipient (asserted on a
      mocked `NotifyClient.stream`).
- [ ] Published payloads contain **no credentials**.
- [ ] Recipient dicts match the §2 per-provider shape table, verified by
      constructing a real `NotifyWrapper` and asserting the resulting type.
- [ ] Global `provider` is overridden by a per-row `provider` column.
- [ ] Rows missing their provider's contact field are `skipped` with a reason
      and reported; **the remaining rows are still sent**.
- [ ] Unknown per-row provider → `skipped`, never a silent fallback.
- [ ] `GET /sender/{batch_id}` returns aggregated progress from the flat table;
      `?details=true` adds per-recipient rows paginated by `limit` (default 100,
      clamped to 1000) / `offset`, filterable by `?status=`.
- [ ] Row status follows the §2 state machine, with `publishing` written
      **before** the `xadd` and `message_id` + `published_at` after it.
- [ ] `POST /sender/{batch_id}/retry` re-publishes `pending` and
      `publish_failed` rows; **never** `queued` or `skipped`; includes
      `publishing` rows only under `?force=true`, reporting them as ambiguous.
- [ ] `dry_run=true` returns `200` with `resolved_functions`, the validation
      report and a rendered `preview`, while publishing nothing and writing
      **no** tracking rows.
- [ ] `username` is always present in the published payload, falling back to
      `name`, so `{{username}}` can never render an `Actor` repr.
- [ ] Batch is capped at 10 000 recipients (`400`) and uploads at 50 MB (`413`).

**Rendering**
- [ ] Computed functions resolve handler-side; `{{name}}`/`{{email}}`/
      `{{username}}`/`{{phone}}` survive pass 1 literally.
- [ ] A malformed template returns `400` and publishes **nothing**.
- [ ] `resolved_functions` in the response matches what was substituted.
- [ ] Function values are deterministic under an injected `now`.

**Templates CRUD**
- [ ] Full CRUD on `navigator.notification_templates`; duplicate `name` → `409`.
- [ ] `updated_at` is maintained by the DB trigger, not by application code.
- [ ] `created_by` / `updated_by` populated from the session.
- [ ] `is_active=false` templates are rejected by `/sender`.

**Placeholders**
- [ ] `GET /placeholders` returns the three §3 groups — 5 recipient fields,
      7 computed functions (`DATE_RESOLVERS` + `now` + `current_year`), and the
      3 reserved names — with descriptions, examples, live sample values, the
      extra-columns note, and the documented template-language limitation.

**Cross-cutting**
- [ ] All endpoints require `@is_authenticated`.
- [ ] No blocking I/O on the event loop — pandas parsing via `asyncio.to_thread`.
- [ ] `async-notify` imported lazily; absence yields an actionable error naming
      the `comm-center` extra; importing `parrot.handlers.comm_center` without
      it does **not** raise at import time.
- [ ] `ai-parrot-server[comm-center]` extra exists and is in the `all` aggregator.
- [ ] Sending logic lives in `CommCenterService`, callable without aiohttp (G12).
- [ ] Google-style docstrings + type hints on every public function/class.
- [ ] `self.logger` used throughout — no `print`.
- [ ] Both `.sql` files authored with trigger + `COMMENT ON` (not executed).
- [ ] All unit tests pass: `pytest packages/ai-parrot-server/tests/handlers/ -v`
- [ ] All integration tests pass.
- [ ] `ruff check` clean on changed files.
- [ ] No breaking changes to any existing public API.
- [ ] Docs updated in `docs/` covering the API, the per-provider mapping table,
      and the two documented ceilings (no delivery confirmation; bare-placeholder
      limitation).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified 2026-08-06 against the working tree at `ce317b8fc` (rebased onto
> `a4bb6be0e`). Every reference below was executed or read, not recalled.

### Verified Imports

```python
# Confirmed importable in .venv (python -c, 2026-08-06):
from notify.server import NotifyWorker, NotifyClient       # notify/server/__init__.py
from notify.conf import (
    NOTIFY_REDIS, NOTIFY_CHANNEL, NOTIFY_WORKER_STREAM,
    NOTIFY_WORKER_GROUP, TEMPLATE_DIR,
)                                                          # notify/conf.py
from notify.models import Actor, Account, Chat, Channel, TeamsChannel
from notify.server.wrapper import NotifyWrapper            # also re-exported by notify.server
from notify.templates import TemplateParser

from jinja2 import Environment, DebugUndefined             # jinja2 3.1.6
from aiohttp import web
from navigator.views import BaseHandler                    # navigator.views.base
from navigator_auth.decorators import is_authenticated, user_session
from navconfig.logging import logging
from datamodel import BaseModel, Field
from datamodel.parsers.json import json_encoder
from asyncdb import AsyncDB                                # handlers/bots.py:5
from asyncdb.exceptions import NoDataFound                 # handlers/bots.py:6
from asyncdb.models import Model                           # models/users_prompts.py:16
from parrot.conf import PARROT_SCHEMA                      # == "navigator"
from parrot.outputs.a2ui.recipes.params import resolve_date, DATE_RESOLVERS
from parrot.bots.dynamic_values import dynamic_values
import pandas                                              # 2.2.3
import openpyxl                                            # 3.1.5
```

### Existing Class Signatures

```python
# /home/jesuslara/proyectos/notify/notify/server/client.py:18-159
class NotifyClient:
    def __init__(self, redis_url: str = None, redis_host: str = "localhost",
                 redis_port: int = 6379, redis_db: int = 5,
                 tcp_host: str = 'localhost', tcp_port: str = 8991): ...  # line 26
    async def connect(self): ...                                          # line 81
    async def publish(self, message: dict, channel: str): ...             # line 99
    async def stream(self, message: dict, stream: str,
                     use_wrapper: bool = False): ...                      # line 108 ← PUBLISH PATH
    async def close(self): ...                                            # line 146
    async def __aenter__(self) / __aexit__(...)                           # lines 152, 157

# stream() body, lines 108-128 — the exact wire encoding:
#   use_wrapper=False → msg = {"message": json.dumps(message)}
#   use_wrapper=True  → msg = {"uid": …, "task": base64(cloudpickle(NotifyWrapper))}
#   await self.redis.xadd(stream, msg)
# USE use_wrapper=False (JSON path) — it is what NotifyWorker's 'message' branch reads.
```

```python
# /home/jesuslara/proyectos/notify/notify/server/wrapper.py:18-95
class NotifyWrapper:
    def __init__(self, provider: str, *args, **kwargs):        # line 40
        recipients = kwargs.pop('recipient', [])                # line 43 ← KEY IS 'recipient' (singular)
        # discriminator order (lines 45-58):
        #   'chat_id'    → Chat
        #   'team_id'    → TeamsChannel     ← checked BEFORE channel_id
        #   'channel_id' → Channel
        #   else         → Actor
        # non-dict / non-BaseModel recipients are PRINTED AND DISCARDED (line 58)
    async def __call__(self):                                   # line 81
        notify = Notify(self._provider, **self.kwargs)
        async with notify as client:
            return await client.send(recipient=self.recipients, *self.args, **self.kwargs)
    @property
    def uid(self) -> str: ...                                   # line 93

# /home/jesuslara/proyectos/notify/notify/server/server.py:34-580
class NotifyWorker:
    async def check_stream(self): ...        # line 224 — xreadgroup consumer loop
    def build_notify(self, data: dict) -> NotifyWrapper: ...   # line 504
# check_stream reads fn['message'] → build_notify → NotifyWrapper(**msg) → await message()
# → redis.xack(...)  (lines 240-273). NOTHING is published back.

# /home/jesuslara/proyectos/notify/notify/models.py
class Account(BaseModel):                                       # line 28
    provider: str = Field(required=True, default="dummy")
    enabled: bool = Field(required=True, default=True)
    address: Union[str, list[str]] = Field(required=False, default_factory=list)  # ← email
    number:  Union[str, list[str]] = Field(required=False, default_factory=list)  # ← phone
    userid: str; attributes: dict
class Actor(BaseModel):                                         # line 43
    userid: uuid.UUID = Field(required=False, primary_key=True, default=auto_uuid)
    name: str
    account: Optional[Account]
    accounts: Optional[list[Account]]
Recipient = Actor    # line 58
class Chat(BaseModel):         chat_name, chat_id               # line 61
class Channel(BaseModel):      channel_name, channel_id         # line 69
class TeamsChannel(BaseModel): name, channel_id, team_id        # (annotations verified live)

# /home/jesuslara/proyectos/notify/notify/providers/base.py
async def _prepare_(self, recipient=None, message=None,
                    template: str = None, **kwargs):            # line 116
    if template:
        self._template = self._tpl.get_template(template)       # line 142 ← FILENAME LOOKUP (today)
async def _render_(self, to=None, message=None, subject=None, **kwargs):   # line 167
    if self._template:
        self._templateargs = {"recipient": to, "username": to,
                              "message": message, "subject": subject, **kwargs}  # lines 177-183
        msg = await self._template.render_async(**self._templateargs)            # line 184
async def send(self, recipient=None, message=None, subject=None, **kwargs):      # line 242
    message = await self._prepare_(recipient=recipient, message=message, **kwargs)  # line 255

# /home/jesuslara/proyectos/notify/notify/templates.py:7-10 — pass-2 Jinja config
jinja_config = {"enable_async": True,
                "extensions": ["jinja2.ext.i18n", "jinja2.ext.loopcontrols"]}
# NO autoescape key → Jinja2 default autoescape=False applies in pass 2.
```

```python
# packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:65-131
class ScrapingInfoHandler(BaseHandler):        # ← THE HANDLER PATTERN TO COPY
    def __init__(self, *args, **kwargs):       # line 73
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Parrot.ScrapingInfoHandler")
        self._action_catalog = _build_action_catalog()      # cached static catalog
    async def get_actions(self, request: web.Request) -> web.Response:   # line 79
        return web.json_response({"actions": self._action_catalog}, dumps=json_encoder)
    def setup(self, app: web.Application) -> None:                       # line 123
        app.router.add_route("GET", "/api/v1/scraping/info/actions", self.get_actions)
```

```python
# navigator.views.base.BaseHandler — introspected live in .venv
async def handle_upload(self, request: Optional[web.Request] = None,
                        form_key: Optional[str] = None, ext: str = '.csv',
                        preserve_filenames: bool = True
                        ) -> Tuple[Dict[str, List[dict]], dict]: ...
async def get_json(self, request: web.Request = None) -> Any: ...
def json_response(self, response: dict = None, reason: str = None,
                  headers: dict = None, status: int = 200,
                  state: int = None, cls: Callable = None): ...
def error(self, response: dict = None, exception: Exception = None,
          status: int = 400, state: int = None, headers: dict = None,
          content_type: str = 'application/json', **kwargs) -> web.Response: ...
async def get_userid(self, session, idx: str = 'user_id') -> int: ...
def query_parameters(self, request: web.Request) -> dict: ...
# Full member list: _allowed, _allowed_methods, _lasterr, _logger_name, _loop, body,
# critical, data, delete_uploaded_files, error, get_args, get_arguments, get_json,
# get_userid, handle_download, handle_upload, json, json_data, json_response, log,
# log_error, match_parameters, no_content, not_allowed, not_implemented, post_init,
# query_parameters, response, session, validate_handler
# handle_upload raises HTTPUnsupportedMediaType on non-multipart, streams parts to
# temp files, returns (files_grouped_by_field_name, form_fields).
```

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:29-70
DATE_RESOLVERS = ("current_month", "previous_month", "today",
                  "yesterday", "first_of_month")             # line 30
def resolve_date(resolver: str, *, tz: str = "UTC",
                 now: datetime | None = None) -> str: ...    # line 39
# "YYYY-MM" for month resolvers, "YYYY-MM-DD" for day resolvers. Stdlib only.
# `now` is injectable → deterministic tests.

# packages/ai-parrot/src/parrot/bots/dynamic_values.py:13-73
class DynamicValueProvider:
    def register(self, name: str): ...                        # line 18 (decorator)
    async def get_value(self, name: str, context: dict = None) -> Any: ...  # line 25
    def get_all_names(self) -> list: ...                      # line 52
dynamic_values = DynamicValueProvider()                       # line 58
# Built-ins: "current_date" (62), "local_time" (66), "user_name" (70)

# packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py:19-64
class UserPrompts(Model):        # ← MODEL + Meta CONVENTION TO COPY
    prompt_id: uuid.UUID = Field(primary_key=True, required=False,
                                 default_factory=uuid.uuid4)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)
    class Meta:
        driver = "pg"; name = "users_prompts"; schema = PARROT_SCHEMA
        strict = True; frozen = False
```

```sql
-- packages/ai-parrot-server/src/parrot/handlers/models/users_prompts_creation.sql:42-56
-- ← THE updated_at TRIGGER CONVENTION TO COPY (rename per table)
CREATE OR REPLACE FUNCTION update_users_prompts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_users_prompts_updated_at ON navigator.users_prompts;
CREATE TRIGGER trigger_users_prompts_updated_at
    BEFORE UPDATE ON navigator.users_prompts
    FOR EACH ROW
    EXECUTE FUNCTION update_users_prompts_updated_at();
```

### Executed Verifications (not recalled — run in `.venv` 2026-08-06)

**1. Partial rendering works:**
```python
from jinja2 import DebugUndefined, Environment
env = Environment(undefined=DebugUndefined, enable_async=True)
env.from_string("Hola {{ name }}, hoy es {{ today }} - {{ email }}").render(today="2026-08-06")
# → 'Hola {{ name }}, hoy es 2026-08-06 - {{ email }}'          ✅
```

**2. The email wire shape round-trips through `NotifyWrapper`:**
```python
NotifyWrapper(provider="email",
              recipient=[{"name": "Ana Gomez",
                          "account": {"provider": "email",
                                      "address": "ana@example.com",
                                      "number": "+34600000000"}}],
              template="Hola {{ name }}, hoy es 2026-08-06", subject="Test",
              name="Ana Gomez", username="agomez",
              email="ana@example.com", phone="+34600000000")
# recipients[0] → Actor(name='Ana Gomez',
#                       account=Account(provider='email', enabled=True,
#                                       address='ana@example.com',
#                                       number='+34600000000', ...))     ✅
# w.kwargs retains: ['email', 'name', 'phone', 'subject', 'template', 'username']
#   → these become the pass-2 render kwargs via send(**kwargs) → _render_(**kwargs)  ✅
```

**3. Pass-2 binding precedence and the `username` trap** (simulating
`providers/base.py:177-183` exactly):
```python
args = {"recipient": to, "username": to, "message": message, "subject": subject, **kwargs}
# A) row HAS username  → "Hola agomez / Ana Gomez"                          ✅ kwargs win
# B) row LACKS username → "Hola <Ana Gomez: c1c4f2c8-deda-46e8-bda2-c9b5f6018b97>"
#                                                    ⚠️ Actor repr leaks into the message
# C) "{{ recipient }}"  → "<Ana Gomez: c1c4f2c8-…>"  ⚠️ object repr, never a name
# ⇒ REQUIREMENT: always emit `username` (fallback to `name`); mark
#   recipient/message/subject reserved.
```

**4. The other three discriminators:**
```python
NotifyWrapper(provider="teams",    recipient=[{"team_id":"T1","channel_id":"C1","name":"Ops"}])
#   → TeamsChannel(name='Ops', channel_id='C1', team_id='T1')            ✅
NotifyWrapper(provider="telegram", recipient=[{"chat_id":"123"}])
#   → Chat(chat_name=None, chat_id='123')                                ✅
NotifyWrapper(provider="slack",    recipient=[{"channel_id":"C9","channel_name":"general"}])
#   → Channel(channel_name='general', channel_id='C9')                   ✅
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CommCenterHandler` | `BaseHandler.handle_upload()` | method call | live introspection, `navigator.views.base` |
| `CommCenterHandler` | `BaseHandler.get_userid(session)` | method call | live introspection; usage at `handlers/bots.py:109` |
| `CommCenterHandler.setup()` | `app.router.add_route(...)` | convention | `scraping/info.py:123-131` |
| `CommCenterService.fan_out` | `NotifyClient.stream(msg, stream)` | method call | `notify/server/client.py:108` |
| `CommCenterService` | `NOTIFY_WORKER_STREAM` | constant read | `notify/conf.py:29` |
| `CommCenterService.resolve_functions` | `resolve_date(name, now=…)` | function call | `a2ui/recipes/params.py:39` |
| `NotificationTemplate` | `Model` + `Meta(driver="pg")` | subclass | `models/users_prompts.py:19,55-63` |
| wire payload | `NotifyWrapper(**msg)` | JSON over Redis | executed round-trip above |
| size caps | `DEFAULT_MAX_BODY_SIZE` / `MAX_FILE_SIZE` = `50 * 1024 * 1024` | constant convention | `infographic_render.py:63`, `datasets.py:40` |

### Key Attributes & Constants

- `notify.conf.NOTIFY_WORKER_STREAM` → `"NotifyWorkerStream"` *(live; `notify/conf.py:29`, env-overridable)*
- `notify.conf.NOTIFY_WORKER_GROUP` → `"NotifyWorkerGroup"` *(live)*
- `notify.conf.NOTIFY_CHANNEL` → `"NotifyChannel"` *(`notify/conf.py:28`)*
- `notify.conf.NOTIFY_REDIS` → `f"redis://{REDIS_HOST}:{REDIS_PORT}/{NOTIFY_DB}"` *(`notify/conf.py:17`)*
- `notify.conf.TEMPLATE_DIR` → `PosixPath('/home/jesuslara/proyectos/ai-parrot/templates')` *(live; `notify/conf.py:6-10`)*
- `parrot.conf.PARROT_SCHEMA` → `"navigator"` *(live)*
- `parrot.conf.default_dsn` → `postgres://{DBUSER}:{pwd}@{DBHOST}:{DBPORT}/{DBNAME}` *(`packages/ai-parrot/src/parrot/conf.py:66`)*
- Versions: `async-notify 1.5.5`, `jinja2 3.1.6`, `pandas 2.2.3`, `openpyxl 3.1.5`, `parrot 0.25.32`
- `openpyxl>=3.1.2,<=3.1.5` pinned in root `pyproject.toml:133` (`override-dependencies`)
- `async-notify[all]` declared at `packages/ai-parrot/pyproject.toml:138` (extra `notify-all`) and `:463` (extra `integrations`) — **not** base deps
- `ai-parrot-server` base deps are only `["ai-parrot", "pyarrow>=25.0"]` *(`packages/ai-parrot-server/pyproject.toml:28-34`)*
- Handler tests: `packages/ai-parrot-server/tests/handlers/` *(verified dir listing)*

### Does NOT Exist (Anti-Hallucination)

- ~~`notify.templates.TemplateParser.from_string()`~~ — **does not exist**.
  Verified methods are exactly `add_filter`, `environment`, `get_template`,
  `render`, `render_async` — *all* filename-based (`notify/templates.py`).
- ~~`template=` accepting a Jinja2 **string** in async-notify 1.5.5~~ —
  **not supported today**. `_prepare_` unconditionally calls
  `self._tpl.get_template(template)` (`notify/providers/base.py:140-142`),
  resolving a filename under `TEMPLATE_DIR`; a raw string raises
  `FileNotFoundError` via `TemplateNotFound` (`notify/templates.py:71-75`).
  **This spec targets a future async-notify release — see §7 gating.**
- ~~A NotifyWorker result / callback stream~~ — **does not exist**.
  `check_stream()` `xack`s and logs; nothing published back
  (`notify/server/server.py:269-280`). **Delivery status is unobtainable.**
- ~~`parrot.handlers.comm_center`~~ / ~~`parrot.services.comm_center`~~ — do not
  exist yet (this feature).
- ~~`navigator.notification_templates`~~ / ~~`navigator.notification_batch_recipients`~~
  — tables do not exist; only `users_bots_creation.sql` and
  `users_prompts_creation.sql` are present in `handlers/models/`.
- ~~`packages/ai-parrot/src/parrot/handlers/models/`~~ — **this directory does
  not exist.** Models live in **`packages/ai-parrot-server/src/parrot/handlers/models/`**.
  Older SDD tasks (e.g. TASK-1136) cite the pre-package-split path — **do not
  follow them**.
- ~~`BaseHandler.setup()`~~ — **not** inherited API. `ScrapingInfoHandler`
  defines its own `setup(app)` (`scraping/info.py:123`); it is a repo
  convention.
- ~~`{{today}}` as a built-in of `parrot.bots.dynamic_values`~~ — that registry's
  built-ins are `current_date`, `local_time`, `user_name`
  (`dynamic_values.py:62-70`). The `today`/`yesterday`/`current_month` naming
  lives in `parrot.outputs.a2ui.recipes.params.DATE_RESOLVERS`
  (`params.py:29-35`). **Two different registries — do not conflate.**
- ~~`Actor.email`~~ / ~~`Actor.phone`~~ — **not fields**. `Actor` has exactly
  `userid`, `name`, `account`, `accounts` (`notify/models.py:43-51`). Contact
  data goes in the nested `Account.address` / `Account.number`.
- ~~`recipients` (plural) as the wire key~~ — `NotifyWrapper` pops
  **`recipient`** singular (`wrapper.py:43`). A plural key is silently ignored
  and the message goes out with **zero recipients**.
- ~~A generic Excel/CSV → recipients parser in `parrot`~~ — none exists.
  `DatasetManager` file loading is dataset-oriented, not a recipient normalizer.
- ~~`async-notify` in `ai-parrot-server` base dependencies~~ — not there.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Handler**: copy `ScrapingInfoHandler` — `__init__` sets
  `self.logger = logging.getLogger("Parrot.CommCenterHandler")` and caches the
  static catalog; each endpoint is an `async def (self, request) -> web.Response`;
  `setup(app)` registers routes.
- **Models/DDL**: copy `users_prompts.py` + `users_prompts_creation.sql` —
  `Model` with `Meta(driver="pg", name=…, schema=PARROT_SCHEMA, strict=True,
  frozen=False)`, sibling `.sql` with a renamed `update_<table>_updated_at()`
  function, `BEFORE UPDATE` trigger, and `COMMENT ON` statements.
- **Async-first**: `aiohttp` only. `pandas.read_excel`/`read_csv` **must** go
  through `asyncio.to_thread`.
- **Pydantic/datamodel** models for all structured request/response data.
- **Logging** via `self.logger` — never `print`.
- **Google-style docstrings + strict type hints** on everything public.
- **Lazy imports** for `notify` inside methods, mirroring the optional-import
  pattern at `handlers/bots.py:9-16` (`try/except ImportError` + availability
  flag).
- **Size-cap constants** as module-level `MAX_*` following
  `infographic_render.py:63` / `datasets.py:40`.
- **Determinism**: every function resolver takes an injectable `now` so tests
  never depend on wall-clock.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **`DebugUndefined` only preserves *bare* `{{ field }}`.** Filters/tests over undefined values (`{{ name\|upper }}`, `{% if email %}`) raise or collapse in pass 1 | Document prominently in the `/placeholders` response, the API docs, and the module docstring. Add a `test_partial_render_*` case pinning the behavior so it never silently changes |
| **HTML injection**: both passes run `autoescape=False`, so a recipient value containing `<script>` is interpolated raw into HTML email | Documented ceiling. Guidance in `/placeholders`: use `{{ name\|e }}` — but note this *is* a filter, so it only works in pass 2 (worker-side), never pass 1. Flag for a follow-up if HTML email with untrusted names becomes a real case |
| **`recipient` vs `recipients`**: the singular key is mandatory; plural silently sends to nobody | Contract §6 + `test_wire_payload_*` assert on a real `NotifyWrapper` |
| **`team_id` precedence over `channel_id`** — a dict with both always becomes `TeamsChannel` | Per-provider shape table emits only the needed keys; covered by tests |
| **Non-dict recipients are silently discarded** (`wrapper.py:58` just prints) | Always emit dicts; never `BaseModel` instances over JSON |
| **No delivery confirmation** — worker publishes no results | Tracking vocabulary is limited to `queued`/`skipped`/`publish_failed`. API docs must not promise delivery. **The UI must not render "delivered"** |
| **Partial send on Redis failure mid-fan-out**: already-published rows stay `queued`, the rest become `publish_failed` | Surfaced by `GET /sender/{batch_id}`; the batch status reflects partial failure explicitly |
| **Restart mid-fan-out strands rows** | `POST /sender/{batch_id}/retry` (G10) driven by the §2 state machine. The pre-`xadd` `publishing` marker narrows duplicate-delivery risk to rows caught mid-call; those are reported as ambiguous and re-sent only under `?force=true`. `queued` rows are never retried |
| **`{{username}}` leaks an `Actor` repr** when the row lacks that column — Notify binds `username` to the Actor object, so a UUID ships inside a real message. Verified: `<Ana Gomez: c1c4f2c8-…>` | `build_wire_payload()` always emits `username`, falling back to `name`. Two tests pin both the fallback and the upstream behavior it defends against |
| **Reserved names** `recipient`/`message`/`subject` silently shadow row columns of the same name | Catalog marks them reserved; ingestion warns if an uploaded file uses one as a column header |
| **Background task exceptions get swallowed** by a bare `asyncio.create_task` | Attach a done-callback that logs and finalizes batch status; never leave a batch stuck in `publishing` |
| **Redis 7-day stream retention** (`cleanup_old_messages`, `server.py:102-120`) | Irrelevant for us (we don't read back), but do not build any tracking that assumes stream durability |
| **Forward dependency on async-notify string templates** | See gating below |
| **Concurrent `sdd-worker` processes on this repo** | Two were running during spec authoring. Push feature commits promptly; do not `reset --hard` shared branches |

### Release gating & test strategy (resolved)

The string-`template=` path **cannot** be exercised end-to-end against a live
worker until the new `async-notify` ships. The feature **is not gated** on that
release. Instead:

1. Acceptance criteria for the sender are verified by asserting the **exact
   payload that would be published**, via a mocked `NotifyClient.stream`.
2. One **real smoke test** uses `template=<file>.html` from `TEMPLATE_DIR` —
   the path that genuinely works on 1.5.5 today — proving the wire contract and
   the worker handshake.
3. When the new async-notify releases, promote the smoke test to cover the
   string path and bump the dependency floor in the `comm-center` extra.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `async-notify` | `>=1.5.5` (string-`template=` release TBD) | `NotifyClient.stream()` publisher; `NotifyWrapper` contract. **New `comm-center` extra**, lazy-imported |
| `pandas` | `>=2.2` | Excel/CSV → rows |
| `openpyxl` | `>=3.1.2,<=3.1.5` | `.xlsx` engine (pin already in root `override-dependencies`) |
| `jinja2` | `>=3.1` | `Environment(undefined=DebugUndefined)` — already transitive via `notify.templates` |
| `asyncdb` | existing core dep | `pg` driver for both tables |
| `datamodel` | existing core dep | Request/response models, `json_encoder` |
| `redis` | transitive via async-notify | Stream transport |

---

## 8. Open Questions

**Resolved in brainstorm** (carried forward — do not re-litigate):

- [x] Feature or hotfix, and base branch? — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] How do we render Postgres-stored template strings when async-notify only resolves filenames? — *Resolved in brainstorm*: a future async-notify release accepts `template=` as **both** a string and a `TEMPLATE_DIR` path; build as if it exists. Computed functions resolve **in the handler** (partial rendering); record placeholders stay for the worker. → §2 Overview, §7 gating.
- [x] Response contract for `POST /sender`, given the worker publishes no results? — *Resolved in brainstorm*: `202` + `batch_id`, per-recipient tracking in our own table. → G6, §2 Data Models, §5.
- [x] Where do provider credentials come from? — *Resolved in brainstorm*: the NotifyWorker's own environment; no secrets in the HTTP body or the Redis payload. → G4, §5 criterion.
- [x] How is the Excel/CSV uploaded? — *Resolved in brainstorm*: three transports — multipart, inline JSON, base64. (DatasetManager reference **not** selected.) → G2, Module 4.
- [x] How are record placeholders preserved through pass 1? — *Resolved in brainstorm*: Jinja2 `DebugUndefined`; filters/conditionals over undefined values are an accepted, documented limitation. → §2, §7 Risks.
- [x] Fan-out granularity? — *Resolved in brainstorm*: **one `xadd` per recipient**. → G4, §5.
- [x] `navigator.notification_templates` columns? — *Resolved in brainstorm*: `template_id` UUID PK + unique `name`, `subject`, default `provider`, `description`, `tags`, `is_active`, plus string and timestamps. **`user_id` deliberately NOT selected → templates are global.** → §2 Data Models, Module 1.
- [x] Provider resolution and invalid-row policy? — *Resolved in brainstorm*: global `provider` overridable by a per-row column; rows missing the required contact field are **skipped with a reason and reported**, the rest are sent. → G5, §5.
- [x] Handling a 20k-row blast without timing out? — *Resolved in brainstorm*: validate/parse synchronously (fail fast), create the batch, return `202`, fan out in a background asyncio task; progress via `GET /sender/{batch_id}`. → G6, Module 6.
- [x] Tracking table shape? — *Resolved in brainstorm*: **a single flat table**, one row per recipient with a repeated `batch_id`; totals by aggregation, no separate batches table. → §2 Data Models, Module 2.
- [x] Authentication and ownership? — *Resolved in brainstorm*: `@is_authenticated` on all endpoints; templates global; `created_by`/`updated_by` audit columns. → G9, §5.
- [x] How is `async-notify` declared, not being a base dep? — *Resolved in brainstorm*: new `ai-parrot-server[comm-center]` extra + **lazy imports** with a clear error when missing. → G11, Module 8.

**Resolved during spec authoring** (this session):

- [x] Recipient → `Actor` mapping per provider? — *Resolved by user*: `Actor` + nested `Account`, with an explicit per-provider shape table. → §2 table, verified by executed round-trip in §6.
- [x] Which safety/durability features land in v1? — *Resolved by user*: **recipient cap per batch (10 000)** and **`POST /sender/{batch_id}/retry`**. Per-user rate limiting explicitly deferred → §1 Non-Goals.
- [x] How do we verify AC before the async-notify release? — *Resolved by user*: mocked `NotifyClient` payload assertions + one real smoke test using a `TEMPLATE_DIR` **file**. Feature is **not gated** on the external release. → §7 gating, §4.
- [x] Autoescape in pass 1? — *Resolved from evidence*: `notify.templates.jinja_config` (`notify/templates.py:7-10`) sets no `autoescape`, so pass 2 is `False`; pass 1 matches it — enabling it would HTML-escape the preserved `{{ }}` braces. Consequence logged as an HTML-injection risk. → §2 Overview, §7 Risks.
- [x] Upload size cap? — *Resolved from convention*: **50 MB**, matching `DEFAULT_MAX_BODY_SIZE` (`infographic_render.py:63`) and `MAX_FILE_SIZE` (`datasets.py:40`). Row ceiling is the separate 10 000-recipient cap. → G10, §5.
- [x] Column-name normalization? — *Resolved by convention*: case-insensitive, trimmed, plus an alias map (`e-mail`/`correo`→`email`, `nombre`→`name`, `teléfono`/`telefono`/`mobile`→`phone`, `user`/`usuario`→`username`). → Module 4.
- [x] Where do the DDL files get applied? — *Resolved by convention*: authored but **not executed**; applying them is an operator/deployment step, as with `users_prompts_creation.sql`. → §1 Non-Goals.
- [x] CRUD style for templates? — *Resolved from requirement*: **hand-written methods on `CommCenterHandler`**, since the requirement specifies all endpoints on the same `BaseHandler`. A `ModelView` would need a second class and separate route registration. → §2 New Public Interfaces, Module 7.

**Resolved at approval** (spec approved 2026-08-06 — no open questions remain):

- [x] Exact final placeholder catalog? — *Resolved*: three groups. **5 recipient fields** (`name`, `username`, `email`, `phone`, `address`), **7 computed functions** (the five `DATE_RESOLVERS` verbatim + module-local `now` and `current_year`), and **3 reserved names** (`recipient`, `message`, `subject`) that must not be used. Extra columns pass through as placeholders automatically. → §3 Module 3, §5.
- [x] Paginate `GET /sender/{batch_id}`? — *Resolved*: aggregates by default; `?details=true` adds rows paginated by `limit` (default 100, clamped to 1000) / `offset`, filterable by `?status=`. Keeps the default response O(1) for a 10 000-row batch. → §2 routes, §5.
- [x] `dry_run=true`? — *Resolved*: **yes**. Runs ingest → render → validate, returns `200` with `resolved_functions`, the skip report and a rendered `preview`; publishes nothing and writes no tracking rows. Near-free given the architecture, and the natural backstop for a mass-send endpoint. → §2 Data Models, §5.
- [x] Retry duplicate-delivery semantics? — *Resolved*: **add the pre-`xadd` marker.** Row states are `pending → publishing → queued`, with `publishing` written immediately before the call. Retry re-publishes `pending` + `publish_failed`, never `queued`/`skipped`, and includes `publishing` only under `?force=true`. Duplicate risk is confined to rows caught mid-`xadd`, and those are surfaced rather than silently re-sent. → §2 state machine, §3 Module 6, §5, §7.

**Deliberately deferred to follow-up specs** (not blocking implementation):

- Per-user rate limiting / quotas (§1 Non-Goals).
- HTML-escaping strategy for untrusted recipient values in HTML email (§7).
- Template versioning / history.
- Exposing bulk send as an agent toolkit (brainstorm Option C; G12 keeps the path open).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`
- All tasks run **sequentially in one worktree**.

```bash
git worktree add -b feat-FEAT-417-commcenter-notify \
  .claude/worktrees/feat-FEAT-417-commcenter-notify HEAD
```

**Rationale.** The feature has high *logical* parallelism — Modules 1, 2, 3 and
4 are genuinely independent and touch disjoint files — but Modules 5–7 all
converge on `comm_center.py` and its single `setup(app)`. Splitting across
worktrees would trade a modest wall-clock gain for guaranteed conflicts in the
handler. Sequential tasks in one worktree keep each commit small and
conflict-free.

**Suggested task order** (dependency-driven):
`Module 1 → Module 2 → Module 3 → Module 4 → Module 5 → Module 6 → Module 7 → Module 8`

**Cross-feature dependencies**: none. Every primary file is new. The only
shared touchpoints are `packages/ai-parrot-server/pyproject.toml` (one extra)
and the app route wiring (one instantiation) — both single-line additions. No
in-flight spec touches `handlers/comm_center*`, `notification_*`, or the
notify/qworker integration.

**External dependency**: the string-`template=` release of `async-notify` —
**not blocking** (see §7 gating).

**Concurrency note**: two `sdd-worker` processes were active on this repo
during spec authoring. Push feature-branch commits promptly and never
`reset --hard` a shared branch.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-06 | Jesus Lara | Initial draft from `commcenter-notify.brainstorm.md` (Option B). All 13 brainstorm resolutions carried forward; 8 further questions resolved (4 by user, 4 from evidence/convention); wire contract verified by execution. |
| 1.0 | 2026-08-06 | Jesus Lara | **Approved.** Final 4 open questions resolved: placeholder catalog (5 fields / 7 functions / 3 reserved), `?details=true` pagination, `dry_run`, and the `pending→publishing→queued` state machine containing retry duplicates. Added the verified `username` → `Actor`-repr trap and its mandatory fallback. Zero open questions remain. |
