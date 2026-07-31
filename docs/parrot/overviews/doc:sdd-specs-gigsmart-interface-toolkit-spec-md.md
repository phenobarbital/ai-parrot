---
type: Wiki Overview
title: 'Feature Specification: GigSmart Interface Toolkit'
id: doc:sdd-specs-gigsmart-interface-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot agents need to interact with the GigSmart Developer API to manage
  gig economy
relates_to:
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot.tools.working_memory.tool
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: GigSmart Interface Toolkit

**Feature ID**: FEAT-253
**Date**: 2026-06-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents need to interact with the GigSmart Developer API to manage gig economy
operations on behalf of requester/employer organizations. This includes posting shifts,
managing worker engagements, reviewing timesheets, and administering locations and positions.

GigSmart exposes a **GraphQL API** at `https://api.gigsmart.com/graphql` with **OAuth 2.1**
authentication. No GigSmart integration exists in the codebase today — this is entirely
greenfield. A prior brainstorm SPEC (`sdd/proposals/GigSmartToolkit_SPEC.md`) proposed an
architecture, but research uncovered 8 incorrect assumptions that this spec corrects
(documented in `sdd/proposals/gigsmart-interface-toolkit.proposal.md` §8).

### Goals

- Provide an aiohttp-based GraphQL client for the GigSmart API with OAuth 2.1 token lifecycle
- Expose 6 functional surfaces as typed async tool methods via a `GigSmartToolkit`
- Validate all inputs/outputs with Pydantic v2 models matching the actual API schema
- Gate write mutations with `confirming_tools` for human-in-the-loop safety
- Integrate with `WorkingMemoryToolkit` for large result set spilling to DataFrames
- Follow existing codebase patterns (`AbstractToolkit`, `@tool_schema`, typed exceptions)

### Non-Goals (explicitly out of scope)

- Webhooks / event subscriptions (follow-up feature)
- Worker-side mutations (toolkit is requester/employer-side only)
- GigSmart's native MCP endpoint (`requester-mcp.prod.gigsmart.com/mcp`) — custom toolkit only
- Onfleet integration plumbing (position attribute only, not a separate client)
- Payment dispute initiation by worker (only requester-side response)
- Gig Series advanced flow (only `postShift` quick-start in initial release)

---

## 2. Architectural Design

### Overview

Two-layer architecture following the established `interfaces/` + toolkit pattern
(same as Workday):

1. **Interface layer** (`parrot_tools/interfaces/gigsmart/`) — aiohttp-based GraphQL
   transport with OAuth 2.1 token lifecycle, typed exceptions, and retry logic.
   This is the API client, independent of LLM tooling concerns.

2. **Toolkit layer** (`parrot_tools/gigsmart/`) — `GigSmartToolkit(AbstractToolkit)`
   exposing tool methods decorated with `@tool_schema` for each API surface.
   Write mutations are gated via `confirming_tools`. Large result sets spill to
   WorkingMemory DataFrames.

### Component Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│  Agent (LLM) — tool calls                                         │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  GigSmartToolkit  (extends AbstractToolkit)                        │
│   • tool_prefix = "gigsmart"                                      │
│   • confirming_tools = frozenset({write mutations})               │
│   • @tool_schema methods → Pydantic-validated args/returns         │
│   • Large list results → WorkingMemory DataFrames via store()     │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  GigSmartClient  (interface / transport)                           │
│   • aiohttp.ClientSession + retry/backoff                         │
│   • OAuth 2.1 token lifecycle (client_credentials + auth_code)    │
│   • GraphQL execute() with error classification                   │
│   • Auth header injection via build_headers()                     │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    https://api.gigsmart.com/graphql
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for GigSmartToolkit; provides tool auto-discovery, `confirming_tools`, lifecycle hooks |
| `@tool_schema` decorator | uses | Pydantic input validation on each tool method |
| `WorkingMemoryToolkit` | composes | Spill large result sets (>50 items) to DataFrames via `store()` |
| `aiohttp.ClientSession` | uses | HTTP transport per CLAUDE.md mandate |
| `ToolManager.register_toolkit()` | registration | How the toolkit gets wired into an agent |

### Data Models

#### OAuth Token

```python
class OAuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    scope: str
    expires_at: datetime  # computed: now + expires_in
```

#### Relay Connection (generic pagination)

```python
class RelayPageInfo(BaseModel):
    has_next_page: bool
    end_cursor: str | None = None

class RelayEdge(BaseModel, Generic[T]):
    node: T
    cursor: str | None = None

class RelayConnection(BaseModel, Generic[T]):
    edges: list[RelayEdge[T]]
    page_info: RelayPageInfo
```

#### Location

```python
class PlaceResult(BaseModel):
    label: str
    place_id: str
    place_provider: str

class AddOrganizationLocationInput(BaseModel, frozen=True):
    organization_id: str
    name: str = Field(min_length=1, max_length=120)
    place_id: str | None = None
    address: str | None = None
    primary_contact_id: str | None = None
    payment_method_id: str | None = None
    arrival_instructions: str | None = None
    location_instructions: str | None = None

class OrganizationLocation(BaseModel):
    id: str
    name: str
    state: str
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime | None = None
```

#### Position

```python
class AddOrganizationPositionInput(BaseModel, frozen=True):
    organization_id: str
    name: str | None = None
    description: str | None = None
    pay_rate: str | None = None  # Money scalar — ISO-4217 string e.g. "20.00"
    pay_schedule: Literal["FIXED", "HOURLY", "INFO_REQUIRED"] | None = None
    gig_category_id: str | None = None
    gig_position_id: str | None = None
    state: str | None = None  # OrganizationPositionState
    accepts_tips: bool | None = None
    requires_vehicle: bool | None = None
    estimated_mileage: float | None = None

class Position(BaseModel):
    id: str  # prefixed opaque ID, e.g. "pos_..."
    name: str | None = None
    description: str | None = None
    pay_rate: str | None = None  # Money scalar
    created_at: datetime | None = None
```

#### Gig / Shift

```python
class PostShiftInput(BaseModel, frozen=True):
    organization_id: str
    organization_position_id: str
    organization_location_id: str
    starts_at: datetime
    ends_at: datetime
    pay_rate: str | None = None  # Money scalar — defaults to position rate
    slots_available: int = Field(default=1, ge=1)
    description: str | None = Field(default=None, max_length=5000)
    requester_id: str | None = None

class TransitionGigInput(BaseModel, frozen=True):
    gig_id: str
    action: Literal["CANCEL", "CLOSE", "MARK_AS_COMPLETE", "PUBLISH"]

# GigStateName enum: ACTIVE, CANCELED, COMPLETED, DRAFT, EXPIRED,
#   IN_PROGRESS, INACTIVE, INCOMPLETE, PENDING_REVIEW, RECONCILED, UPCOMING
class Gig(BaseModel):
    id: str  # prefixed opaque ID, e.g. "gig_9ucAiJfkccqJKbnVytgviu"
    name: str | None = None
    starts_at: datetime
    ends_at: datetime
    current_state: dict  # { "name": "<GigStateName>" }
    slots_available: int | None = None
```

#### Engagement

```python
class AddEngagementInput(BaseModel, frozen=True):
    gig_id: str
    worker_id: str | None = None
    initial_state: Literal["OFFERED", "BID_REQUESTED", "SCHEDULED"] | None = None
    pay_rate: str | None = None  # Money scalar
    pay_schedule: Literal["FIXED", "HOURLY", "INFO_REQUIRED"] | None = None
    note: str | None = None
    cancel_conflicting_engagements: bool | None = None

class TransitionEngagementInput(BaseModel, frozen=True):
    """Single mutation for ALL engagement state transitions."""
    engagement_id: str
    action: str  # EngagementStateAction — e.g. "HIRE", "ACCEPT", "START", "END", "CANCEL"
    cancel_conflicting_engagements: bool | None = None

# EngagementStateName enum (32 values): APPLIED, OFFERED, SCHEDULED,
#   AWAITING_START, CONFIRMING, EN_ROUTE, WORKING, PAUSED, ENDED,
#   PENDING_REVIEW, PENDING_TIMESHEET_APPROVAL, DISBURSED, CANCELED, ...
class Engagement(BaseModel):
    id: str  # prefixed opaque ID, e.g. "eng_0WjivXE8xbrgBuEkfpANQP"
    gig_id: str | None = None
    worker_display_name: str | None = None
    current_state: dict  # { "name": "<EngagementStateName>" }
    applied_at: datetime | None = None
    hired_at: datetime | None = None
```

#### Timesheet

```python
# No TimesheetState enum — lifecycle tracked via EngagementStateName
# (PENDING_TIMESHEET_APPROVAL, DISBURSED) + isApproved boolean on EngagementTimesheet.
# Variants: ADMIN, FINAL, LATEST, REQUESTER, SYSTEM, WORKER
# Payment styles: CALCULATED, FIXED_AMOUNT, FIXED_HOURS
class EngagementTimesheet(BaseModel):
    id: str  # prefixed opaque ID, e.g. "engts_9fesLHHFy0By8MC6FvbYiv"
    engagement_id: str | None = None
    is_approved: bool = False
    variant: str | None = None  # EngagementTimesheetVariant
    payment_style: str | None = None  # EngagementTimesheetPaymentStyle

class ApproveEngagementTimesheetInput(BaseModel, frozen=True):
    timesheet_id: str
    mutation_lock: str | None = None  # optimistic concurrency

class RemoveEngagementTimesheetInput(BaseModel, frozen=True):
    """Reject/send back — worker can resubmit."""
    timesheet_id: str

# Disputes are separate from timesheets:
class AddEngagementDisputeInput(BaseModel, frozen=True):
    engagement_id: str
    # exact fields TBD from schema — dispute reason, notes

class SetEngagementDisputeApprovalInput(BaseModel, frozen=True):
    dispute_id: str
    accept: bool
    response_note: str | None = None
```

> **Note**: Models above are derived from the introspected schema (1270 types, 27 mutations).
> IDs are prefixed opaque strings (e.g., `gig_9ucAiJfk...`, `eng_0WjivXE8...`).
> Money is an ISO-4217 string scalar (e.g., `"20.00"`), not an object.
> Phase 1 should still persist the full introspected schema as `schema.graphql` for diff tracking.

### New Public Interfaces

```python
# parrot_tools/interfaces/gigsmart/client.py
class GigSmartClient:
    def __init__(self, config: GigSmartConfig) -> None: ...
    async def execute(self, document: str, variables: dict | None = None,
                      *, operation_name: str | None = None) -> dict: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> "GigSmartClient": ...
    async def __aexit__(self, *exc_info) -> None: ...

# parrot_tools/interfaces/gigsmart/auth.py
class GigSmartAuth:
    async def get_token(self, scopes: list[str] | None = None) -> str: ...
    async def refresh_token(self) -> str: ...
    def build_headers(self) -> dict[str, str]: ...

# parrot_tools/gigsmart/toolkit.py
class GigSmartToolkit(AbstractToolkit):
    tool_prefix: str = "gigsmart"
    confirming_tools: frozenset[str] = frozenset({
        "post_shift", "transition_gig", "add_engagement",
        "transition_engagement", "approve_timesheet",
        "remove_timesheet", "add_dispute", "resolve_dispute",
        "create_location", "create_position",
    })
```

---

## 3. Module Breakdown

### Module 1: Exceptions
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/exceptions.py`
- **Responsibility**: Typed exception hierarchy for GigSmart API errors
- **Depends on**: none

Classes: `GigSmartError` (base), `GigSmartAuthError`, `GigSmartValidationError`,
`GigSmartRateLimitError`, `GigSmartNotFoundError`, `GigSmartTransportError`,
`GigSmartGraphQLError`, `GigSmartConflictError`.
Follow `MassiveAPIError` pattern from `parrot_tools/massive/client.py:16-35`.

### Module 2: Configuration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/config.py`
- **Responsibility**: `GigSmartConfig` dataclass loading credentials from env vars
- **Depends on**: Module 1

Config fields: `client_id`, `client_secret`, `environment` (production/sandbox),
`endpoint_url`, `request_timeout`, `max_concurrent_requests`.
Load from `GIGSMART_CLIENT_ID`, `GIGSMART_CLIENT_SECRET`, `GIGSMART_ENV` env vars.

### Module 3: OAuth Authentication
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/auth.py`
- **Responsibility**: OAuth 2.1 token lifecycle — client_credentials + auth_code+PKCE grants
- **Depends on**: Module 2

Token endpoint: `https://api.gigsmart.com/oauth/token`.
Authorization endpoint: `https://api.gigsmart.com/oauth/authorize`.
Handles: token acquisition, caching, proactive refresh (re-auth when <2min remaining),
scope validation (write scopes only via auth_code grant).

### Module 4: Pydantic Models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/models/`
- **Responsibility**: All input/output models for the 6 API surfaces + Relay pagination generics
- **Depends on**: none (pure data models)

Submodules: `common.py` (RelayConnection, PageInfo, Money), `auth.py` (OAuthToken, AuthStatus),
`location.py`, `position.py`, `gig.py`, `engagement.py`, `timesheet.py`.
All input models are `frozen=True`. Field names use `alias` for camelCase GraphQL mapping.

### Module 5: GraphQL Documents
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/queries/`
- **Responsibility**: Raw GraphQL query/mutation documents as `.graphql` files
- **Depends on**: none

Files: `viewer.graphql`, `locations.graphql`, `positions.graphql`, `gigs.graphql`,
`engagements.graphql`, `timesheets.graphql`. Loaded at import time as Python strings.

### Module 6: GraphQL Client
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/client.py`
- **Responsibility**: aiohttp-based GraphQL transport with retry, error classification, logging
- **Depends on**: Modules 1, 2, 3, 4

Core method: `async execute(document, variables, operation_name) -> dict`.
Retry policy: exponential backoff on 5xx/network errors (3 attempts, base 0.5s, cap 8s).
Rate limit handling: respect `X-RateLimit-*` headers and `Retry-After` on 429.
Error classification: extract `errors[].extensions.code` and map to typed exceptions.
Partial success: queries return degraded data + WARN log; mutations always raise on errors.

### Module 7: GigSmartToolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gigsmart/toolkit.py`
- **Responsibility**: `AbstractToolkit` subclass exposing all API surfaces as LLM tools
- **Depends on**: Modules 1-6

Tool methods (all `@tool_schema` decorated, all `async`):

| Method | GraphQL operation | Category |
|--------|-------------------|----------|
| `verify_auth` | `query { viewer { ... } }` | auth |
| `search_address` | `placeAutocomplete` | locations |
| `create_location` | `addOrganizationLocation` | locations |
| `list_locations` | `organization { locations(...) }` | locations |
| `get_location` | `node(id: ...)` | locations |
| `create_position` | `addOrganizationPosition` | positions |
| `list_positions` | `organization { positions(...) }` | positions |
| `get_position` | `node(id: ...)` | positions |
| `post_shift` | `postShift` | gigs |
| `list_gigs` | `organization { gigs(...) }` | gigs |
| `get_gig` | `node(id: ...)` | gigs |
| `transition_gig` | `transitionGig(action: CANCEL\|CLOSE\|PUBLISH\|MARK_AS_COMPLETE)` | gigs |
| `add_engagement` | `addEngagement` | engagements |
| `list_engagements` | `gig { engagements(...) }` | engagements |
| `get_engagement` | `node(id: ...)` | engagements |
| `transition_engagement` | `transitionEngagement(action: HIRE\|ACCEPT\|START\|END\|CANCEL\|...)` | engagements |
| `send_message` | `addUserMessage` | messages |
| `list_timesheets` | engagement timesheet query | timesheets |
| `get_timesheet` | `node(id: ...)` | timesheets |
| `approve_timesheet` | `approveEngagementTimesheet` | timesheets |
| `remove_timesheet` | `removeEngagementTimesheet` | timesheets |
| `add_dispute` | `addEngagementDispute` | disputes |
| `resolve_dispute` | `setEngagementDisputeApproval` | disputes |

### Module 8: Package Init & Registration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gigsmart/__init__.py` and `interfaces/gigsmart/__init__.py`
- **Responsibility**: Package exports and optional toolkit registry entry
- **Depends on**: Modules 1-7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_from_env` | Module 2 | GigSmartConfig loads from env vars correctly |
| `test_config_missing_required` | Module 2 | Raises on missing client_id/client_secret |
| `test_exception_hierarchy` | Module 1 | All exceptions inherit GigSmartError; status codes attached |
| `test_oauth_token_model` | Module 4 | OAuthToken parses API response, computes expires_at |
| `test_relay_connection_generic` | Module 4 | RelayConnection[Location] parses edges/node |
| `test_frozen_input_immutability` | Module 4 | Frozen input models reject attribute assignment |
| `test_camelcase_aliases` | Module 4 | Models serialize to camelCase for GraphQL variables |
| `test_post_shift_input_validation` | Module 4 | Rejects starts_at > ends_at, slots_available < 1 |
| `test_graphql_document_loading` | Module 5 | All .graphql files load as non-empty strings |
| `test_error_classification` | Module 6 | Maps GraphQL error codes to typed exceptions |
| `test_retry_on_5xx` | Module 6 | Retries 5xx with backoff, gives up after max_retries |
| `test_no_retry_non_idempotent` | Module 6 | Non-idempotent mutations are not retried |
| `test_rate_limit_429` | Module 6 | Respects Retry-After header on 429 |
| `test_partial_success_query` | Module 6 | Returns data + warns on query with partial errors |
| `test_partial_success_mutation` | Module 6 | Raises on mutation with any errors |

### Integration Tests (sandbox)

| Test | Description |
|---|---|
| `test_verify_auth_sandbox` | Runs viewer query, asserts org identity returned |
| `test_place_autocomplete` | Searches for an address, gets placeId back |
| `test_create_and_get_location` | Creates location, retrieves by ID, verifies fields match |
| `test_post_and_cancel_shift` | Posts a shift, verifies UPCOMING state, cancels it |
| `test_list_gigs_pagination` | Lists gigs with cursor pagination, verifies RelayConnection shape |

> Integration tests gated by `GIGSMART_CLIENT_ID` + `GIGSMART_CLIENT_SECRET` env vars; skipped otherwise.

### Test Data / Fixtures

```python
@pytest.fixture
def gigsmart_config():
    return GigSmartConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        environment="sandbox",
    )

@pytest.fixture
def mock_graphql_response():
    return {
        "data": {
            "viewer": {
                "__typename": "OrganizationRequester",
                "id": "org-123",
                "organization": {"name": "Test Org"}
            }
        }
    }

@pytest.fixture
def mock_graphql_error():
    return {
        "errors": [{"message": "Not found", "extensions": {"code": "NOT_FOUND"}}],
        "data": None
    }
```

---

## 5. Acceptance Criteria

- [ ] GigSmartClient connects to sandbox and executes viewer query successfully
- [ ] OAuth token acquisition works for both grant types (client_credentials and auth_code+PKCE)
- [ ] OAuth tokens auto-refresh before expiry (proactive renewal when <2min remaining)
- [ ] All 23 toolkit methods are discoverable via `GigSmartToolkit.get_tools()`
- [ ] Write mutations (post_shift, transition_engagement, etc.) require HITL confirmation via `confirming_tools`
- [ ] GraphQL errors are classified into typed exceptions matching error code table
- [ ] Retry logic activates on 5xx and 429, with exponential backoff and Retry-After
- [ ] Relay connection pagination (edges/node) works for all list methods
- [ ] Large result sets (>50 items) auto-spill to WorkingMemory DataFrames
- [ ] All Pydantic input models are frozen (immutable) and serialize to camelCase
- [ ] PII (worker names, addresses) never appears in logs unless `GIGSMART_LOG_PII=1`
- [ ] All unit tests pass: `pytest tests/tools/gigsmart/ -v`
- [ ] Integration tests pass against sandbox when credentials are provided
- [ ] No breaking changes to existing public API
- [ ] Introspected schema persisted as `schema.graphql` for diff tracking

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.tools.decorators import tool_schema  # verified: packages/ai-parrot/src/parrot/tools/decorators.py:37
from parrot.tools.decorators import requires_permission  # verified: packages/ai-parrot/src/parrot/tools/decorators.py:9
from parrot.tools.working_memory.tool import WorkingMemoryToolkit  # verified: packages/ai-parrot/src/parrot/tools/working_memory/tool.py:43
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # line 207
    input_class: Optional[Type[BaseModel]] = None  # line 235
    return_direct: bool = False  # line 236
    exclude_tools: tuple[str, ...] = ()  # line 244
    tool_prefix: Optional[str] = None  # line 258
    prefix_separator: str = "_"  # line 261
    confirming_tools: frozenset = frozenset()  # line 276
    def __init__(self, **kwargs): ...  # line 278
    async def start(self) -> None: ...  # line 316
    async def stop(self) -> None: ...  # line 323
    async def cleanup(self) -> None: ...  # line 330
    async def _prepare_kwargs(self, tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]: ...  # line 337
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...  # line 354
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...  # line 369
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...  # line 385

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):  # line 37
    # Sets func._args_schema = schema and func._tool_description

def requires_permission(*permissions: str):  # line 9
    # Sets obj._required_permissions = frozenset(permissions)

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):  # line 43
    name: str = "working_memory"  # line 76
    tool_prefix: str = "wm"  # line 77
    async def store(self, key: str, df: pd.DataFrame, description: str = "", turn_id=None) -> dict: ...  # line 127

# packages/ai-parrot-tools/src/parrot_tools/massive/client.py
class MassiveAPIError(Exception):  # line 16
    def __init__(self, message: str, status_code: int | None = None): ...  # line 19
class MassiveRateLimitError(MassiveAPIError):  # line 25
    def __init__(self, message: str, retry_after: int | None = None): ...  # line 28
class MassiveTransientError(MassiveAPIError):  # line 33
    pass
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GigSmartToolkit` | `AbstractToolkit` | inheritance | `toolkit.py:207` |
| `GigSmartToolkit` methods | `@tool_schema` | decorator | `decorators.py:37` |
| `GigSmartToolkit` | `WorkingMemoryToolkit.store()` | method call (compose) | `working_memory/tool.py:127` |
| `GigSmartToolkit` | `ToolManager.register_toolkit()` | registration | `tools/manager.py:678` |
| `GigSmartClient` | `aiohttp.ClientSession` | HTTP transport | external package |

…(truncated)…
