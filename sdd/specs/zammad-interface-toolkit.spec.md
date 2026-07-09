---
type: feature
base_branch: dev
---

# Feature Specification: Zammad Interface & Toolkit

**Feature ID**: FEAT-218
**Date**: 2026-07-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents need to interact with Zammad helpdesk servers for ticket
management, user administration, and article/attachment retrieval. The existing
`ZammadBackend` in `parrot/human/actions/backends/zammad.py` is a
single-purpose HITL escalation backend that only creates tickets — it cannot
list, search, update, or close tickets, manage users, retrieve articles, or
fetch attachments.

The navigator project (`navigator/actions/zammad.py`) already has a Zammad
integration, but it is tightly coupled to the navigator framework (inherits
`AbstractTicket` + `RESTAction`). AI-Parrot needs its own async-first,
self-contained interface following the `OdooInterface` pattern, plus an
`AbstractToolkit` subclass so LLMs can interact with Zammad servers through
tool calls.

A critical requirement is "On Behalf Of" support — the ability to perform API
operations as a specific user (by ID, login, or email) using the Zammad `From`
HTTP header. This enables agents to create/update tickets attributed to the
actual end-user rather than the API service account.

### Goals

- Provide a reusable `ZammadInterface` async HTTP client for Zammad REST API v1
- Support all core Zammad operations: tickets (CRUD + search), users (CRUD +
  search), articles (list by ticket), attachments (download)
- Implement "On Behalf Of" via the `From` header for all requests
- Create a `ZammadToolkit` extending `AbstractToolkit` so LLMs can use Zammad
  as tools
- Support Bearer token authentication (OAuth2 / API token)
- Read configuration from environment variables via `parrot.conf`

### Non-Goals (explicitly out of scope)

- WebSocket/real-time Zammad integrations (push notifications, live chat)
- Zammad webhook receiver endpoints
- Knowledge Base API endpoints (can be added later)
- OAuth2 authorization code flow (only pre-existing tokens)
- Replacing the existing `ZammadBackend` in HITL — that backend will remain
  for its narrow escalation purpose; consumers who need richer Zammad access
  will use `ZammadInterface` directly

---

## 2. Architectural Design

### Overview

Two new modules following established AI-Parrot patterns:

1. **`ZammadInterface`** — async HTTP client in `parrot/interfaces/zammad.py`,
   modeled after `OdooInterface`. Uses `aiohttp.ClientSession` for all HTTP
   calls. Manages authentication headers, the `From` header for on-behalf-of
   operations, response parsing, pagination, and error handling. Supports async
   context manager (`async with`) for session lifecycle.

2. **`ZammadToolkit`** — in `parrot_tools/zammad.py`, extends
   `AbstractToolkit`. Wraps `ZammadInterface` methods as public async methods
   that auto-register as LLM tools. Uses `@tool_schema` decorators with
   Pydantic input models for structured argument schemas.

### Component Diagram

```
┌─────────────────────┐     ┌─────────────────────────┐
│    LLM / Agent      │     │   Direct Python caller   │
└────────┬────────────┘     └────────────┬────────────┘
         │ tool call                     │ await
         ▼                               ▼
┌─────────────────────┐     ┌─────────────────────────┐
│   ZammadToolkit     │────▶│    ZammadInterface       │
│ (AbstractToolkit)   │     │  (aiohttp client)        │
│                     │     │                          │
│ • create_ticket()   │     │ • _request(method, path) │
│ • get_ticket()      │     │ • list_tickets()         │
│ • list_tickets()    │     │ • get_ticket(id)         │
│ • update_ticket()   │     │ • create_ticket(...)     │
│ • search_tickets()  │     │ • update_ticket(...)     │
│ • close_ticket()    │     │ • delete_ticket(id)      │
│ • get_user()        │     │ • search_tickets(query)  │
│ • search_users()    │     │ • get_user(id)           │
│ • create_user()     │     │ • search_users(query)    │
│ • get_articles()    │     │ • create_user(...)       │
│ • get_attachment()  │     │ • get_articles(ticket)   │
│                     │     │ • get_attachment(...)     │
└─────────────────────┘     └────────────┬────────────┘
                                         │ aiohttp
                                         ▼
                            ┌─────────────────────────┐
                            │  Zammad REST API v1      │
                            │  (external server)       │
                            └─────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/interfaces/` package | new module | `zammad.py` follows `OdooInterface` pattern |
| `parrot/conf.py` | extends | Add `ZAMMAD_*` env var declarations |
| `parrot_tools/` package | new module | `zammad.py` follows `JiraToolkit` pattern |
| `parrot_tools.TOOL_REGISTRY` | extends | Register `"zammad": "parrot_tools.zammad.ZammadToolkit"` |
| `AbstractToolkit` | extends | `ZammadToolkit` inherits from it |
| `@tool_schema` decorator | uses | Pydantic input models for each tool method |
| `ZammadBackend` (HITL) | coexists | Not modified; separate concern |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ZammadConfig(BaseModel):
    """Configuration for Zammad API connection."""
    instance_url: str = Field(..., description="Zammad instance base URL")
    token: str = Field(..., description="API token for authentication")
    default_customer: Optional[str] = Field(default=None, description="Default customer email")
    default_group: Optional[str] = Field(default=None, description="Default ticket group")
    default_catalog: Optional[str] = Field(default=None, description="Default service catalog")
    organization: Optional[str] = Field(default=None, description="Default organization")
    default_role: str = Field(default="Customer", description="Default role for new users")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class TicketCreatePayload(BaseModel):
    """Payload for creating a Zammad ticket."""
    title: str = Field(..., description="Ticket title")
    group: str = Field(..., description="Ticket group/queue")
    customer: str = Field(..., description="Customer email or ID")
    article_subject: Optional[str] = Field(default=None, description="Article subject")
    article_body: str = Field(..., description="Article body text")
    article_type: str = Field(default="note", description="Article type")
    article_internal: bool = Field(default=False, description="Internal note flag")
    priority_id: Optional[int] = Field(default=None, description="Priority ID")
    state_id: Optional[int] = Field(default=None, description="State ID")
    on_behalf_of: Optional[str] = Field(default=None, description="User ID/login/email for From header")


class TicketUpdatePayload(BaseModel):
    """Payload for updating a Zammad ticket."""
    ticket_id: int = Field(..., description="Ticket ID to update")
    title: Optional[str] = Field(default=None, description="New title")
    group: Optional[str] = Field(default=None, description="New group")
    state_id: Optional[int] = Field(default=None, description="New state ID")
    priority_id: Optional[int] = Field(default=None, description="New priority ID")
    article_body: Optional[str] = Field(default=None, description="Article body for the update")
    article_type: str = Field(default="note", description="Article type")
    article_internal: bool = Field(default=True, description="Internal note flag")
    on_behalf_of: Optional[str] = Field(default=None, description="User ID/login/email for From header")


class UserCreatePayload(BaseModel):
    """Payload for creating a Zammad user."""
    firstname: str = Field(..., description="First name")
    lastname: str = Field(..., description="Last name")
    email: str = Field(..., description="Email address")
    organization: Optional[str] = Field(default=None, description="Organization name")
    roles: List[str] = Field(default_factory=lambda: ["Customer"], description="Roles")
    active: bool = Field(default=True, description="Active flag")
```

### New Public Interfaces

```python
class ZammadInterface:
    """Async interface for Zammad REST API v1."""

    def __init__(
        self,
        instance_url: str | None = None,
        token: str | None = None,
        default_customer: str | None = None,
        default_group: str | None = None,
        default_catalog: str | None = None,
        organization: str | None = None,
        default_role: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
    ) -> None: ...

    async def __aenter__(self) -> "ZammadInterface": ...
    async def __aexit__(self, *args) -> None: ...
    async def close(self) -> None: ...

    # Core HTTP method
    async def _request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
        on_behalf_of: str | None = None,
    ) -> dict | list: ...

    # Ticket operations
    async def list_tickets(
        self, state_ids: list[int] | None = None, page: int = 1, per_page: int = 100
    ) -> dict[str, Any]: ...
    async def get_ticket(self, ticket_id: int, expand: bool = False) -> dict[str, Any]: ...
    async def create_ticket(self, payload: TicketCreatePayload) -> dict[str, Any]: ...
    async def update_ticket(self, payload: TicketUpdatePayload) -> dict[str, Any]: ...
    async def delete_ticket(self, ticket_id: int) -> None: ...
    async def search_tickets(self, query: str, page: int = 1, per_page: int = 100) -> dict[str, Any]: ...

    # User operations
    async def get_user(self, user_id: int, expand: bool = False) -> dict[str, Any]: ...
    async def get_current_user(self) -> dict[str, Any]: ...
    async def search_users(self, query: str) -> list[dict[str, Any]]: ...
    async def create_user(self, payload: UserCreatePayload) -> dict[str, Any]: ...
    async def update_user(self, user_id: int, data: dict) -> dict[str, Any]: ...

    # Article & attachment operations
    async def get_articles(self, ticket_id: int) -> list[dict[str, Any]]: ...
    async def get_attachment(self, ticket_id: int, article_id: int, attachment_id: int) -> bytes: ...


class ZammadToolkit(AbstractToolkit):
    """LLM-facing toolkit for Zammad operations."""
    tool_prefix = "zammad"

    def __init__(
        self,
        instance_url: str | None = None,
        token: str | None = None,
        default_customer: str | None = None,
        default_group: str | None = None,
        **kwargs,
    ) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    # Each public async method becomes an LLM tool
    async def create_ticket(self, ...) -> dict: ...
    async def get_ticket(self, ticket_id: int) -> dict: ...
    async def list_tickets(self, ...) -> dict: ...
    async def update_ticket(self, ...) -> dict: ...
    async def close_ticket(self, ticket_id: int) -> dict: ...
    async def search_tickets(self, query: str) -> dict: ...
    async def get_user(self, user_id: int) -> dict: ...
    async def search_users(self, query: str) -> list: ...
    async def create_user(self, ...) -> dict: ...
    async def get_articles(self, ticket_id: int) -> list: ...
    async def get_attachment(self, ticket_id: int, article_id: int, attachment_id: int) -> dict: ...
```

---

## 3. Module Breakdown

### Module 1: Configuration

- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Add `ZAMMAD_*` environment variable declarations
- **Depends on**: none (existing file, append only)

Variables to add:
```python
ZAMMAD_INSTANCE = config.get("ZAMMAD_INSTANCE", fallback=None)
ZAMMAD_TOKEN = config.get("ZAMMAD_TOKEN", fallback=None)
ZAMMAD_DEFAULT_CUSTOMER = config.get("ZAMMAD_DEFAULT_CUSTOMER", fallback=None)
ZAMMAD_DEFAULT_GROUP = config.get("ZAMMAD_DEFAULT_GROUP", fallback=None)
ZAMMAD_DEFAULT_CATALOG = config.get("ZAMMAD_DEFAULT_CATALOG", fallback=None)
ZAMMAD_ORGANIZATION = config.get("ZAMMAD_ORGANIZATION", fallback=None)
ZAMMAD_DEFAULT_ROLE = config.get("ZAMMAD_DEFAULT_ROLE", fallback="Customer")
```

### Module 2: ZammadInterface

- **Path**: `packages/ai-parrot/src/parrot/interfaces/zammad.py`
- **Responsibility**: Async HTTP client wrapping the Zammad REST API v1.
  Handles authentication (Bearer token), the `From` header for on-behalf-of
  operations, pagination, response parsing, and error handling.
- **Depends on**: Module 1 (conf vars), `aiohttp`

Key implementation details:
- Uses `aiohttp.ClientSession` with persistent session (created in
  `__aenter__` or lazily on first request)
- All responses parsed as JSON; non-2xx status raises `ZammadError`
- `From` header injected when `on_behalf_of` parameter is provided
- Default headers: `Authorization: Bearer {token}`,
  `Content-Type: application/json`
- Supports `?expand=true` query parameter for enriched responses
- Pagination via `page` + `per_page` (Zammad calls it `limit`)

### Module 3: ZammadToolkit

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/zammad.py`
- **Responsibility**: `AbstractToolkit` subclass exposing `ZammadInterface`
  methods as LLM tools. Each public async method has a Pydantic `@tool_schema`
  for argument validation.
- **Depends on**: Module 2, `AbstractToolkit`, `@tool_schema`

Key implementation details:
- Creates `ZammadInterface` in `start()`, closes in `stop()`
- `tool_prefix = "zammad"` so tools are named `zammad_create_ticket`, etc.
- Constructor accepts Zammad credentials directly or falls back to env vars
- Each method docstring becomes the LLM tool description
- Uses `on_behalf_of` parameter where applicable, allowing the LLM to
  specify which user to act as

### Module 4: Registry & Exports

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**: Register `ZammadToolkit` in `TOOL_REGISTRY`
- **Depends on**: Module 3

### Module 5: Tests

- **Path**: `packages/ai-parrot/tests/interfaces/test_zammad.py` and
  `packages/ai-parrot-tools/tests/test_zammad_toolkit.py`
- **Responsibility**: Unit tests for `ZammadInterface` and `ZammadToolkit`
- **Depends on**: Modules 2 and 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_zammad_interface_init_from_env` | Module 2 | Config loads from env vars |
| `test_zammad_interface_init_from_kwargs` | Module 2 | Config loads from explicit kwargs |
| `test_zammad_interface_context_manager` | Module 2 | Session created/closed properly |
| `test_zammad_request_auth_header` | Module 2 | Bearer token in Authorization header |
| `test_zammad_request_on_behalf_of` | Module 2 | `From` header set when `on_behalf_of` provided |
| `test_zammad_request_no_on_behalf_of` | Module 2 | No `From` header when `on_behalf_of` is None |
| `test_create_ticket_payload` | Module 2 | Correct JSON payload structure |
| `test_create_ticket_with_attachments` | Module 2 | Attachment data encoded and sent |
| `test_update_ticket` | Module 2 | PUT request with correct payload |
| `test_get_ticket` | Module 2 | GET request returns ticket dict |
| `test_search_tickets_pagination` | Module 2 | Multi-page search aggregates results |
| `test_list_tickets_state_filter` | Module 2 | State IDs encoded in query |
| `test_get_articles` | Module 2 | Articles list returned for ticket |
| `test_get_attachment_binary` | Module 2 | Binary attachment data returned |
| `test_create_user` | Module 2 | User creation payload correct |
| `test_search_users` | Module 2 | User search query correct |
| `test_error_handling_4xx` | Module 2 | Non-2xx raises `ZammadError` |
| `test_error_handling_network` | Module 2 | Connection error raises `ZammadConnectionError` |
| `test_toolkit_tools_registered` | Module 3 | All expected tools appear in `get_tools()` |
| `test_toolkit_tool_prefix` | Module 3 | Tool names start with `zammad_` |
| `test_toolkit_start_stop` | Module 3 | Interface created/closed via lifecycle |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_create_and_get_ticket` | Full round-trip: create then retrieve (requires live Zammad) |
| `test_toolkit_on_behalf_of_flow` | Create ticket as another user, verify `created_by_id` |

### Test Data / Fixtures

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def zammad_config():
    return {
        "instance_url": "https://zammad.example.com",
        "token": "test-token-12345",
        "default_customer": "customer@example.com",
        "default_group": "Support",
    }

@pytest.fixture
def mock_ticket_response():
    return {
        "id": 42,
        "title": "Test Ticket",
        "group_id": 1,
        "state_id": 1,
        "customer_id": 3,
        "number": "22042",
        "created_at": "2026-07-09T10:00:00.000Z",
    }

@pytest.fixture
def mock_user_response():
    return {
        "id": 5,
        "login": "jane@example.com",
        "firstname": "Jane",
        "lastname": "Doe",
        "email": "jane@example.com",
        "organization_id": 2,
    }
```

---

## 5. Acceptance Criteria

- [ ] `ZammadInterface` can be instantiated from env vars or explicit kwargs
- [ ] `ZammadInterface` supports async context manager (`async with`)
- [ ] All HTTP requests include `Authorization: Bearer {token}` header
- [ ] `From` header is set when `on_behalf_of` is provided (user ID, login, or email)
- [ ] `From` header is absent when `on_behalf_of` is not provided
- [ ] Ticket CRUD operations work: create, get, list, update, delete, search
- [ ] User operations work: get, search, create, update, get current user
- [ ] Article retrieval works: list articles by ticket ID
- [ ] Attachment download works: returns binary data
- [ ] Pagination is handled for list/search endpoints
- [ ] Non-2xx responses raise `ZammadError` with status code and message
- [ ] Network errors raise `ZammadConnectionError`
- [ ] `ZammadToolkit` extends `AbstractToolkit` and generates tools from public async methods
- [ ] All toolkit tool names are prefixed with `zammad_`
- [ ] `ZammadToolkit` is registered in `TOOL_REGISTRY`
- [ ] ZAMMAD_* env vars added to `parrot/conf.py`
- [ ] All unit tests pass (`pytest tests/interfaces/test_zammad.py -v`)
- [ ] No breaking changes to existing public API
- [ ] Existing `ZammadBackend` in HITL remains unmodified

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Toolkit base classes — from satellite package re-exports
from parrot_tools.toolkit import AbstractToolkit    # verified: packages/ai-parrot-tools/src/parrot_tools/toolkit.py
from parrot_tools.decorators import tool_schema, requires_permission  # verified: packages/ai-parrot-tools/src/parrot_tools/decorators.py (re-exports from parrot.tools.decorators)

# OR from core (both resolve to the same classes)
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.tools.decorators import tool_schema  # verified: packages/ai-parrot/src/parrot/tools/decorators.py:37

# Config
from parrot.conf import (                         # verified: packages/ai-parrot/src/parrot/conf.py
    ODOO_URL,                                     # line 824 — pattern to follow for ZAMMAD_*
)

# Logging
from navconfig.logging import logging             # verified: used in odoointerface.py:13

# aiohttp
import aiohttp                                    # verified: used throughout codebase

# Pydantic
from pydantic import BaseModel, Field             # verified: used throughout codebase
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                        # line 207
    input_class: Optional[Type[BaseModel]] = None  # line 235
    return_direct: bool = False                    # line 236
    exclude_tools: tuple[str, ...] = ()            # line 290
    tool_prefix: Optional[str] = None              # line 291
    prefix_separator: str = "_"                    # line 292
    credential_provider: Optional[str] = None      # line 294

    def __init__(self, **kwargs): ...               # line 296
    async def start(self) -> None: ...              # line 337 — override for setup
    async def stop(self) -> None: ...               # line 344 — override for teardown
    async def cleanup(self) -> None: ...            # line 351
    async def _pre_execute(self, tool_name, /, **kwargs) -> None: ...   # line 375
    async def _post_execute(self, tool_name, result, /, **kwargs): ...  # line 390
    async def _prepare_kwargs(self, tool_name, kwargs): ...             # line 358
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...  # line 406
    def get_tool(self, name: str) -> Optional[AbstractTool]: ...        # line 524
    def list_tool_names(self) -> List[str]: ...     # line 539

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):  # line 37
    # Attaches _args_schema to a toolkit method

# packages/ai-parrot/src/parrot/interfaces/odoointerface.py — PATTERN TO FOLLOW
class OdooInterface:                                # line 130
    def __init__(self, url=None, database=None, username=None, password=None,
                 timeout=None, verify_ssl=None) -> None: ...  # line 156
    async def _get_session(self) -> aiohttp.ClientSession: ...  # line 195
    async def close(self) -> None: ...              # line 210
    async def __aenter__(self) -> "OdooInterface": ...  # line 218
    async def __aexit__(self, ...) -> None: ...      # line 227

# packages/ai-parrot/src/parrot/human/actions/backends/zammad.py — EXISTS, DO NOT MODIFY
class ZammadBackend(ActionBackend):                 # line 18
    async def execute(self, interaction, tier) -> Dict[str, Any]: ...  # line 52
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ZammadInterface` | `parrot.conf` | env var imports | `conf.py:824` (ODOO pattern) |
| `ZammadInterface` | `aiohttp.ClientSession` | HTTP client | used in `odoointerface.py` |
| `ZammadToolkit` | `AbstractToolkit` | inheritance | `toolkit.py:207` |
| `ZammadToolkit` | `@tool_schema` | decorator | `decorators.py:37` |
| `ZammadToolkit` | `TOOL_REGISTRY` | dict entry | `parrot_tools/__init__.py` |
| `ZammadToolkit` | `ZammadInterface` | composition | created in `start()` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.interfaces.zammad`~~ — does not exist yet; must be created
- ~~`parrot_tools.zammad`~~ — does not exist yet; must be created
- ~~`ZAMMAD_INSTANCE` in `parrot/conf.py`~~ — not declared yet; must be added
- ~~`parrot.interfaces.http.HTTPService`~~ — exists but is a complex multi-backend
  class (httpx + aiohttp + requests); do NOT use it for ZammadInterface. Use
  `aiohttp.ClientSession` directly, following the `OdooInterface` pattern
- ~~`AbstractTicket`~~ — navigator-only class, does not exist in AI-Parrot
- ~~`RESTAction`~~ — navigator-only class, does not exist in AI-Parrot
- ~~`parrot.tools.toolkit.AbstractToolkit.register()`~~ — no such method;
  registration is via `TOOL_REGISTRY` dict in `parrot_tools/__init__.py`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Interface pattern**: Follow `OdooInterface` (`parrot/interfaces/odoointerface.py`):
  - Pydantic config model, async context manager, lazy session creation,
    centralized `_request()` method, custom exception hierarchy
- **Toolkit pattern**: Follow `JiraToolkit` (`parrot_tools/jiratoolkit.py`):
  - `AbstractToolkit` subclass, `@tool_schema` Pydantic input models per
    method, `tool_prefix` for namespaced tool names, lifecycle in
    `start()`/`stop()`
- **Authentication**: Bearer token via `Authorization: Bearer {token}` header
  (Zammad OAuth2 style). The navigator reference uses `X-On-Behalf-Of` but the
  official Zammad REST API documents the `From` header for on-behalf-of.
  **Use the official `From` header.**
- **Async-first**: All HTTP calls via `aiohttp`, no blocking I/O
- **Logging**: Use `logging.getLogger(f"parrot.interfaces.zammad")` pattern
- **Error handling**: Custom exceptions (`ZammadError`, `ZammadAuthError`,
  `ZammadConnectionError`) following `OdooError` pattern

### Zammad REST API v1 Endpoints

| Operation | Method | Endpoint |
|---|---|---|
| List tickets | GET | `/api/v1/tickets` |
| Get ticket | GET | `/api/v1/tickets/{id}` |
| Create ticket | POST | `/api/v1/tickets` |
| Update ticket | PUT | `/api/v1/tickets/{id}` |
| Delete ticket | DELETE | `/api/v1/tickets/{id}` |
| Search tickets | GET | `/api/v1/tickets/search?query={q}` |
| List users | GET | `/api/v1/users` |
| Get user | GET | `/api/v1/users/{id}` |
| Current user | GET | `/api/v1/users/me` |
| Create user | POST | `/api/v1/users` |
| Update user | PUT | `/api/v1/users/{id}` |
| Search users | GET | `/api/v1/users/search?query={q}` |
| List articles | GET | `/api/v1/ticket_articles/by_ticket/{ticket_id}` |
| Get attachment | GET | `/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment_id}` |

### On Behalf Of

The Zammad API supports the `From` HTTP header for acting on behalf of another
user. The value can be:
- User ID (integer as string)
- User login
- User email address

Requires `admin.user` permission on the API token.

### Known Risks / Gotchas

- **Navigator uses `X-On-Behalf-Of`**: The navigator reference code uses
  `X-On-Behalf-Of` header. The official Zammad docs specify `From`. Verify
  which header the target Zammad version supports; some older versions may
  use the non-standard header. We will use `From` as primary, with a
  constructor option to override the header name if needed.
- **Pagination differences**: Zammad uses `page` + `per_page` for ticket lists
  but `page` + `limit` for search. Normalize in the interface.
- **Binary attachments**: `get_attachment` returns raw binary; the toolkit
  wrapper should base64-encode for LLM consumption.
- **Rate limiting**: Zammad does not have built-in rate limiting docs, but
  server admins may configure it. No retry logic in v1; add if needed later.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | `>=3.8` | Async HTTP client (already a project dependency) |
| `pydantic` | `>=2.0` | Data models (already a project dependency) |

No new external dependencies required.

---

## 8. Open Questions

- [ ] Should the `From` header name be configurable (to support older Zammad
  instances that use `X-On-Behalf-Of`)? — *Owner: Jesus*
- [ ] Should the toolkit expose `delete_ticket` to LLMs, or should that be
  excluded via `exclude_tools` for safety? — *Owner: Jesus*
- [ ] Should attachment download in the toolkit return base64-encoded data or
  save to a file and return the path? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All five modules are tightly coupled and should be implemented in order.
- No cross-feature dependencies.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-09 | Jesus Lara | Initial draft |
