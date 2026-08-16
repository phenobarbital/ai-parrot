---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: CommCenter — Bulk Notification Sender over NotifyWorker

**Date**: 2026-08-06
**Author**: Jesus Lara (with Claude Code)
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

AI-Parrot can host agents and REST surfaces, but it has **no way to send a
templated communication blast** (email / Teams / Zoom / SMS) to a list of
people. Today the two halves of that capability exist but are not connected:

- **`async-notify`** (`/home/jesuslara/proyectos/notify`, installed as
  `async-notify 1.5.5`) knows how to talk to every provider (SMTP, Gmail,
  O365, Teams, Zoom, Twilio, Telegram, Slack, SES, …) and how to render
  Jinja2 templates.
- **Qworker** (`/home/jesuslara/proyectos/qworker`) runs a **`NotifyWorker`**
  process (`qw/process.py:10` → `from notify.server import NotifyWorker`) that
  consumes a Redis Stream and dispatches those notifications
  asynchronously — so the sending work is already distributed and
  out-of-process.

What is missing is the **front door**: an HTTP surface where an operator (or
the Navigator UI) can drop a recipient list — typed inline as JSON, or
uploaded as an Excel/CSV — pick a Jinja2 template and a provider, and have
one personalized message published per recipient into the NotifyWorker
stream.

Three concrete gaps:

1. **No sender endpoint.** Nothing in `parrot.handlers` publishes to the
   NotifyWorker stream. Every blast today is a hand-written script.
2. **No template store.** Jinja2 templates only exist as files under
   `TEMPLATE_DIR` (currently `/home/jesuslara/proyectos/ai-parrot/templates`).
   A non-developer cannot author, version or edit one; there is no CRUD and
   no database table.
3. **No placeholder discovery.** A person writing a template has no way to
   learn which variables are available (`{{name}}`, `{{email}}`, …) or which
   computed functions exist (`{{today}}`). They guess, and the blast renders
   with holes.

**Who is affected**: operations / marketing staff who send the blasts, the
Navigator frontend team who need a documented API to build the composer UI,
and the developers who currently absorb every "can you send this out"
request as manual work.

---

## Constraints & Requirements

- **`CommCenterHandler` must subclass `navigator.views.BaseHandler`** and be
  *instantiable* (the `setup(app)` route-registration pattern used by
  `ScrapingInfoHandler`), not a `BaseView`/`ModelView` class-route.
- **Three endpoints, one handler class**:
  - `POST /api/v1/comm_center/sender`
  - `/api/v1/comm_center/templates` — full CRUD
  - a third **GET-only** placeholders endpoint.
- **Transport is Qworker's NotifyWorker** — a Redis Stream `xadd`. The
  handler never sends a notification itself.
- **Recipient input**: inline JSON list, multipart Excel/CSV upload, and
  base64-embedded file. Columns/keys are `name | username | email | phone`
  and are the Jinja2 placeholders.
- **Provider selectable globally or per-record** (`email`, `zoom`, `teams`, …).
- **Templates persist in Postgres** at `navigator.notification_templates` via
  `asyncdb` `pg` driver, with `created_at` / `updated_at` and a
  `BEFORE UPDATE` trigger maintaining `updated_at`.
- **Placeholder list is static, in-module** for this iteration.
- **Partial rendering**: computed *functions* (`{{today}}`) resolve in the
  handler; per-recipient placeholders (`{{name}}`, `{{email}}`) must survive
  intact in the string so Notify renders them worker-side.
- **Forward-looking dependency**: a future `async-notify` release will accept
  `template=` as **either** a template *string* **or** a `TEMPLATE_DIR` path.
  Build against that contract now. *(Today's 1.5.5 does not — see
  "Does NOT Exist" below. This is a deliberate, user-approved forward
  dependency.)*
- **No secrets over the wire**: provider credentials come from the
  NotifyWorker's own environment; the payload carries only `provider`,
  `recipient`, `message`/`template`, `subject`.
- **Response contract**: `202 Accepted` + `batch_id`; per-recipient rows
  tracked in Postgres.
- **Auth**: all three endpoints require `@is_authenticated`; templates are
  globally readable/writable by any authenticated user, with `created_by` /
  `updated_by` audit columns.
- **Async-first**: `aiohttp` only, no `requests`/`httpx`, no blocking I/O in
  the event loop (pandas parsing must be threaded off).
- **Packaging**: `async-notify` is *not* a base dependency of
  `ai-parrot-server` — it lives in `ai-parrot[notify-all]` /
  `ai-parrot[integrations]`. A new extra plus lazy imports is required.

---

## Options Explored

### Option A: Thin Passthrough — handler renders nothing, worker does everything

The handler is a stateless relay. It parses the recipient source into rows,
and for each row publishes one Redis Stream message carrying `provider`,
`recipient`, and `template` (name or string) plus the row's fields as
kwargs. All Jinja2 rendering — both the record placeholders **and** the
computed functions — happens inside `NotifyWorker` via
`AbstractProvider._render_`. Computed functions like `{{today}}` would have
to be pre-computed and passed as extra kwargs alongside the row fields.

Templates CRUD is a straight `ModelView` over an `asyncdb` `Model`, and the
placeholders endpoint returns a hardcoded catalog.

✅ **Pros:**
- Smallest possible handler: no Jinja2 environment, no rendering code, no
  render-failure surface in the web process.
- Single render pass in one place (the worker) — no risk of double-escaping
  or of a half-rendered string.
- Fastest request: the handler does string assembly and `xadd`, nothing else.

❌ **Cons:**
- **Depends on the worker propagating arbitrary kwargs** into `_render_`.
  `NotifyWrapper.__call__` does `client.send(recipient=…, **self.kwargs)` and
  `AbstractProvider.send()` forwards `**kwargs` into `_prepare_`/`_render_`
  (`notify/providers/base.py:242-259`) — plausible, but each provider's
  `_send_` signature is a separate risk that is *not* verified per provider.
- Template validation is deferred to the worker, so a broken template is
  discovered *after* the 202, per recipient, in the worker log — the operator
  gets no feedback.
- No way to return a rendered preview to the UI before sending.
- Computed-function semantics ("`{{today}}` means today *at request time*")
  become implicit in a kwargs bag rather than being a visible contract.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `async-notify` | `NotifyClient.stream()` publisher | 1.5.5 installed; in `ai-parrot[notify-all]` extra |
| `pandas` | Excel/CSV → rows | 2.2.3 installed |
| `openpyxl` | `.xlsx` engine for pandas | 3.1.5 installed; pinned in root `pyproject.toml:133` |
| `asyncdb` | `pg` driver for templates + tracking | already a core dep |
| `redis` (via async-notify) | Stream transport | transitive |

🔗 **Existing Code to Reuse:**
- `notify/server/client.py:108` — `NotifyClient.stream(message, stream, use_wrapper)`
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:65-131` — instantiable `BaseHandler` + `setup(app)` route pattern
- `packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py` + `users_prompts_creation.sql` — `Model` + DDL + trigger convention

---

### Option B: Partial-Render Gateway — handler resolves functions, worker resolves the person ⭐

The handler owns a **Jinja2 `Environment(undefined=DebugUndefined)`**. It
loads the template body (from the Postgres row, or passes a `TEMPLATE_DIR`
filename straight through), renders it **once per batch** with only the
computed-function context bound (`today`, `now`, `yesterday`,
`current_month`, …). Because the environment uses `DebugUndefined`, every
placeholder it cannot resolve is **re-emitted literally**:

```
"Hola {{ name }}, hoy es {{ today }}"  →  "Hola {{ name }}, hoy es 2026-08-06"
```

*(verified working — see Code Context.)*

The resulting partially-rendered string is what travels in `template=` to
the worker, where Notify performs the second pass and substitutes the
per-recipient fields. One `xadd` per recipient.

Around that core: multi-source recipient ingestion (inline JSON / multipart
/ base64) normalized into a single `Recipient` list; per-record provider
override with a global default; validation that skips invalid rows with a
reason rather than failing the batch; a background publish task so a 20k-row
file returns `202` immediately; and a single flat tracking table with one
row per recipient.

Templates CRUD and the static placeholders catalog live in the same handler
class.

✅ **Pros:**
- **The computed-function contract is explicit and testable in-process** —
  `{{today}}` is resolved once, at request time, with a value the handler can
  log and return; it cannot drift per-recipient or per-retry.
- **Fails fast on template syntax**: a malformed Jinja2 template raises
  during the batch-level render, *before* anything is published, so the
  operator gets a `400` instead of N silent worker failures.
- Enables a future `POST .../preview` with near-zero extra work — the same
  render path with one sample row bound.
- One `xadd` per recipient gives per-person tracking rows, per-person retry,
  and per-person skip reasons.
- Background publish keeps the request short regardless of file size while
  still validating the file synchronously (fail fast on bad columns).

❌ **Cons:**
- **`DebugUndefined` is a partial-rendering hack, not a designed feature.**
  It preserves bare `{{ name }}`, but a *filter* or *test* applied to an
  undefined value (`{{ name|upper }}`, `{% if name %}`) still raises or
  collapses. This must be documented as a hard limitation of the template
  language available to authors.
- Two render passes means two places a template can break, and escaping
  semantics must be reasoned about once (autoescape off in the first pass).
- Requires the forward-looking `async-notify` release that accepts a template
  string — until it ships, the sender path cannot be end-to-end tested
  against a real worker.
- Background publishing means the `202` is a *promise*; a Redis outage
  mid-fan-out surfaces only in the tracking table.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `async-notify` | `NotifyClient.stream()`; future string-template support | 1.5.5 installed; **string `template=` is a forward dependency** |
| `jinja2` | `Environment(undefined=DebugUndefined)` partial render | 3.1.6 installed (transitive, already used by `notify.templates`) |
| `pandas` | Excel/CSV → `DataFrame` → rows | 2.2.3 installed |
| `openpyxl` | `.xlsx` engine | 3.1.5; pinned in root `pyproject.toml:133` |
| `asyncdb` | `pg` driver — templates CRUD + tracking table | core dep (`packages/ai-parrot-server/src/parrot/handlers/bots.py:5`) |
| `datamodel` | `BaseModel` request/response validation + `json_encoder` | core dep |

🔗 **Existing Code to Reuse:**
- `notify/server/client.py:108` — `NotifyClient.stream()`; `notify/server/client.py:26-76` — constructor / Redis DSN resolution
- `notify/conf.py:28-31` — `NOTIFY_WORKER_STREAM` / `NOTIFY_CHANNEL` / `NOTIFY_REDIS`
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:39-70` — `resolve_date()` + `DATE_RESOLVERS` (`today`, `yesterday`, `current_month`, `previous_month`, `first_of_month`), stdlib-only, tz-aware, injectable `now` for deterministic tests. **This is the computed-function engine — do not write a new one.**
- `packages/ai-parrot/src/parrot/bots/dynamic_values.py` — `DynamicValueProvider` registry + `get_all_names()`; the pattern the placeholders endpoint should mirror
- `packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:65-131` — instantiable `BaseHandler`, cached static catalog, `setup(app)` registration
- `navigator.views.BaseHandler.handle_upload()` — built-in multipart parser returning `(files_by_field, form_fields)`; **already exists, do not hand-roll multipart**
- `packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py` + `users_prompts_creation.sql` — `Model` + `Meta(driver="pg", schema=PARROT_SCHEMA)` + `update_*_updated_at()` trigger convention

---

### Option C: Notify-as-a-Toolkit — expose sending as an `AbstractToolkit`, handler is a thin caller

The unconventional option. Instead of putting the logic in a handler, build a
`CommCenterToolkit(AbstractToolkit)` in `parrot/tools/` exposing
`send_notification`, `send_bulk_notification`, `list_templates` and
`list_placeholders` as `@tool`s. `CommCenterHandler` becomes a ~60-line REST
shim that calls the toolkit; the same toolkit is simultaneously usable by any
Agent, over A2A, and over MCP.

The lifecycle hooks (`_open()` / `_close()`, `auto_open=True`, FEAT-391)
manage the Redis connection and the asyncdb pool.

✅ **Pros:**
- **One implementation, three consumers**: REST, agents, and MCP clients all
  get bulk notification for free. An agent could genuinely do "email this
  summary to the regional managers".
- Sits squarely in the documented tool-centric architecture; the lifecycle
  hooks are exactly the DB/Redis-connection use case they were designed for.
- Naturally testable without an HTTP layer.

❌ **Cons:**
- **Overshoots the stated requirement.** The ask is explicitly a
  `BaseHandler` with three endpoints; a toolkit is a second, larger design
  surface to specify, review and maintain.
- **Giving an LLM a bulk-send tool is a serious blast-radius decision** —
  prompt injection now reaches real recipients. It needs approval gating,
  rate limits and recipient allow-lists that are entirely out of scope here.
- Tool signatures are a poor fit for file upload; the multipart path would
  end up in the handler anyway, so the "one implementation" benefit is
  partial.
- Highest effort for the same day-one user-visible outcome.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| *(same as Option B)* | | |
| `parrot.tools.AbstractToolkit` | Toolkit base + `_open`/`_close` lifecycle | in-repo, FEAT-391 |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/` — `AbstractToolkit`, `@tool`, `auto_open` lifecycle (FEAT-391, `.agent/CONTEXT.md`)
- everything listed under Option B

---

## Recommendation

**Option B — Partial-Render Gateway** is recommended.

**Why not A.** Option A's simplicity is real, but it buys that simplicity by
making the operator's feedback loop terrible. A typo'd template under Option
A produces a `202`, then N failures in a worker log the operator cannot see.
Under Option B the same typo raises during the single batch-level render and
comes back as a `400` with the Jinja2 error — before a single message is
published. For a feature whose failure mode is "we sent 20,000 broken emails",
paying one render pass to fail fast is the right trade. Option A also leans on
an unverified assumption — that every provider's `_send_` tolerates arbitrary
extra kwargs — where Option B leans on `DebugUndefined`, which is verified
working in this venv.

**Why not C.** Option C is the better long-term architecture and it is
genuinely tempting given the tool-centric guidance in `.agent/CONTEXT.md`.
It is rejected for *this* feature on scope and safety: the requirement names a
`BaseHandler` with three endpoints, and handing an LLM an unguarded bulk-send
tool imports a prompt-injection blast radius that would need its own spec for
approval gating and rate limiting. Option B does not foreclose it — if the
sending core is factored as a `CommCenterService` that the handler calls, then
a future toolkit wraps that service without a rewrite. **That factoring should
be a spec-level requirement.**

**What Option B trades away, explicitly:**
- `DebugUndefined` restricts template authors to *bare* `{{ placeholder }}`
  references for per-recipient fields. `{{ name|title }}` and
  `{% if email %}` on record fields will not survive the first pass. This is a
  real limitation on the template language and must be documented in the
  placeholders endpoint response, not buried in a docstring.
- Two render passes. Autoescape must be off in pass one, and the interaction
  with HTML email escaping needs one deliberate decision at spec time.
- The `202` is a promise, not a receipt. Delivery truth is not obtainable
  today — `NotifyWorker.check_stream()` (`notify/server/server.py:224-293`)
  `xack`s and logs but publishes **no result stream**. The tracking table can
  therefore only ever record `queued` / `skipped` / `publish_failed`, never
  `delivered`. This ceiling must be stated in the API docs so the UI does not
  promise delivery confirmation it cannot get.

---

## Feature Description

### User-Facing Behavior

**Sending a blast — `POST /api/v1/comm_center/sender`**

The caller authenticates, then submits either:

- `application/json` with `recipients: [{name, username, email, phone, …}]`, or
- `application/json` with the file embedded as base64, or
- `multipart/form-data` with an `.xlsx`/`.csv` file plus a JSON metadata part.

Alongside the recipients, they specify the message source — a stored
`template_id`/`template_name`, an inline Jinja2 `template` string, or a
`TEMPLATE_DIR` filename — plus a default `provider` and an optional `subject`.

The response is **`202 Accepted`**:

```jsonc
{
  "batch_id": "…uuid…",
  "status": "publishing",
  "total": 1204,
  "queued": 1198,
  "skipped": 6,
  "resolved_functions": { "today": "2026-08-06" },
  "skipped_details": [
    { "row": 17, "reason": "provider 'email' requires a non-empty 'email' column" }
  ]
}
```

Rows missing the contact field their provider needs are **skipped with a
reason and reported**; the rest are sent. A malformed template, an unreadable
file, or a file with none of the expected columns is a `400` and **nothing is
published**.

`GET /api/v1/comm_center/sender/{batch_id}` returns the batch's aggregated
counts and per-recipient rows so the UI can show progress.

**Managing templates — `/api/v1/comm_center/templates`**

Standard CRUD. `GET` lists (or fetches one by id/name), `POST` creates,
`PUT`/`PATCH` updates, `DELETE` removes. A template carries a unique
human-readable `name`, the Jinja2 `template_string`, an optional default
`subject` and default `provider`, a `description`, `tags`, and an
`is_active` flag. Templates are **global** — any authenticated user can read
and edit them — but every row records `created_by` / `updated_by`, and
`updated_at` is maintained by a database trigger.

**Discovering placeholders — `GET /api/v1/comm_center/placeholders`**

Returns the static catalog a template author needs, in two groups:

- **Recipient fields** — `name`, `username`, `email`, `phone`, `address`, …
  each with a description, its required-for-provider mapping, and an example.
  These are resolved **worker-side, per recipient**.
- **Computed functions** — `today`, `now`, `yesterday`, `current_month`,
  `previous_month`, `first_of_month`, … each with a description and a live
  sample of its current value. These are resolved **handler-side, once per
  batch**.

The response also carries the documented **limitation**: record placeholders
must be written as bare `{{ field }}` — filters and conditionals over them are
not supported in this iteration.

### Internal Behavior

```
POST /sender
  │
  ├─ 1. Auth (@is_authenticated) → user_id via BaseHandler.get_userid(session)
  │
  ├─ 2. Ingest recipients (content-type dispatch)
  │      multipart → BaseHandler.handle_upload() → temp file
  │      base64    → decode to temp file
  │      json      → rows directly
  │      file rows → pandas.read_excel/read_csv in a thread (asyncio.to_thread)
  │      → normalize column names → list[Recipient]
  │
  ├─ 3. Resolve template source
  │      template_id/name → SELECT from navigator.notification_templates
  │      inline string    → use as-is
  │      TEMPLATE_DIR file→ pass through untouched (no partial render)
  │
  ├─ 4. PARTIAL RENDER (once per batch)
  │      Environment(undefined=DebugUndefined, autoescape=False)
  │      bind ONLY the computed-function context (resolve_date + friends)
  │      → functions substituted, {{name}}/{{email}} preserved literally
  │      → TemplateSyntaxError here ⇒ 400, nothing published
  │
  ├─ 5. Per-row validation + provider resolution
  │      provider = row["provider"] or body["provider"]
  │      required contact field present? → queued : skipped(reason)
  │
  ├─ 6. Create batch rows in Postgres (one row per recipient, status=queued|skipped)
  │
  ├─ 7. 202 Accepted  ← returns here
  │
  └─ 8. BACKGROUND asyncio task: fan-out
         for each queued recipient:
           NotifyClient.stream(
               {"provider": …, "recipient": [Actor-dict], "template": <partial>,
                "subject": …, **row_fields},
               stream=NOTIFY_WORKER_STREAM)
           → one xadd per recipient; update row status on publish failure
```

Worker-side (unchanged, existing code): `NotifyWorker.check_stream()` reads
`{"message": <json>}` from the stream, builds a `NotifyWrapper`, coerces each
recipient dict into an `Actor`/`Chat`/`Channel`/`TeamsChannel`, and calls
`Notify(provider, **kwargs).send(recipient=[…], **kwargs)` — which renders the
second pass and dispatches.

**Responsibility split:**

| Concern | Owner |
|---|---|
| HTTP, auth, content-type dispatch | `CommCenterHandler` |
| Recipient normalization, validation, provider resolution | `CommCenterService` (factored for future toolkit reuse) |
| Computed-function resolution + partial render | `CommCenterService` |
| Redis `xadd` fan-out | `CommCenterService` via `NotifyClient` |
| Per-recipient render + provider dispatch | `NotifyWorker` (existing, untouched) |
| Provider credentials | NotifyWorker environment (never over the wire) |

### Edge Cases & Error Handling

| Case | Behavior |
|---|---|
| Malformed Jinja2 template | `400` at step 4, **nothing published** |
| File has none of `name/username/email/phone` | `400` — cannot template anything |
| File parses but is empty | `400` with an explicit "0 recipients" message |
| Row missing the contact field its provider needs | row `skipped` + reason; batch proceeds |
| Unknown `provider` value in a row | row `skipped` + reason (do not silently fall back to the default) |
| `template_id` not found / `is_active=false` | `404` / `400` |
| Duplicate template `name` on create | `409` (unique constraint) |
| Upload exceeds size cap | `413` — cap is an open question |
| Redis unreachable at step 8 | batch rows flip to `publish_failed`; batch status `failed`; visible via `GET /sender/{batch_id}` |
| Redis dies mid-fan-out | already-published rows stay `queued`; remainder `publish_failed` — **partial send is possible and must be surfaced** |
| `async-notify` not installed | `501`/`503` with an actionable message naming the `comm-center` extra (lazy import) |
| Template uses a filter on a record field (`{{name\|upper}}`) | Known limitation — first pass may raise or collapse it. Detect and warn where feasible; document loudly |
| Server restarts during background fan-out | Rows remain `queued` and are never published — **no resume mechanism in v1**; documented, with a possible `POST /sender/{batch_id}/retry` follow-up |
| Delivery success/failure | **Not observable.** Worker publishes no results; tracking tops out at `queued` |

---

## Capabilities

### New Capabilities
- `comm-center-sender`: REST endpoint accepting inline / Excel / CSV recipient
  lists, partial-rendering a Jinja2 template, and fanning out one Redis-Stream
  message per recipient to the NotifyWorker.
- `comm-center-templates`: Postgres-backed CRUD for named Jinja2 template
  strings at `navigator.notification_templates`, with trigger-maintained
  `updated_at`.
- `comm-center-placeholders`: GET-only static catalog of recipient fields and
  computed functions, with live sample values and documented limitations.
- `comm-center-batch-tracking`: single flat per-recipient table plus a
  `GET /sender/{batch_id}` progress endpoint.

### Modified Capabilities
- *(none — no existing spec's requirements change. `ai-parrot-server`
  packaging gains a new optional extra, which is additive.)*

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/comm_center.py` | **new** | `CommCenterHandler(BaseHandler)` + `setup(app)` |
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_templates.py` | **new** | `asyncdb` `Model`, `Meta(driver="pg", schema=PARROT_SCHEMA)` |
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_templates_creation.sql` | **new** | DDL + `update_notification_templates_updated_at()` trigger |
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_batches_creation.sql` | **new** | Flat per-recipient tracking table |
| `packages/ai-parrot-server/src/parrot/services/comm_center.py` (or similar) | **new** | `CommCenterService` — factored so a future toolkit reuses it (Option C escape hatch) |
| `packages/ai-parrot-server/pyproject.toml` | **modifies** | New `comm-center` extra pulling `async-notify` + `pandas`/`openpyxl`; add to the `all` aggregator |
| App route wiring (`app.py` / `BotManager`) | **modifies** | Instantiate `CommCenterHandler` and call `.setup(app)` — mirrors `ScrapingInfoHandler` |
| `notify` (external repo) | **depends on** | **Forward dependency**: `template=` accepting a string. Until released, the sender path cannot be integration-tested against a live worker |
| `qworker` / `NotifyWorker` | **depends on** | Consumed as-is; **no changes required** |
| Redis (`NOTIFY_REDIS`, db `NOTIFY_DB`) | **depends on** | Web process now needs write access to the NotifyWorker stream — a deployment/network change |
| `parrot.outputs.a2ui.recipes.params` | **depends on** | `resolve_date` / `DATE_RESOLVERS` reused for computed functions |
| Navigator frontend | **depends on** | New API surface for the composer UI |

**Breaking changes:** none — all additive.

**Deployment changes:** the web process needs (a) reachability of the Redis
instance backing `NOTIFY_REDIS`, and (b) the two DDL files applied to Postgres.

---

## Code Context

### User-Provided Code

No code snippets were pasted during discovery. The user supplied two
repository paths, both verified to exist and be importable in `.venv`:

```
# Source: user-provided
/home/jesuslara/proyectos/notify    → async-notify 1.5.5 (installed in .venv)
/home/jesuslara/proyectos/qworker   → qw (installed in .venv)
```

### Verified Codebase References

#### Classes & Signatures

```python
# From /home/jesuslara/proyectos/notify/notify/server/client.py:18-128
class NotifyClient:
    def __init__(
        self,
        redis_url: str = None,          # defaults to notify.conf.NOTIFY_REDIS
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 5,
        tcp_host: str = 'localhost',
        tcp_port: str = 8991,
    ): ...                                                    # line 26
    async def connect(self): ...                              # line 81
    async def publish(self, message: dict, channel: str): ...  # line 99
    async def stream(self, message: dict, stream: str,
                     use_wrapper: bool = False): ...           # line 108  ← THE PUBLISH PATH
    async def send(self, message: dict): ...                   # line 130 (TCP, not used here)
    async def close(self): ...                                 # line 146
    async def __aenter__(self) / __aexit__(...)                # lines 152, 157
```

```python
# From /home/jesuslara/proyectos/notify/notify/server/client.py:108-128
# stream() body — the exact wire format:
async def stream(self, message: dict, stream: str, use_wrapper: bool = False):
    if use_wrapper is True:
        fn = NotifyWrapper(**message)
        serialized_task = cloudpickle.dumps(fn)
        encoded_task = base64.b64encode(serialized_task).decode('utf-8')
        msg = {"uid": fn.uid, "task": encoded_task}
    else:
        data = json.dumps(message)
        msg = {"message": data}          # ← use_wrapper=False is the JSON path
    await self.redis.xadd(stream, msg)
```

```python
# From /home/jesuslara/proyectos/notify/notify/server/server.py:34-45
class NotifyWorker:
    async def check_stream(self): ...    # line 224 — xreadgroup consumer loop
    def build_notify(self, data: dict) -> NotifyWrapper: ...  # line 504
# check_stream() reads fn["message"] → build_notify() → NotifyWrapper(**msg) → await message()
# then redis.xack(...). NO result is published anywhere.  (lines 237-280)
```

```python
# From /home/jesuslara/proyectos/notify/notify/server/wrapper.py:18-95
class NotifyWrapper:
    def __init__(self, provider: str, *args, **kwargs):   # line 40
        recipients = kwargs.pop('recipient', [])           # line 43  ← key name is 'recipient'
        # dict coercion by discriminator key:              # lines 45-58
        #   'chat_id'    → Chat
        #   'team_id'    → TeamsChannel
        #   'channel_id' → Channel
        #   else         → Actor
    async def __call__(self):                              # line 81
        notify = Notify(self._provider, **self.kwargs)
        async with notify as client:
            return await client.send(recipient=self.recipients, *self.args, **self.kwargs)
    @property
    def uid(self) -> str: ...                              # line 93
```

```python
# From /home/jesuslara/proyectos/notify/notify/models.py:43-56
class Actor(BaseModel):
    userid: uuid.UUID = Field(required=False, primary_key=True, default=auto_uuid)
    name: str
    account: Optional[Account]
    accounts: Optional[list[Account]]
Recipient = Actor        # line 58 — alias
Sender = Actor           # line 59

# From notify/models.py:28-41
class Account(BaseModel):
    provider: str = Field(required=True, default="dummy")
    enabled: bool = Field(required=True, default=True)
    address: Union[str, list[str]] = Field(required=False, default_factory=list)  # ← email
    number: Union[str, list[str]] = Field(required=False, default_factory=list)   # ← phone
    userid: str = Field(required=False, default="")
    attributes: dict = Field(required=False, default_factory=dict)
```

```python
# From /home/jesuslara/proyectos/notify/notify/providers/base.py:116-185
async def _prepare_(self, recipient=None, message=None, template: str = None, **kwargs):
    ...
    if template:
        self._template = self._tpl.get_template(template)   # line 142 ← FILENAME LOOKUP (today)
async def _render_(self, to=None, message=None, subject=None, **kwargs):   # line 167
    if self._template:
        self._templateargs = {"recipient": to, "username": to,
                              "message": message, "subject": subject, **kwargs}   # lines 177-183
        msg = await self._template.render_async(**self._templateargs)             # line 184
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:65-131
class ScrapingInfoHandler(BaseHandler):          # THE HANDLER PATTERN TO COPY
    def __init__(self, *args, **kwargs):        # line 73
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Parrot.ScrapingInfoHandler")
        self._action_catalog = _build_action_catalog()      # cached static catalog
    async def get_actions(self, request: web.Request) -> web.Response:   # line 79
        return web.json_response({"actions": self._action_catalog}, dumps=json_encoder)
    def setup(self, app: web.Application) -> None:          # line 123
        app.router.add_route("GET", "/api/v1/scraping/info/actions", self.get_actions)
```

```python
# From navigator.views.base.BaseHandler — introspected live in .venv (python -c)
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
# handle_upload rejects non-multipart with HTTPUnsupportedMediaType, streams each
# part to a temp file, and returns (files_grouped_by_field_name, form_fields).
```

```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/params.py:29-70
DATE_RESOLVERS = ("current_month", "previous_month", "today",
                  "yesterday", "first_of_month")            # line 30
def resolve_date(resolver: str, *, tz: str = "UTC",
                 now: datetime | None = None) -> str: ...   # line 39
# "YYYY-MM" for month resolvers, "YYYY-MM-DD" for day resolvers. Stdlib only.
```

```python
# From packages/ai-parrot/src/parrot/bots/dynamic_values.py:13-56
class DynamicValueProvider:
    def register(self, name: str): ...                       # decorator, line 18
    async def get_value(self, name: str, context: Dict[str, Any] = None) -> Any: ...  # line 25
    def get_all_names(self) -> list: ...                     # line 52
dynamic_values = DynamicValueProvider()                      # line 58 — global registry
# Built-ins registered: "current_date" (line 62), "local_time" (line 66), "user_name" (line 70)
```

```python
# From packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py:19-64
# THE MODEL + Meta CONVENTION TO COPY
class UserPrompts(Model):
    prompt_id: uuid.UUID = Field(primary_key=True, required=False,
                                 default_factory=uuid.uuid4)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)
    class Meta:
        driver = "pg"
        name = "users_prompts"
        schema = PARROT_SCHEMA        # == "navigator" (verified live)
        strict = True
        frozen = False
```

```sql
-- From packages/ai-parrot-server/src/parrot/handlers/models/users_prompts_creation.sql:42-56
-- THE updated_at TRIGGER CONVENTION TO COPY (rename per-table)
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

#### Verified Imports

```python
# All confirmed importable in .venv (python -c, 2026-08-06):
from notify.server import NotifyWorker, NotifyClient       # notify/server/__init__.py
from notify.conf import (
    NOTIFY_REDIS, NOTIFY_CHANNEL, NOTIFY_WORKER_STREAM,
    NOTIFY_WORKER_GROUP, TEMPLATE_DIR,
)                                                          # notify/conf.py
from notify.models import Actor, Account, Chat, Channel, TeamsChannel   # notify/models.py
from notify.templates import TemplateParser                # notify/templates.py

from jinja2 import Environment, DebugUndefined             # jinja2 3.1.6
from aiohttp import web
from navigator.views import BaseHandler                    # navigator.views.base
from navigator_auth.decorators import is_authenticated, user_session
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder
from asyncdb import AsyncDB                                # handlers/bots.py:5
from asyncdb.exceptions import NoDataFound                 # handlers/bots.py:6
from asyncdb.models import Model                           # models/users_prompts.py:16
from datamodel import Field
from parrot.conf import PARROT_SCHEMA                      # == "navigator"
from parrot.outputs.a2ui.recipes.params import resolve_date, DATE_RESOLVERS
from parrot.bots.dynamic_values import dynamic_values
import pandas                                              # 2.2.3
import openpyxl                                            # 3.1.5
```

#### Key Attributes & Constants

- `notify.conf.NOTIFY_WORKER_STREAM` → `"NotifyWorkerStream"` *(verified live; `notify/conf.py:29`, env-overridable)*
- `notify.conf.NOTIFY_WORKER_GROUP` → `"NotifyWorkerGroup"` *(verified live)*
- `notify.conf.NOTIFY_CHANNEL` → `"NotifyChannel"` *(`notify/conf.py:28`)*
- `notify.conf.NOTIFY_REDIS` → `f"redis://{REDIS_HOST}:{REDIS_PORT}/{NOTIFY_DB}"` *(`notify/conf.py:17`)*
- `notify.conf.TEMPLATE_DIR` → `PosixPath('/home/jesuslara/proyectos/ai-parrot/templates')` *(verified live; `notify/conf.py:6-10`, `TEMPLATE_DIR` env-overridable)*
- `parrot.conf.PARROT_SCHEMA` → `"navigator"` *(verified live)*
- `parrot.conf.default_dsn` → `f'postgres://{DBUSER}:{pwd}@{DBHOST}:{DBPORT}/{DBNAME}'` *(`packages/ai-parrot/src/parrot/conf.py:66`)*
- `jinja2.__version__` → `3.1.6`; `pandas` `2.2.3`; `openpyxl` `3.1.5`; `async-notify` `1.5.5`
- `openpyxl>=3.1.2,<=3.1.5` is pinned in root `pyproject.toml:133` (`override-dependencies`)
- `async-notify[all]` is declared in `packages/ai-parrot/pyproject.toml:138` (extra `notify-all`) and `:463` (extra `integrations`) — **not** in base deps
- `ai-parrot-server` base deps are only `["ai-parrot", "pyarrow>=25.0"]` *(`packages/ai-parrot-server/pyproject.toml:28-34`)*
- `qw/process.py:10` → `from notify.server import NotifyWorker`; spawned at `qw/process.py:167-170` as `NotifyWorker_{id}`

**Partial-render mechanism — verified working, not assumed:**

```python
# Executed in .venv on 2026-08-06:
from jinja2 import DebugUndefined, Environment
env = Environment(undefined=DebugUndefined, enable_async=True)
t = env.from_string("Hola {{ name }}, hoy es {{ today }} - {{ email }}")
t.render(today="2026-08-06")
# → 'Hola {{ name }}, hoy es 2026-08-06 - {{ email }}'      ✅ CONFIRMED
```

### Does NOT Exist (Anti-Hallucination)

- ~~`notify.templates.TemplateParser.from_string()`~~ — **does not exist**.
  Verified methods are exactly: `add_filter`, `environment`, `get_template`,
  `render`, `render_async` — *all* filename-based
  (`notify/templates.py:66-129`).
- ~~`template=` accepting a Jinja2 **string** in async-notify 1.5.5~~ —
  **not supported today**. `AbstractProvider._prepare_` unconditionally does
  `self._tpl.get_template(template)` (`notify/providers/base.py:140-142`),
  which resolves a filename under `TEMPLATE_DIR`. Passing a raw template
  string raises `FileNotFoundError` via `TemplateNotFound`
  (`notify/templates.py:71-75`). **This feature is being built against a
  future async-notify release, per explicit user decision.**
- ~~A NotifyWorker result / callback stream~~ — **does not exist**.
  `check_stream()` calls `redis.xack(...)` and logs; nothing is published back
  (`notify/server/server.py:269-280`). Delivery status is **not** obtainable.
- ~~`parrot.handlers.comm_center`~~ — does not exist yet (this feature).
- ~~`navigator.notification_templates`~~ — table does not exist; no DDL file
  in `packages/ai-parrot-server/src/parrot/handlers/models/` (only
  `users_bots_creation.sql` and `users_prompts_creation.sql`).
- ~~`packages/ai-parrot/src/parrot/handlers/models/`~~ — **this directory does
  not exist.** The models live in **`packages/ai-parrot-server/src/parrot/handlers/models/`**.
  (Older SDD tasks such as TASK-1136 reference the `ai-parrot` path from
  before the package split — do not follow those paths.)
- ~~`async-notify` in `ai-parrot-server` base dependencies~~ — not there; base
  deps are `["ai-parrot", "pyarrow>=25.0"]` only.
- ~~`{{today}}` as a built-in in `parrot.bots.dynamic_values`~~ — the registry's
  built-ins are named `current_date`, `local_time`, `user_name`
  (`dynamic_values.py:62-70`). The `today` / `yesterday` / `current_month`
  naming lives in `parrot.outputs.a2ui.recipes.params.DATE_RESOLVERS`
  (`params.py:29-35`). **Two different registries — do not conflate.**
- ~~A generic Excel/CSV → recipients parser in `parrot`~~ — none found;
  `DatasetManager` file loading exists but is dataset-oriented, not a
  recipient normalizer.
- ~~`BaseHandler.setup()`~~ — not a base-class method; `ScrapingInfoHandler`
  defines its own `setup(app)` (`scraping/info.py:123`). It is a repo
  convention, not inherited API.

---

## Parallelism Assessment

- **Internal parallelism**: **High.** The feature decomposes into four
  near-independent strands that touch disjoint files:
  1. **Templates CRUD** — `Model` + `_creation.sql` + CRUD methods.
  2. **Placeholders catalog** — pure static module + one GET method; zero
     dependencies on the other strands.
  3. **Recipient ingestion** — multipart/base64/JSON → normalized rows
     (pandas, `handle_upload`); testable in isolation with fixture files.
  4. **Render + fan-out + tracking** — partial render, `NotifyClient.stream()`,
     tracking DDL and background task.

  Strands 1–3 can run fully in parallel. Strand 4 depends on 1 (needs the
  template row) and 3 (needs normalized rows), so it should land last.

  The shared serialization point is `comm_center.py` itself — all four strands
  add methods to the same handler class and to the same `setup(app)`. That is
  a merge-conflict magnet.

- **Cross-feature independence**: **Clean.** Every primary file is new. The
  only shared touchpoints are `packages/ai-parrot-server/pyproject.toml` (one
  extra added) and the app route wiring — both single-line additions. No
  in-flight spec found touching `handlers/comm_center*`, `notification_*`, or
  the notify/qworker integration. `parrot.outputs.a2ui.recipes.params` and
  `parrot.bots.dynamic_values` are consumed **read-only**.

- **Recommended isolation**: **per-spec**

- **Rationale**: Despite high logical parallelism, all four strands converge
  on one handler class and one `setup(app)` method. Running them in separate
  worktrees would trade a modest wall-clock gain for guaranteed conflicts in
  `comm_center.py`. Sequential tasks in a single worktree — DDL/model first,
  then placeholders, then ingestion, then render/fan-out — keeps each task
  small and each commit conflict-free. The one genuinely splittable piece is
  the placeholders catalog (a standalone module), but it is small enough that
  isolating it is not worth the worktree overhead.

---

## Open Questions

Answered during discovery (Rounds 0–3):

- [x] Feature or hotfix, and which base branch? — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] How do we render Postgres-stored template strings when async-notify only resolves filenames? — *Owner: Jesus Lara*: A future async-notify release will accept `template=` as **both** a string and a `TEMPLATE_DIR` path. Build as if it exists. The **computed functions must be resolved in the handler** (partial rendering); record placeholders stay for the worker.
- [x] What response contract for `POST /sender`, given the worker publishes no results? — *Owner: Jesus Lara*: `202` + `batch_id`, with per-recipient tracking in our own table.
- [x] Where do provider credentials come from? — *Owner: Jesus Lara*: from the NotifyWorker's own environment. No secrets in the HTTP body or the Redis payload.
- [x] How is the Excel/CSV uploaded? — *Owner: Jesus Lara*: **three** transports — `multipart/form-data`, inline JSON `recipients` list, and base64-embedded file. (DatasetManager reference was **not** selected.)
- [x] How are record placeholders preserved through the first render pass? — *Owner: Jesus Lara*: Jinja2 `DebugUndefined` — undefined names are re-emitted literally. Verified working; filters/conditionals over undefined values are an accepted, documented limitation.
- [x] Fan-out granularity? — *Owner: Jesus Lara*: **one `xadd` per recipient**.
- [x] `navigator.notification_templates` columns? — *Owner: Jesus Lara*: `template_id` (UUID PK) + unique `name`, `subject`, default `provider`, `description`, `tags`, `is_active`, plus the string and timestamps. **`user_id` was deliberately NOT selected → templates are global, not per-user.**
- [x] Provider resolution and invalid-row policy? — *Owner: Jesus Lara*: global `provider` in the body, overridable by a per-row column; rows missing the required contact field are **skipped with a reason and reported**, the rest are sent.
- [x] How do we handle a 20k-row blast without timing out? — *Owner: Jesus Lara*: validate and parse synchronously (fail fast), create the batch, return `202` immediately, and fan out in a background asyncio task. Progress via `GET /sender/{batch_id}`.
- [x] Tracking table shape? — *Owner: Jesus Lara*: **a single flat table**, one row per recipient carrying a repeated `batch_id`; batch totals come from aggregation (no separate `batches` table).
- [x] Authentication and ownership? — *Owner: Jesus Lara*: `@is_authenticated` on all three endpoints; templates global; `created_by` / `updated_by` audit columns.
- [x] How is `async-notify` declared, given it is not a base dep? — *Owner: Jesus Lara*: a new `ai-parrot-server[comm-center]` extra plus **lazy imports** inside the methods, with a clear error when the extra is missing.

Still open — to resolve at `/sdd-spec` time:

- [ ] **Upload size cap and row-count ceiling.** What are the limits for the multipart and base64 paths, and does a 50k-row file get rejected or accepted? (`infographic_render.py` uses a 50 MB cap — reuse that number?) — *Owner: Jesus Lara*
- [ ] **Autoescape in the first render pass.** For HTML email templates, does pass one run with `autoescape=False` (assumed above) and is double-escaping in pass two a real risk? Needs one deliberate decision. — *Owner: Jesus Lara*
- [ ] **Recipient → `Actor` mapping.** Which JSON shape do we emit so `NotifyWrapper` builds the right object — a flat `Actor` with `name`, or an `Actor` carrying an `Account(address=email, number=phone)`? `NotifyWrapper` discriminates on `chat_id`/`team_id`/`channel_id` (`wrapper.py:45-58`); Teams and Zoom recipients likely need a different shape than email. **Per-provider mapping table needed in the spec.** — *Owner: Jesus Lara*
- [ ] **Exact placeholder catalog.** Confirm the final list of recipient fields (`name`, `username`, `email`, `phone`, `address`, + what else?) and computed functions (adopt `DATE_RESOLVERS` verbatim, or add `now`, `current_year`, …?). — *Owner: Jesus Lara*
- [ ] **CRUD style for templates.** Hand-written methods on `CommCenterHandler` (keeps all three endpoints in one class, as specified) vs. a `ModelView` subclass (free CRUD, but a second class and a separate route registration). The requirement says "same BaseHandler", which argues for hand-written — confirm. — *Owner: Jesus Lara*
- [ ] **Column-name normalization.** Are Excel headers matched case-insensitively / trimmed / aliased (`e-mail` → `email`, `nombre` → `name`)? — *Owner: Jesus Lara*
- [ ] **Where do the DDL files get applied?** Both new `.sql` files follow the repo convention of being authored but not executed. Confirm this stays an operator/deployment step. — *Owner: Jesus Lara*
- [ ] **Rate limiting / abuse ceiling.** Any authenticated user can trigger a real mass send. Do we need a per-user daily cap or an approval step before v1 ships? — *Owner: Jesus Lara*
- [ ] **Background-task durability.** A restart mid-fan-out strands rows in `queued` forever. Is a `POST /sender/{batch_id}/retry` in scope for v1, or a follow-up? — *Owner: Jesus Lara*
- [ ] **Integration testing before the async-notify release.** The string-`template=` path cannot be tested end-to-end against a live worker until the new async-notify ships. Do we gate the feature on that release, or ship with mocked-worker tests plus a `TEMPLATE_DIR`-filename smoke test? — *Owner: Jesus Lara*
