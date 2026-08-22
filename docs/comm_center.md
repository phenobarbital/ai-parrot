# CommCenter — Bulk Notification Sender (FEAT-417)

CommCenter is the HTTP front door for sending a templated communication
blast (email / Teams / Zoom / Telegram / SMS) to a list of recipients, or
to a single recipient synchronously. It publishes one message per
recipient onto the existing NotifyWorker Redis Stream — it does not talk
to any provider directly and does not change NotifyWorker itself.

- Handler: `parrot.handlers.comm_center.CommCenterHandler`
- Sending core: `parrot.services.comm_center` (`ingest.py`, `render.py`,
  `dispatch.py`) — usable without aiohttp (spec G12).
- Optional dependency: `ai-parrot-server[comm-center]` (`async-notify`,
  `pandas`, `openpyxl`). Importing the handler or the service modules
  never requires it; only actually publishing does, and that failure
  returns a clear `503` naming the extra.
- **`async-notify` minimum version: 1.6.0.** CommCenter enqueues an inline
  Jinja2 template string in the xadd payload; `async-notify < 1.6.0`
  silently ignores that key and looks for a `template_file` in
  `TEMPLATE_DIR` instead, delivering an **empty body** with no error on
  either side. `async-notify` 1.6.0 shipped inline Jinja2 template source
  support, which CommCenter relies on. A runtime guard in
  `parrot.services.comm_center.dispatch` raises a clear `RuntimeError`
  (mapped to `503`) naming the required version if an older release is
  installed — checked once per process, right after the "is it installed
  at all" check.

## Two-pass rendering model

A template body is rendered **twice**:

1. **Pass 1** (`CommCenterService`, once per batch): resolves computed
   functions (`{{today}}`, `{{now}}`, …) using Jinja2's `DebugUndefined`,
   so every placeholder it cannot resolve — i.e. every per-recipient
   field — is re-emitted literally: `"Hola {{ name }}, hoy es
   2026-08-06"`.
2. **Pass 2** (`NotifyWorker` → `AbstractProvider._render_`, once per
   recipient): resolves the record placeholders (`{{name}}`, `{{email}}`,
   …) from the row's own fields.

A malformed template fails at pass 1, before a single message is
published — this is deliberate: one bad template returns `400`
immediately instead of producing N silent worker failures.

## Endpoints

All endpoints require `@is_authenticated`.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/comm_center/sender` | Bulk send. `dry_run` is a body field. |
| `GET` | `/api/v1/comm_center/sender` | Paginated batch list — `limit` (default 25, max 100), `offset`, `status`, `provider`, `created_after`, `created_before` |
| `GET` | `/api/v1/comm_center/sender/{batch_id}` | `details`, `status`, `limit` (default 100, max 1000), `offset` |
| `POST` | `/api/v1/comm_center/sender/{batch_id}/retry` | `force` (bool, default `false`) |
| `POST` | `/api/v1/comm_center/message` | Single recipient, synchronous, explicit `provider`. `dry_run` is a body field. |
| `GET` / `POST` | `/api/v1/comm_center/templates` | List / create |
| `GET` / `PUT` / `PATCH` / `DELETE` | `/api/v1/comm_center/templates/{template_id}` | Read / update / delete |
| `GET` | `/api/v1/comm_center/placeholders` | Static catalog — recipient fields, computed functions, reserved names |

### `POST /sender` — bulk send

Accepts recipients via exactly one transport:

- Inline JSON: `{"recipients": [{"name": "Ana", "email": "..."}], ...}`
- `multipart/form-data`: an uploaded Excel/CSV file, other fields as form
  fields.
- Base64: `{"file_b64": "...", "filename": "recipients.csv", ...}`

Exactly one of `template_id`, `template_name`, `template`, or
`template_file` must be given. `provider` is the batch-wide default; a
per-row `provider` column overrides it. Returns `202` with `batch_id`,
`total`, `queued`, `skipped`, `resolved_functions`, `skipped_details`.
Rows missing their provider's contact field are **skipped with a
reason**, never silently dropped — the rest of the batch still sends.
Fan-out happens in a background task; the response does not wait for it.

### `GET /sender` — list batches (FEAT-445 TASK-2319)

The tracking table is flat (one row per recipient, `batch_id` repeated),
so batch-level metadata is derived by aggregation — there is no separate
"batches" table to page through directly. Returns:

```json
{
  "batches": [
    {
      "batch_id": "uuid", "created_at": "ISO-8601", "created_by": 42,
      "total": 150, "queued": 140, "skipped": 8, "publish_failed": 2,
      "pending": 0, "template_ref": "monthly-report", "provider": "email"
    }
  ],
  "total": 47, "limit": 25, "offset": 0
}
```

Query params: `limit` (default 25, clamped to 100), `offset` (default 0),
`status` (batches with at least one row in this status), `provider`
(batches with at least one row for this provider), `created_after` /
`created_before` (ISO-8601 date range). Disambiguated from `GET
/sender/{batch_id}` by the absence of a path parameter.

### `POST /message` — single recipient (G13)

A thin, arity-1 caller over the **same** `prepare()` the bulk endpoint
uses (verified byte-identical payloads for the same input). Publishes
**synchronously** inside the request (no background task for one
`xadd`). `provider` is required and explicit — there is no per-record
override with a single recipient.

Deliberate divergence from the bulk endpoint: an invalid recipient or a
missing `provider` returns `400` with the reason (not `202` + `skipped`);
a publish failure returns `502` with the row left retryable via
`/sender/{batch_id}/retry`.

### `dry_run` (G14)

Set `dry_run: true` on either send endpoint to run the full pipeline
(ingest → template resolution → partial render → provider resolution →
validation) and **stop before any `xadd` and before any tracking row is
written**. Returns `200` (not `202`) with `resolved_functions`,
`skipped_details`, and a `preview` — the first queued recipient's text
rendered through **both** passes, so it is byte-identical to what a real
send would deliver. `batch_id`/`message_id` are `null`; `status` is
`"dry_run"`. The guard is enforced in the service layer
(`dispatch.fan_out`), not only in the handler.

## Per-provider recipient shape

The wire payload's `recipient` key is **singular** — `NotifyWrapper` pops
exactly that key; a plural key silently sends to nobody. Only the keys
each provider needs are emitted:

| Provider | Emitted dict | Builds |
|---|---|---|
| `email`, `gmail`, `smtp`, `ses`, `sendgrid`, `office365`, `outlook` | `{"name": …, "account": {"provider": …, "address": <email>}}` | `Actor` + `Account` |
| `twilio` (SMS-like) | `{"name": …, "account": {"provider": …, "number": <phone>}}` | `Actor` + `Account` |
| `teams` | `{"name": …, "team_id": …, "channel_id": …}` | `TeamsChannel` |
| `telegram` | `{"chat_name": …, "chat_id": …}` | `Chat` |
| `slack`, `zoom` | `{"channel_name": …, "channel_id": …}` | `Channel` |

`team_id` is checked **before** `channel_id` by `NotifyWrapper` — a dict
carrying both always becomes a `TeamsChannel`, never a `Channel`.

## Placeholders

`GET /placeholders` returns three groups:

- **Recipient fields** (pass 2): `name` (required), `username`,
  `email` (required for email-like providers), `phone` (required for
  SMS-like providers), `address`.
- **Computed functions** (pass 1): the five `DATE_RESOLVERS`
  (`today`, `yesterday`, `first_of_month`, `current_month`,
  `previous_month`) plus two module-local extras, `now` and
  `current_year`.
- **Reserved names**: `recipient`, `message`, `subject` — bound by
  Notify's own pass-2 context. Do not use them as template placeholders.

Any recipient column beyond the canonical five is forwarded verbatim as
an extra pass-2 placeholder.

### The `{{username}}` fallback

`AbstractProvider._render_` binds `username` to the recipient object by
default; a row without a `username` column would otherwise render an
internal object representation (verified: `<Ana Gomez:
c1c4f2c8-…>`) instead of a name. CommCenter's `build_wire_payload()`
**always** emits `username`, falling back to `name`, so this can never
happen through this API.

## Known limitations

1. **No delivery confirmation.** `NotifyWorker` acknowledges and logs
   each message but publishes no result stream back. Tracking status
   tops out at `queued` / `skipped` / `publish_failed` — there is no
   `delivered` state, and the UI must not claim there is one.
2. **Bare-placeholder limitation.** Record placeholders must be written
   as bare `{{ field }}`. Filters and conditionals over an unresolved
   value (`{{ name|upper }}`, `{% if email %}`) are not supported in the
   batch-level partial render, because it relies on Jinja2's
   `DebugUndefined` to preserve unresolved fields literally.
3. **HTML injection.** Both render passes run with `autoescape=False`
   (matching `notify.templates`'s own pass-2 configuration), so a
   recipient value is interpolated unescaped into HTML templates. There
   is no built-in escaping for untrusted recipient data today.

## Database setup

CommCenter depends on two Postgres tables in the `navigator` schema —
`notification_templates` and `notification_batch_recipients` — authored as
DDL alongside their models
(`packages/ai-parrot-server/src/parrot/handlers/models/`) but **not applied
automatically**; applying them is an operator/deployment step, per this
repo's convention for handler DDL.

Apply both files, in order, with:

```bash
make apply-commcenter-ddl DATABASE_URL=postgres://user:pass@host:5432/dbname
```

DSN resolution order: `DATABASE_URL` → `NAVIGATOR_DSN` → `PG_URL` — the
target uses whichever of the three is set, so it also works unattended in
an environment that already exports `NAVIGATOR_DSN`:

```bash
export NAVIGATOR_DSN=postgres://user:pass@host:5432/dbname
make apply-commcenter-ddl
```

Both `.sql` files are idempotent (`CREATE TABLE IF NOT EXISTS`,
`CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS`, `CREATE INDEX IF
NOT EXISTS`) — running the target twice, or against a database that
already has the tables, is safe and makes no changes on the second run.

Without this step, the template CRUD endpoints fail with `500` (no table
to read/write) and no batch can be tracked.

## Retry & the row status state machine

`GET /sender/{batch_id}` aggregates a flat, per-recipient tracking table
(`navigator.notification_batch_recipients` — there is no separate
"batches" header table). Each row's `status` follows:

```
created → pending → (set publishing, then xadd) → publishing
                                                       │
                                            xadd returns an entry id
                                                       ▼
                                                    queued  (terminal)
   validation failed → skipped (terminal)
   xadd raised → publish_failed (retryable)
```

`POST /sender/{batch_id}/retry` re-publishes `pending` and
`publish_failed` rows; it **never** retries `queued` or `skipped` rows,
and only includes `publishing` rows when `?force=true` (reported as
`ambiguous` otherwise) — the pre-`xadd` `publishing` marker narrows
duplicate-delivery risk to rows caught mid-call.
