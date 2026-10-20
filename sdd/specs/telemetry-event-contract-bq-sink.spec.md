---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [telemetry, observability, eventbus, bigquery, kpi]
---

# Feature Specification: Telemetry event contract + BigQuery batch sink

**Feature ID**: FEAT-774 (cross-repo ID, reserved in `fieldsync/sdd/FEAT_ID_LEDGER.md`, dev @ 7217a8d85)
**Jira**: NVP-505 · Epic NVP-502 (Telemetría y KPIs del ecosistema Navigator)
**Date**: 2026-10-20
**Author**: Javier León
**Owner**: Henry Cabello
**Status**: draft
**Target package**: `navigator-eventbus` (github.com/phenobarbital/navigator-eventbus). The code lands upstream; this spec lives in ai-parrot because the bus was extracted from parrot (FEAT-313/317) and parrot is its first consumer. The upstream PR needs Jesús Lara (maintainer).

---

## 1. Motivation & Business Requirements

### Problem Statement

The Navigator ecosystem (navigator-api, navigator-svelte, fieldsync, ai-parrot, navigator-report-builder) has no common usage-event schema.

- **Navigator web usage** reaches OpenSearch `logs-*` only as a free-form `dev.*` log payload. The user is declared by the browser and the retention is 30 days.
- **FieldSync visit telemetry** is only a log line (`visit telemetry: {json}`).
- **Parrot usage** (`UsageRecord`) deliberately carries no user, session or tenant.
- **Chat, feedback and report-builder data** live in separate silos (BigQuery, Postgres, sqlite).

The telemetry POC (FEAT-772/773) builds KPIs from those silos in batch. Phase 2 needs every app to emit **one envelope** into **one table** with long retention.

### Goals

- Define a single `TelemetryEvent` envelope, importable by any Python app in the ecosystem.
- Provide a `BigQueryBatchSubscriber` that writes events to BigQuery `telemetry.events`. It is derived from the existing `AuditSubscriber`: batched, with a bounded queue, dropping the oldest event when full, and never backpressuring.
- Make the sink impossible to break the host app. When BigQuery is down, events are dropped and counted, and requests are never slowed.

### Non-Goals

- Instrumenting each app. That is FEAT-775 (parrot), FEAT-776 (navigator-api), FEAT-777 (svelte), FEAT-778 (fieldsync) and FEAT-779 (report-builder).
- Dashboards. That is FEAT-773.
- Replacing OpenSearch/Logstash, Prometheus metrics or OTel traces. Those stay for operations.
- Provisioning the BigQuery dataset and IAM in Terraform. That is FEAT-780; this spec ships an idempotent `ensure_table()` for dev and staging only.

---

## 2. Architectural Design

### Overview

```
app code ──emit──▶ EventBus / lifecycle registry ──▶ BigQueryBatchSubscriber
                                                     │  deque(maxlen) drop-oldest
                                                     │  flusher task (size | interval)
                                                     ▼
                                     asyncdb "bigquery" .write(rows, table, dataset, use_streams=True)
                                                     ▼
                                     BigQuery  <project>.telemetry.events
```

`AuditSubscriber` already does exactly this against Postgres `navigator.evb_audit`. The new subscriber reuses its design: buffering, drop-oldest, a flusher task, `stats()` and `close()`. Only the writer changes, to the asyncdb `bigquery` driver.

### Integration Points

| Component | Where (installed navigator-eventbus 0.2.3) | Use |
|---|---|---|
| `AuditSubscriber` | `navigator_eventbus/subscribers/audit.py:88` (`batch_size`/`flush_interval`/`queue_size` at :100-124, drop-oldest at :211, flusher at :246, `_flush` at :258, `close` at :177, `stats` at :194) | Template to fork |
| `EventBus.subscribe/publish/emit` | `navigator_eventbus/evb.py:257, 309, 349` | Transport for cross-process events |
| Lifecycle registry | `navigator_eventbus.lifecycle` (re-exported by `parrot/core/events/lifecycle/__init__.py`) | In-process providers (FEAT-775) |
| asyncdb BigQuery | `asyncdb/drivers/bigquery.py` `write()` :297 (`use_streams` → `insert_rows_json` :377, else `load_table_from_json` :385), `create_dataset` :119, `create_table` :145 | Writer |

### Data Models

```python
class TelemetryEvent(BaseModel):
    """One usage event. Immutable once emitted; serialized 1:1 to telemetry.events."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: uuid4().hex)  # idempotency / dedup key
    event_ts: datetime                    # UTC, tz-aware (validator rejects naive)
    event_date: date                      # LOCAL date of the actor (user tz / store tz); partition key
    source_app: Literal["web", "navigator-api", "fieldsync", "ai", "report-builder", "flowtask"]
    event_name: str                       # "domain.action", regex ^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$
    # actor (server-resolved, never trusted from the client)
    user_id: Optional[int] = None
    username: Optional[str] = None
    is_superuser: Optional[bool] = None
    # tenant / navigation
    client_id: Optional[int] = None
    program_id: Optional[int] = None
    program_slug: Optional[str] = None
    module_id: Optional[int] = None
    dashboard_id: Optional[str] = None
    widget_id: Optional[str] = None
    # session / device
    session_id: Optional[str] = None
    platform: Optional[str] = None        # web | android | ios | capacitor
    os: Optional[str] = None
    browser: Optional[str] = None
    app_version: Optional[str] = None
    user_agent: Optional[str] = None      # truncated to 512 chars
    # place
    store_id: Optional[str] = None        # STRING everywhere (fs_stores.store_id is VARCHAR)
    lat: Optional[float] = None
    lon: Optional[float] = None
    # outcome
    duration_ms: Optional[float] = None
    status: Optional[Literal["ok", "error", "timeout", "cancelled"]] = None
    attrs: Dict[str, Any] = Field(default_factory=dict)   # JSON column; ≤ 16 KB serialized

    def to_row(self) -> dict: ...         # JSON-safe dict (isoformat dates, attrs json)
```

### BigQuery DDL (`telemetry.events`)

```sql
CREATE TABLE IF NOT EXISTS `{project}.telemetry.events` (
  event_id STRING NOT NULL, event_ts TIMESTAMP NOT NULL, event_date DATE NOT NULL,
  source_app STRING NOT NULL, event_name STRING NOT NULL,
  user_id INT64, username STRING, is_superuser BOOL,
  client_id INT64, program_id INT64, program_slug STRING,
  module_id INT64, dashboard_id STRING, widget_id STRING,
  session_id STRING, platform STRING, os STRING, browser STRING, app_version STRING, user_agent STRING,
  store_id STRING, lat FLOAT64, lon FLOAT64,
  duration_ms FLOAT64, status STRING, attrs JSON,
  ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY event_date
CLUSTER BY program_slug, source_app, event_name
OPTIONS (partition_expiration_days = NULL);
```

### New Public Interfaces

```python
# navigator_eventbus/telemetry.py
class TelemetryEvent(BaseModel): ...
def build_event(name: str, *, source_app: str, **fields) -> TelemetryEvent: ...

# navigator_eventbus/subscribers/bigquery.py
class BigQueryBatchSubscriber:
    def __init__(self, *, credentials: dict | str, project: str, dataset: str = "telemetry",
                 table: str = "events", batch_size: int = 500, flush_interval: float = 5.0,
                 queue_size: int = 50_000, use_streams: bool = True,
                 event_filter: Callable[[TelemetryEvent], bool] | None = None): ...
    async def start(self) -> None: ...
    def handle(self, event: TelemetryEvent) -> None: ...   # sync, O(1), never awaits I/O
    async def close(self) -> None: ...                     # final flush, bounded by timeout
    def stats(self) -> dict: ...                           # queued, written, dropped, failed_batches
    async def ensure_table(self) -> None: ...              # dev/staging helper; prod uses Terraform (FEAT-780)
```

Configuration comes from env (navconfig) with the prefix `TELEMETRY_`: `TELEMETRY_ENABLED` (default false), `TELEMETRY_BQ_PROJECT`, `TELEMETRY_BQ_DATASET`, `TELEMETRY_BQ_CREDENTIALS`, `TELEMETRY_BATCH_SIZE`, `TELEMETRY_FLUSH_INTERVAL`, `TELEMETRY_QUEUE_SIZE`.

### PII rules

- `attrs` must never contain prompts, completions, passwords, tokens, cookies or full request bodies. A key denylist (`password`, `token`, `authorization`, `cookie`, `secret`, `api_key`) is stripped in `to_row()`.
- Free text (for example AI questions) does **not** go in `telemetry.events`. The FEAT-775 topic job reads it from ChatStorage.
- `lat`/`lon` are only filled for field events (FieldSync), never for web requests.

### Failure behavior

- `handle()` appends to a `deque(maxlen=queue_size)`. On overflow the oldest row is dropped, `dropped` is incremented and a warning is logged every 100 drops (the same as `audit.py:211-216`).
- When a flush fails, the batch is retried once with backoff. After that it is dropped and counted in `failed_batches`. Exceptions never propagate to the emitter.
- `close()` flushes within `flush_timeout` (5 s by default) and then gives up.

---

## 3. Module Breakdown

### Module 1: `navigator_eventbus/telemetry.py`
`TelemetryEvent`, `build_event`, the `event_name` validator and `to_row()` with the denylist.

### Module 2: `navigator_eventbus/subscribers/bigquery.py`
`BigQueryBatchSubscriber`, forked from `AuditSubscriber`. The writer is asyncdb `bigquery`.

### Module 3: wiring helpers
`setup_telemetry(app)` for aiohttp apps. It reads the `TELEMETRY_*` config, starts the subscriber in `on_startup`, closes it in `on_cleanup` and exposes `app["telemetry"].emit(event)`. It is a no-op when `TELEMETRY_ENABLED` is false.

---

## 4. Test Specification

### Unit Tests
- `test_event_name_validation`: `widget.view` is accepted. `Widget loaded successfully` is rejected.
- `test_naive_datetime_rejected`.
- `test_to_row_strips_denylisted_attrs`.
- `test_attrs_size_cap`: more than 16 KB gets a truncated marker.
- `test_drop_oldest_on_overflow`: with `queue_size=3` and 5 events, `dropped == 2`, and the remaining 3 are the newest.
- `test_flush_on_batch_size` and `test_flush_on_interval`, using a fake writer.
- `test_writer_failure_never_raises`: the writer raises, `handle()` still returns, and `failed_batches == 1`.
- `test_close_flushes_pending`.

### Integration Tests
- Staging BigQuery dataset `telemetry_dev`: `ensure_table()`, then emit 1,000 events. All rows must be visible within 60 s and the schema must match the DDL.

### Validation Contract
- With BigQuery unreachable, a load test of 200 req/s on a host app shows **no** p95 latency increase compared with `TELEMETRY_ENABLED=false`.

---

## 5. Acceptance Criteria

- [ ] `TelemetryEvent` and `BigQueryBatchSubscriber` are published in a navigator-eventbus release (an upstream PR merged by the maintainer).
- [ ] Events reach `telemetry.events` in under 60 s at the defaults.
- [ ] The host app is not degraded when BigQuery is down (validation contract).
- [ ] `stats()` is exposed so FEAT-776 can surface it on a health endpoint.
- [ ] The DDL matches what FEAT-780 provisions in Terraform.

---

## 6. Codebase Contract

### Verified references (navigator-eventbus 0.2.3 as installed; ai-parrot origin/dev @ 69fb12a41)
- `navigator_eventbus/subscribers/audit.py:88` `class AuditSubscriber`; drop-oldest at `:211`; `_run_flusher` at `:246`; `_flush` at `:258`.
- `navigator_eventbus/evb.py:257` `subscribe`, `:309` `publish`, `:349` `emit`.
- `asyncdb/drivers/bigquery.py:297` `async def write(..., use_streams: bool = False)`; `:377` `insert_rows_json`; `:385` `load_table_from_json`.
- `packages/ai-parrot/src/parrot/observability/bootstrap.py:138` shows how a subscriber is registered: `get_global_registry().add_provider(subscriber)`.

### Dependents
FEAT-775, FEAT-776, FEAT-778 and FEAT-779 import `TelemetryEvent` and `setup_telemetry`. FEAT-772 (batch ETL) writes the same columns to the `telemetry` dataset tables, so the schemas must stay aligned.

---

## 7. Task Breakdown (for Henry)

1. Open an upstream issue and branch in phenobarbital/navigator-eventbus, and agree on the module location with Jesús Lara.
2. Implement `telemetry.py` (model, validator, denylist, `to_row`), with its unit tests.
3. Fork `AuditSubscriber` into `subscribers/bigquery.py` with the asyncdb `bigquery` writer, retry-once and `stats()`, with its unit tests.
4. Add `setup_telemetry(app)` and the `TELEMETRY_*` config.
5. Run the integration test against staging `telemetry_dev`.
6. Run the load-test validation contract.
7. Release navigator-eventbus and bump the dependency in ai-parrot, navigator-api and fieldsync. FEAT-775, 776 and 778 build on this release.
