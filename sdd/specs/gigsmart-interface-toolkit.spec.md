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

### Existing Patterns to Follow

| Pattern | Source | What to replicate |
|---------|--------|-------------------|
| Interface module structure | `parrot_tools/interfaces/workday/` | `config.py`, `service.py`, `models/`, `handlers/` layout |
| Typed exception hierarchy | `parrot_tools/massive/client.py:16-35` | Base error + status code + subclasses |
| Retry with backoff | `parrot_tools/massive/client.py:49-68` | Exponential backoff, rate limit patterns |
| Toolkit with tool_prefix | `WorkingMemoryToolkit` (tool.py:77) | `tool_prefix = "gigsmart"` |
| confirming_tools | `AbstractToolkit` (toolkit.py:264-276) | frozenset of write method names |
| @tool_schema + frozen inputs | `WorkingMemoryToolkit.store()` | `@tool_schema(PydanticModel)` with `BaseModel, frozen=True` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.toolkit.WorkingMemoryToolkit`~~ — it's at `parrot.tools.working_memory.tool.WorkingMemoryToolkit`, NOT in toolkit.py
- ~~`DeterministicGuard`~~ — does not exist anywhere in the codebase; use `confirming_tools` instead
- ~~`MutationMandate`~~ — does not exist; the brainstorm SPEC invented this
- ~~`DataFrameHandle`~~ — does not exist as a class; WorkingMemory uses `store()` → returns dict summary
- ~~`parrot.tools.gigsmart`~~ — does not exist yet; must be created
- ~~`parrot_tools.interfaces.gigsmart`~~ — does not exist yet; must be created
- ~~`httpx`~~ — do NOT use httpx; CLAUDE.md mandates aiohttp
- ~~`GigSmartGraphQLClient`~~ — the brainstorm SPEC name; use `GigSmartClient` instead (consistent with `MassiveClient`)
- ~~`createLocation` mutation~~ — actual mutation is `addOrganizationLocation`
- ~~`createOrganizationPosition` mutation~~ — actual is `addOrganizationPosition`
- ~~`postGig` / `PostGigInput`~~ — actual mutation is `postShift` / `PostShiftInput`
- ~~`workers_needed` field~~ — actual field is `slotsAvailable`
- ~~`hireWorker` / `endEngagement` / `acceptEngagement` mutations~~ — ALL state transitions go through single `transitionEngagement(action: ...)` mutation
- ~~`editTimesheet` mutation~~ — does NOT exist; only `approveEngagementTimesheet` and `removeEngagementTimesheet`
- ~~`TimesheetState` enum~~ — does NOT exist; timesheet lifecycle tracked via `EngagementStateName` + `isApproved` boolean
- ~~Money as `{ amount, currency }` object~~ — Money is a plain ISO-4217 string scalar (e.g., `"20.00"`)
- ~~Simple `Authorization: Bearer <api_key>` auth~~ — actual auth is OAuth 2.1 token exchange
- ~~UUID or Relay base64 IDs~~ — IDs are prefixed opaque strings (e.g., `gig_9ucAiJ...`, `eng_0WjivX...`)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `AbstractToolkit` pattern — all public async methods auto-discovered as tools
- Follow async-first design throughout (aiohttp, not httpx or requests)
- Pydantic v2 models for all structured data; frozen inputs for mutations
- Comprehensive logging with `self.logger` (from AbstractToolkit.__init__)
- GraphQL documents as `.graphql` files loaded at import time (not inline strings)
- camelCase aliases on Pydantic models for GraphQL variable serialization

### OAuth 2.1 Implementation Notes

- **Client credentials** (server-to-server): send client_id + client_secret via HTTP Basic auth
  to `/oauth/token` with `grant_type=client_credentials`. Tokens expire in 15 minutes.
  Only `read:*` scopes available.
- **Auth code + PKCE** (user-facing): generate code_verifier + code_challenge (SHA-256,
  base64url), redirect to `/oauth/authorize`, exchange code at `/oauth/token`.
  Tokens expire in 1 hour. All scopes (read + write) available.
- **Token caching**: cache token in memory; proactively refresh when <2min remaining.
- **Scope enforcement**: raise `GigSmartAuthError` if a write operation is attempted with
  a client_credentials token (which only has read scopes).

### Available OAuth Scopes

| Scope | Description | Grant Types |
|---|---|---|
| `read:gigs` | View gig postings, shifts, scheduling | both |
| `read:engagements` | View engagement details and state transitions | both |
| `read:organizations` | View organization profiles and structure | both |
| `read:positions` | View organization positions and categories | both |
| `read:locations` | View organization locations and addresses | both |
| `write:gigs` | Create and modify gig postings | auth_code only |
| `write:engagements` | Modify engagement states (offer, cancel, etc.) | auth_code only |
| `write:organizations` | Manage organizations | auth_code only |
| `write:positions` | Create and manage positions | auth_code only |
| `write:locations` | Create and manage locations | auth_code only |
| `read:messages` | Read messages and conversations | auth_code only |
| `write:messages` | Send messages | auth_code only |

### GraphQL Error Classification

| `extensions.code` | Exception | Retryable |
|---|---|---|
| `UNAUTHENTICATED` | `GigSmartAuthError` | no |
| `FORBIDDEN` | `GigSmartAuthError` | no |
| `BAD_USER_INPUT` | `GigSmartValidationError` | no |
| `NOT_FOUND` | `GigSmartNotFoundError` | no |
| 429 / `RATE_LIMITED` | `GigSmartRateLimitError` | yes (with Retry-After) |
| 5xx / `INTERNAL_SERVER_ERROR` | `GigSmartTransportError` | yes |
| `CONFLICT` | `GigSmartConflictError` | no |
| anything else | `GigSmartGraphQLError` | no |

### Known Risks / Gotchas

- **Token expiry in long sessions**: client_credentials tokens expire in 15 minutes. Agent
  sessions running multi-step operations need proactive refresh. Mitigation: check expiry
  before every `execute()` call.
- **Write scopes require user OAuth flow**: headless agents cannot get write access without
  a pre-authorized refresh token. Mitigation: support pre-configured refresh tokens via
  `GIGSMART_REFRESH_TOKEN` env var.
- **Schema drift**: exact enum values may differ from what docs show. Mitigation: run
  introspection in Phase 1 and persist `schema.graphql`.
- **First GraphQL client**: no existing pattern to copy. Mitigation: keep client generic
  enough to be reusable for future GraphQL APIs.
- **Partial success on queries**: GraphQL can return both `data` and `errors`. Policy:
  queries return degraded data + WARN log; mutations always raise on any error.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | `>=3.9` | HTTP transport (already in project dependencies) |
| `pydantic` | `>=2.0` | Input/output validation (already in project) |

No new external dependencies required.

---

## 8. Open Questions

### Resolved (during proposal phase)

- [x] **OAuth grant types** — *Resolved in proposal*: Support both client_credentials (read-only) and auth_code+PKCE (full access)
- [x] **Module location** — *Resolved in proposal*: Interface at `parrot_tools/interfaces/gigsmart/`, toolkit at `parrot_tools/gigsmart/`
- [x] **MCP endpoint** — *Resolved in proposal*: Custom toolkit only; do not register native MCP endpoint
- [x] **API credentials** — *Resolved in proposal*: Available for development

### Resolved (via schema introspection)

- [x] **Exact timesheet mutation names** — *Resolved via introspection*: Only 2 mutations — `approveEngagementTimesheet` (approve) and `removeEngagementTimesheet` (reject/send back). No edit mutation exists. Disputes are separate: `addEngagementDispute` and `setEngagementDisputeApproval`.
- [x] **Exact enum values for states** — *Resolved via introspection*: GigStateName has 11 values (ACTIVE, CANCELED, COMPLETED, DRAFT, EXPIRED, IN_PROGRESS, INACTIVE, INCOMPLETE, PENDING_REVIEW, RECONCILED, UPCOMING). EngagementStateName has 32 values. EngagementStateAction has 48 values (HIRE, ACCEPT, START, END, CANCEL, APPROVE_TIMESHEET, etc.). No TimesheetState enum — tracked via EngagementStateName + isApproved boolean.
- [x] **Money type representation** — *Resolved via introspection*: Money is a custom scalar in ISO-4217 format, serialized as a plain decimal string (e.g., `"20.00"`). Not an object type.
- [x] **Position creation mutation name** — *Resolved via introspection*: `addOrganizationPosition` (not `createOrganizationPosition`).
- [x] **ID format** — *Resolved via introspection*: Prefixed opaque strings — type prefix + underscore + ~22-char base62 hash (e.g., `gig_9ucAiJfkccqJKbnVytgviu`, `eng_0WjivXE8xbrgBuEkfpANQP`, `engts_9fesLHHFy0By8MC6FvbYiv`).

### Additional Schema Discoveries

- [x] **Engagement transitions** — *Resolved via introspection*: `transitionEngagement` is a single mutation for ALL state changes via `action: EngagementStateAction`. There are NO separate hire/accept/end mutations. Key actions: HIRE, ACCEPT, START, END, CANCEL, APPROVE_TIMESHEET, OFFER, PAUSE, RESUME.
- [x] **Full mutation list** — *Resolved via introspection*: 27 mutations total. Key ones for toolkit: `addOrganizationLocation`, `addOrganizationPosition`, `postShift`, `transitionGig`, `addEngagement`, `transitionEngagement`, `approveEngagementTimesheet`, `removeEngagementTimesheet`, `addEngagementDispute`, `setEngagementDisputeApproval`, `addUserMessage`.
- [x] **Custom scalars** — *Resolved via introspection*: DateTime, Duration (ISO-8601), Money (ISO-4217 string), PhoneNumber (E.164), Json, EncodedPolyline, IpAddress.

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks run sequentially in one worktree)
- **Rationale**: modules have linear dependencies (exceptions → config → auth → models → client → toolkit)
- **Cross-feature dependencies**: none — this is greenfield
- **Recommended worktree name**: `feat-253-gigsmart-interface-toolkit`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-23 | Jesus Lara / Claude | Initial draft from research-grounded proposal FEAT-253 |
| 1.0 | 2026-06-23 | Jesus Lara / Claude | All open questions resolved via schema introspection (1270 types, 27 mutations). Status: approved. |
