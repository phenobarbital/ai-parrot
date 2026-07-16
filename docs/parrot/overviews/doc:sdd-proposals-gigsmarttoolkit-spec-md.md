---
type: Wiki Overview
title: GigSmart Toolkit — SPEC
id: doc:sdd-proposals-gigsmarttoolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. Authentication / session bootstrap
relates_to:
- concept: mod:parrot.tools
  rel: mentions
---

# GigSmart Toolkit — SPEC

**Framework:** ai-parrot (`parrot.tools` / `WorkingMemoryToolkit` family)
**Target API:** GigSmart Developer API (GraphQL) — https://developers.gigsmart.ninja/docs
**Status:** Draft — pending introspection against live endpoint
**Naming convention in this doc:** Anything wrapped as `[VERIFY]` is a placeholder that must be replaced with the exact identifier/field/enum from the live GraphQL schema (via introspection or the rendered docs). The *shape* of inputs/outputs is designed; the *names* are inferred and must be confirmed.

---

## 0. Scope & Non-Goals

### In scope
- Authenticated GraphQL client (sync internal, async external interface) for the GigSmart API.
- Six functional surfaces, each exposed as a typed async tool method:
  1. Authentication / session bootstrap
  2. Location management (create, list, get)
  3. Position management (create, list, get)
  4. Gig posting (create, list, cancel)
  5. Engagement management (list, hire, message, end)
  6. Timesheet workflow (review, edit, approve, dispute response)
- Pydantic v2 input/output models with strict validation.
- A `DeterministicGuard` layer over write mutations (mirrors the TradierWrite mandate pattern).
- Integration with `WorkingMemoryToolkit` so result sets (engagements, timesheets) land as session DataFrames instead of bloating context.

### Out of scope (initial release)
- Webhooks / event subscriptions (separate spec; GigSmart likely supports webhooks for engagement state changes — track as follow-up).
- Worker-side mutations (this toolkit is requester/employer-side only).
- Payment dispute *initiation* by the worker (only requester-side response is included).
- Onfleet integration plumbing (the GigSmart side of Onfleet linkage is in scope only as a position attribute, not as a separate Onfleet client).

---

## 1. Reference Documentation

These are the authoritative sources. The SPEC implementer must read each before touching the relevant section.

| Section | Doc URL |
|---|---|
| Getting started | https://developers.gigsmart.ninja/docs/getting-started |
| Authentication | https://developers.gigsmart.ninja/docs/authentication |
| Create Location | https://developers.gigsmart.ninja/docs/guides/create-location |
| Create Position | https://developers.gigsmart.ninja/docs/guides/create-position |
| Post a Gig | https://developers.gigsmart.ninja/docs/guides/post-a-gig |
| Manage Engagements | https://developers.gigsmart.ninja/docs/guides/manage-engagements |
| Timesheet workflow | https://developers.gigsmart.ninja/docs/guides/timesheet-workflow |

> **Note:** The docs site is a JS-rendered SPA; raw HTTP fetching returns only the shell. The schema must be obtained via introspection against the live endpoint once credentials are provisioned.

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Agent (LLM) — tool calls                                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  GigSmartToolkit  (subclass of WorkingMemoryToolkit)               │
│   • @tool_schema methods, one per use case                         │
│   • Pydantic-validated args/returns                                │
│   • Large list responses → WorkingMemory DataFrames                │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  DeterministicGuard  (write-only)                                  │
│   • Idempotency keys                                               │
│   • Mandate checks (cost cap, time-window, dup detection)          │
│   • Post-mutation reconciliation                                   │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  GigSmartGraphQLClient  (transport)                                │
│   • httpx.AsyncClient + retry/backoff                              │
│   • Auth header injection                                          │
│   • GraphQL error → typed exception mapping                        │
│   • Optional response caching (queries only)                       │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    GigSmart GraphQL endpoint
```

### Module layout

```
parrot/tools/gigsmart/
    __init__.py
    toolkit.py            # GigSmartToolkit
    client.py             # GigSmartGraphQLClient
    auth.py               # credential loading, header builders
    guard.py              # DeterministicGuard + mandates
    models/
        __init__.py
        common.py         # shared enums, money, address
        location.py
        position.py
        gig.py
        engagement.py
        timesheet.py
    queries/              # raw GraphQL documents as Python strings
        locations.graphql
        positions.graphql
        gigs.graphql
        engagements.graphql
        timesheets.graphql
    exceptions.py
    config.py
```

GraphQL documents live as `.graphql` files loaded at import time. This keeps queries reviewable in isolation and avoids embedding multi-line strings in Python.

---

## 3. Authentication

### 3.1 Credentials model

```python
class GigSmartCredentials(BaseModel):
    api_key: SecretStr                       # primary credential
    api_secret: SecretStr | None = None      # [VERIFY] only if 2-part scheme
    environment: Literal["production", "sandbox"] = "production"
    endpoint_override: HttpUrl | None = None
```

### 3.2 Loading order (highest precedence first)
1. Explicit `credentials=` argument to `GigSmartToolkit.__init__`
2. Environment variables: `GIGSMART_API_KEY`, `GIGSMART_API_SECRET`, `GIGSMART_ENV`
3. GCP Secret Manager (when running on Cloud Run): secret IDs `gigsmart-api-key`, `gigsmart-api-secret`

### 3.3 Header construction `[VERIFY]`

Expected pattern (typical for GraphQL APIs of this type):

```
POST /graphql HTTP/1.1
Authorization: Bearer <api_key>
Content-Type: application/json
X-GigSmart-Client: parrot-toolkit/<version>
```

If GigSmart uses a custom header name (e.g. `X-API-Key`) or HMAC signing, `auth.py:build_headers()` is the single point that must change. **All other code paths go through `build_headers()`** — no auth logic anywhere else.

### 3.4 Endpoint resolution

| Environment | Endpoint URL |
|---|---|
| production | `[VERIFY]` (likely `https://api.gigsmart.com/graphql` or similar) |
| sandbox    | `[VERIFY]` |

### 3.5 Auth verification tool

```python
@tool_schema
async def verify_auth(self) -> AuthStatus:
    """Lightweight ping that runs `query { viewer { id, organizationName } }`
    (or equivalent [VERIFY]) and returns the authenticated account identity.
    Use this first in any new agent crew to fail fast on misconfigured keys."""
```

---

## 4. GraphQL Transport (`client.py`)

### 4.1 Class signature

```python
class GigSmartGraphQLClient:
    def __init__(
        self,
        credentials: GigSmartCredentials,
        *,
        timeout: float = 30.0,
        retry: RetryConfig | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None: ...

    async def execute(
        self,
        document: str,
        variables: Mapping[str, Any] | None = None,
        *,
        operation_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...
    async def __aenter__(self) -> "GigSmartGraphQLClient": ...
    async def __aexit__(self, *exc_info) -> None: ...
```

### 4.2 Retry policy
- Idempotent operations (queries, mutations with idempotency keys): exponential backoff on 5xx, network errors, and GraphQL errors classified as `RETRYABLE` (see §9).
- Non-idempotent mutations without idempotency key: **no retry** by default; surfaces as `NonRetryableMutationError`.
- Defaults: 3 attempts, base 0.5s, jitter, cap 8s. Override via `RetryConfig`.

### 4.3 Error mapping

```python
class GigSmartError(Exception): ...
class GigSmartAuthError(GigSmartError): ...           # 401, INVALID_TOKEN
class GigSmartValidationError(GigSmartError): ...     # input/validation issues
class GigSmartRateLimitError(GigSmartError): ...      # 429
class GigSmartNotFoundError(GigSmartError): ...       # entity not found
class GigSmartTransportError(GigSmartError): ...      # network/5xx
class GigSmartGraphQLError(GigSmartError):            # GraphQL `errors` array
    def __init__(self, errors: list[dict]): ...
```

All GraphQL responses are checked for an `errors` array *before* `data` is returned, regardless of HTTP status — GraphQL APIs commonly return 200 with errors embedded (see Shopify, GitHub patterns).

### 4.4 Logging

Every call emits a structured log entry:

```
{
  "evt": "gigsmart.graphql",
  "op": "<operationName>",
  "elapsed_ms": 234,
  "ok": true,
  "vars_hash": "<sha256(variables[:8])>",
  "idempotency_key": "...",
}
```

Never log raw `variables` (may contain PII — addresses, worker IDs). Only hash.

---

## 5. Domain Model

GigSmart's data model (inferred from public docs and help center):

```
Organization (requester account)
  └─ Location          (a physical address where work happens)
       └─ Position     (a role template: title, skills, pay rate, requirements)
            └─ Gig     (a posted instance: time window + workers needed)
                 └─ Engagement   (one worker's relationship to one gig)
                      └─ Timesheet (time records + breaks + adjustments)
```

### 5.1 Lifecycle states `[VERIFY enum names/values]`

**Gig** state: `DRAFT → POSTED → IN_PROGRESS → COMPLETED → CLOSED` (plus `CANCELLED`).
**Engagement** state: `APPLIED → OFFERED → HIRED → CLOCKED_IN → CLOCKED_OUT → PAID` (plus `DECLINED`, `CANCELLED`, `NO_SHOW`).
**Timesheet** state: `PENDING_WORKER_REVIEW → PENDING_REQUESTER_REVIEW → APPROVED → DISPUTED → FINAL`.

These are best-guess; replace with exact enum values from introspection.

---

## 6. Pydantic Schemas

All models are Pydantic v2, frozen by default for inputs that flow into mutations (defensive immutability), and emit camelCase aliases for GraphQL input variables.

### 6.1 Shared (`models/common.py`)

```python
class Money(BaseModel):
    """All monetary amounts in minor units (cents) to avoid float drift."""
    amount_cents: int = Field(ge=0)
    currency: Literal["USD"] = "USD"

class Address(BaseModel):
    line1: str
    line2: str | None = None
    city: str
    state: str = Field(min_length=2, max_length=2)   # US 2-letter
    postal_code: str = Field(pattern=r"^\d{5}(-\d{4})?$")
    country: Literal["US"] = "US"
    latitude: float | None = None
    longitude: float | None = None

class TimeWindow(BaseModel):
    start_at: datetime                                # tz-aware required
    end_at: datetime
    timezone: str = Field(default="America/Denver")   # IANA

    @model_validator(mode="after")
    def _check_order(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self

class PageInfo(BaseModel):
    has_next: bool
    end_cursor: str | None = None

class Page[T](BaseModel):
    nodes: list[T]
    page_info: PageInfo
```

### 6.2 Locations (`models/location.py`)

```python
class CreateLocationInput(BaseModel, frozen=True):
    name: str = Field(min_length=1, max_length=120)
    address: Address
    contact_phone: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    external_ref: str | None = None      # for idempotency / cross-system linking

class Location(BaseModel):
    id: str                              # [VERIFY] GraphQL ID type
    name: str
    address: Address
    contact_phone: str | None = None
    created_at: datetime
    archived_at: datetime | None = None
```

### 6.3 Positions (`models/position.py`)

```python
class WorkerRequirement(BaseModel, frozen=True):
    """[VERIFY] — exact requirement taxonomy comes from GigSmart enums."""
    requires_background_check: bool = False
    requires_drug_test: bool = False
    required_certifications: list[str] = Field(default_factory=list)
    minimum_rating: float | None = Field(default=None, ge=0, le=5)

class TravelDelivery(BaseModel, frozen=True):
    workers_travel: bool = False
    requires_own_vehicle: bool = False
    estimated_mileage: int | None = Field(default=None, ge=0)
    onfleet_enabled: bool = False
    onfleet_api_key_ref: str | None = None    # reference to secret, not the key itself

class CreatePositionInput(BaseModel, frozen=True):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)
    category: str                              # [VERIFY] enum
    pay_rate_cents_per_hour: int = Field(ge=0)
    location_id: str
    requirements: WorkerRequirement = Field(default_factory=WorkerRequirement)
    travel_delivery: TravelDelivery = Field(default_factory=TravelDelivery)
    w2_required: bool = False                  # see GigSmart W-2 help docs
    skills: list[str] = Field(default_factory=list)
    external_ref: str | None = None

class Position(BaseModel):
    id: str
    title: str
    description: str
    pay_rate_cents_per_hour: int
    location: Location
    requirements: WorkerRequirement
    travel_delivery: TravelDelivery
    w2_required: bool
    created_at: datetime
    archived_at: datetime | None = None
```

### 6.4 Gigs (`models/gig.py`)

```python
class PostGigInput(BaseModel, frozen=True):
    position_id: str
    time_window: TimeWindow
    workers_needed: int = Field(ge=1, le=500)    # upper bound is a guard, not API
    pay_rate_override_cents: int | None = Field(default=None, ge=0)
    instructions: str | None = Field(default=None, max_length=5000)
    auto_approve_applications: bool = False
    external_ref: str | None = None

class Gig(BaseModel):
    id: str
    position: Position
    time_window: TimeWindow
    workers_needed: int
    workers_hired: int
    state: str                                    # [VERIFY] use Literal once enum confirmed
    pay_rate_cents_per_hour: int
    created_at: datetime
    posted_at: datetime | None = None
    cancelled_at: datetime | None = None

class CancelGigInput(BaseModel, frozen=True):
    gig_id: str
    reason: str = Field(min_length=1, max_length=500)
```

### 6.5 Engagements (`models/engagement.py`)

```python
class Worker(BaseModel):
    id: str
    display_name: str
    rating: float | None = None
    verified: bool = False

class Engagement(BaseModel):
    id: str
    gig_id: str
    worker: Worker
    state: str                                    # [VERIFY]
    applied_at: datetime | None = None
    hired_at: datetime | None = None
    clocked_in_at: datetime | None = None
    clocked_out_at: datetime | None = None

class HireWorkerInput(BaseModel, frozen=True):
    engagement_id: str

class EndEngagementInput(BaseModel, frozen=True):
    engagement_id: str
    reason: str = Field(min_length=1)

class MessageEngagementInput(BaseModel, frozen=True):
    engagement_id: str
    body: str = Field(min_length=1, max_length=2000)
```

### 6.6 Timesheets (`models/timesheet.py`)

```python
class TimesheetBreak(BaseModel):
    start_at: datetime
    end_at: datetime
    paid: bool = False

class Timesheet(BaseModel):
    id: str
    engagement_id: str
    clock_in: datetime
    clock_out: datetime
    breaks: list[TimesheetBreak] = Field(default_factory=list)
    additional_payment_cents: int = 0
    state: str                                    # [VERIFY]
    submitted_at: datetime | None = None
    approved_at: datetime | None = None

class EditTimesheetInput(BaseModel, frozen=True):
    timesheet_id: str
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    breaks: list[TimesheetBreak] | None = None
    additional_payment_cents: int | None = Field(default=None, ge=0)
    adjustment_reason: str = Field(min_length=1, max_length=500)

class ApproveTimesheetInput(BaseModel, frozen=True):
    timesheet_id: str
    final_total_minutes: int | None = None    # optional sanity check; client recomputes

class TimesheetDisputeResponse(BaseModel, frozen=True):
    timesheet_id: str
    accept: bool
    response_note: str = Field(min_length=1, max_length=2000)
```

---

## 7. Toolkit Methods (`toolkit.py`)

`GigSmartToolkit` extends `WorkingMemoryToolkit`. Every method:
- is `async`
- is decorated with `@tool_schema`
- validates its input via the corresponding Pydantic model
- routes through `DeterministicGuard` for mutations
- routes large list results through `WorkingMemoryToolkit.register_dataframe(...)` and returns a `DataFrameHandle` (not raw rows) when result size > 50

### 7.1 Auth & ping

```python
@tool_schema
async def verify_auth(self) -> AuthStatus: ...
```

### 7.2 Locations

```python
@tool_schema
async def create_location(self, payload: CreateLocationInput) -> Location: ...

@tool_schema
async def get_location(self, location_id: str) -> Location: ...

@tool_schema
async def list_locations(
    self,
    *,
    name_contains: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> Page[Location] | DataFrameHandle: ...
```

### 7.3 Positions

```python
@tool_schema
async def create_position(self, payload: CreatePositionInput) -> Position: ...

@tool_schema
async def get_position(self, position_id: str) -> Position: ...

@tool_schema
async def list_positions(
    self,
    *,
    location_id: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> Page[Position] | DataFrameHandle: ...

@tool_schema
async def archive_position(self, position_id: str, reason: str) -> Position: ...
```

### 7.4 Gigs

```python
@tool_schema
async def post_gig(self, payload: PostGigInput) -> Gig: ...

@tool_schema
async def get_gig(self, gig_id: str) -> Gig: ...

@tool_schema
async def list_gigs(
    self,
    *,
    state: str | None = None,
    position_id: str | None = None,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> Page[Gig] | DataFrameHandle: ...

@tool_schema
async def cancel_gig(self, payload: CancelGigInput) -> Gig: ...
```

### 7.5 Engagements

```python
@tool_schema
async def list_engagements(
    self,
    *,
    gig_id: str | None = None,
    worker_id: str | None = None,
    state: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> Page[Engagement] | DataFrameHandle: ...

@tool_schema
async def get_engagement(self, engagement_id: str) -> Engagement: ...

@tool_schema
async def hire_worker(self, payload: HireWorkerInput) -> Engagement: ...

@tool_schema
async def end_engagement(self, payload: EndEngagementInput) -> Engagement: ...

@tool_schema
async def send_engagement_message(self, payload: MessageEngagementInput) -> Engagement: ...
```

### 7.6 Timesheets

```python
@tool_schema
async def list_pending_timesheets(
    self,
    *,
    gig_id: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> Page[Timesheet] | DataFrameHandle: ...

@tool_schema
async def get_timesheet(self, timesheet_id: str) -> Timesheet: ...

@tool_schema
async def edit_timesheet(self, payload: EditTimesheetInput) -> Timesheet: ...

@tool_schema
async def approve_timesheet(self, payload: ApproveTimesheetInput) -> Timesheet: ...

@tool_schema
async def respond_to_dispute(self, payload: TimesheetDisputeResponse) -> Timesheet: ...
```

### 7.7 Method-to-doc traceability

| Toolkit method | GigSmart guide |
|---|---|
| `verify_auth` | Authentication |
| `create_location`, `get_location`, `list_locations` | Create Location |
| `create_position`, `get_position`, `list_positions`, `archive_position` | Create Position |
| `post_gig`, `get_gig`, `list_gigs`, `cancel_gig` | Post a Gig |
| `list_engagements`, `get_engagement`, `hire_worker`, `end_engagement`, `send_engagement_message` | Manage Engagements |
| `list_pending_timesheets`, `get_timesheet`, `edit_timesheet`, `approve_timesheet`, `respond_to_dispute` | Timesheet Workflow |

---

## 8. Deterministic Guard / Mandates (`guard.py`)

Mirrors the TradierWrite mandate pattern: every write mutation passes through a typed guard before reaching the GraphQL client. The guard is **not** an opinion layer — it enforces deterministic constraints declared per method.

### 8.1 Guard contract

```python
class MutationMandate(BaseModel):
    operation: str                                # e.g. "post_gig"
    estimated_cost_cents: int = 0
    max_cost_cents: int = 100_000                 # $1,000 default cap, override per call
    requires_explicit_confirmation: bool = False
    confirmation_token: str | None = None
    idempotency_key: str = Field(default_factory=lambda: uuid4().hex)
    not_before: datetime | None = None            # for scheduled gigs

class DeterministicGuard:
    async def check(self, mandate: MutationMandate, payload: BaseModel) -> None: ...
    async def reconcile(
        self, mandate: MutationMandate, payload: BaseModel, result: BaseModel
    ) -> None: ...
```

### 8.2 Per-operation mandates

| Operation | Mandate |
|---|---|
| `post_gig` | `estimated_cost_cents` = pay_rate × workers_needed × duration_hours; rejects if exceeds `max_cost_cents`. Idempotency key required. |
| `hire_worker` | Idempotency key required. Duplicate-hire detection: refuses if engagement already in `HIRED+` state. |
| `cancel_gig` | Idempotency key required. Refuses if any engagement is `CLOCKED_IN`. |
| `edit_timesheet` | Computes delta vs current timesheet; if delta in either time or `additional_payment_cents` exceeds 25% of current values, requires `confirmation_token`. |
| `approve_timesheet` | If `final_total_minutes` supplied and disagrees with computed total by more than 1 minute, fails closed. |
| `respond_to_dispute` | Idempotency key required. |
| `end_engagement` | Refuses if engagement is `CLOCKED_IN` and no clock-out is forced first. |

### 8.3 Post-mutation reconciliation

After every write, `reconcile()` re-fetches the entity and asserts:
- The returned `id` matches the response from the mutation.
- For state transitions: the new state is in the expected set (e.g. after `cancel_gig`, state ∈ {`CANCELLED`}).
- For monetary fields: the recorded amount matches what was sent.

A reconciliation failure raises `GigSmartReconciliationError` and is logged at WARN with full diff.

---

## 9. Error Handling

### 9.1 GraphQL error classification table `[VERIFY codes]`

GigSmart's error `extensions.code` values must be enumerated from the docs. Mapping:

| `extensions.code` (expected) | Exception | Retryable |
|---|---|---|
| `UNAUTHENTICATED` | `GigSmartAuthError` | no |
| `FORBIDDEN` | `GigSmartAuthError` | no |
| `BAD_USER_INPUT` / `VALIDATION` | `GigSmartValidationError` | no |
| `NOT_FOUND` | `GigSmartNotFoundError` | no |
| `RATE_LIMITED` / `TOO_MANY_REQUESTS` | `GigSmartRateLimitError` | yes (with Retry-After) |
| `INTERNAL_SERVER_ERROR` | `GigSmartTransportError` | yes |
| `CONFLICT` / `IDEMPOTENCY_VIOLATION` | `GigSmartConflictError` | no |
| anything else | `GigSmartGraphQLError` | no |

### 9.2 Partial-success handling

GraphQL responses can return both `data` and `errors`. Policy:
- **Queries:** if `data` is non-null, return it and emit a WARN log with the errors. The caller can still proceed with degraded data.
- **Mutations:** if `errors` is non-empty, **always** raise — never return partial mutation results, even if `data` is populated.

---

## 10. Operational Concerns

### 10.1 Idempotency

…(truncated)…
