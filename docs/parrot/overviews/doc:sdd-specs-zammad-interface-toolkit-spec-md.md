---
type: Wiki Overview
title: 'Feature Specification: Zammad Interface & Toolkit'
id: doc:sdd-specs-zammad-interface-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot agents need to interact with Zammad helpdesk servers for ticket
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.http
  rel: mentions
- concept: mod:parrot.interfaces.zammad
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.zammad
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Zammad Interface & Toolkit

**Feature ID**: FEAT-218
**Date**: 2026-07-09
**Author**: Jesus Lara
**Status**: approved
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
- Implement "On Behalf Of" via a configurable header (defaults to `From`,
  configurable to `X-On-Behalf-Of` for older instances)
- Create a `ZammadToolkit` extending `AbstractToolkit` so LLMs can use Zammad
  as tools (`delete_ticket` excluded for safety)
- Support Bearer token authentication (OAuth2 / API token)
- Read configuration from environment variables via `parrot.conf`
- Attachments: save to configurable directory AND return base64-encoded data

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
   calls. Manages authentication headers, a configurable on-behalf-of header
   (`From` by default, `X-On-Behalf-Of` for older instances), response parsing,
   pagination, and error handling. Supports async context manager (`async with`)
   for session lifecycle. Downloads attachments to a configurable directory.

2. **`ZammadToolkit`** — in `parrot_tools/zammad.py`, extends
   `AbstractToolkit`. Wraps `ZammadInterface` methods as public async methods
   that auto-register as LLM tools. Uses `@tool_schema` decorators with
   Pydantic input models for structured argument schemas. `delete_ticket` is
   excluded via `exclude_tools` for safety.

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
│ (delete_ticket      │     │                          │
│  EXCLUDED for LLMs) │     │                          │
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
    on_behalf_of_header: str = Field(default="From", description="Header name for on-behalf-of; use 'X-On-Behalf-Of' for older Zammad instances")
    attachment_dir: Optional[str] = Field(default=None, description="Directory to save downloaded attachments; defaults to a temp dir")


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
    on_behalf_of: Optional[str] = Field(default=None, description="User ID/login/email for on-behalf-of header")


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
    on_behalf_of: Optional[str] = Field(default=None, description="User ID/login/email for on-behalf-of header")


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
        on_behalf_of_header: str = "From",
        attachment_dir: str | None = None,
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
    async def get_attachment(
        self, ticket_id: int, article_id: int, attachment_id: int
    ) -> tuple[bytes, str]: ...
    # Returns (binary_data, file_path) — saves to attachment_dir and returns both


class ZammadToolkit(AbstractToolkit):
    """LLM-facing toolkit for Zammad operations."""
    tool_prefix = "zammad"
    exclude_tools = ("delete_ticket",)  # excluded for safety — available on ZammadInterface directly

    def __init__(
        self,
        instance_url: str | None = None,
        token: str | None = None,
        default_customer: str | None = None,
        default_group: str | None = None,
        on_behalf_of_header: str = "From",
        attachment_dir: str | None = None,
        **kwargs,
    ) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    # Each public async method becomes an LLM tool (except delete_ticket)
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
    # get_attachment returns {"file_path": str, "base64": str, "mime_type": str, "filename": str}
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
  Handles authentication (Bearer token), a configurable on-behalf-of header
  (defaults to `From`, switchable to `X-On-Behalf-Of`), pagination, response
  parsing, attachment download to disk, and error handling.
- **Depends on**: Module 1 (conf vars), `aiohttp`

Key implementation details:
- Uses `aiohttp.ClientSession` with persistent session (created in
  `__aenter__` or lazily on first request)
- All responses parsed as JSON; non-2xx status raises `ZammadError`
- On-behalf-of header (configurable via `on_behalf_of_header`) injected when
  `on_behalf_of` parameter is provided
- Default headers: `Authorization: Bearer {token}`,
  `Content-Type: application/json`
- Supports `?expand=true` query parameter for enriched responses
- Pagination via `page` + `per_page` (Zammad calls it `limit`)
- `get_attachment` saves binary to `attachment_dir` (or temp dir) and returns
  both the binary data and the file path

### Module 3: ZammadToolkit

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/zammad.py`
- **Responsibility**: `AbstractToolkit` subclass exposing `ZammadInterface`
  methods as LLM tools. Each public async method has a Pydantic `@tool_schema`
  for argument validation. `delete_ticket` is excluded via `exclude_tools`.
- **Depends on**: Module 2, `AbstractToolkit`, `@tool_schema`

Key implementation details:
- Creates `ZammadInterface` in `start()`, closes in `stop()`
- `tool_prefix = "zammad"` so tools are named `zammad_create_ticket`, etc.
- `exclude_tools = ("delete_ticket",)` — prevents LLMs from deleting tickets
- Constructor accepts Zammad credentials directly or falls back to env vars
- Each method docstring becomes the LLM tool description
- Uses `on_behalf_of` parameter where applicable, allowing the LLM to
  specify which user to act as
- `get_attachment` saves file to `attachment_dir` and returns a dict with
  `file_path`, `base64`, `mime_type`, and `filename`

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
| `test_zammad_request_on_behalf_of_from` | Module 2 | `From` header set when `on_behalf_of` provided (default) |
| `test_zammad_request_on_behalf_of_custom_header` | Module 2 | Custom header name (`X-On-Behalf-Of`) when configured |
| `test_zammad_request_no_on_behalf_of` | Module 2 | No on-behalf-of header when `on_behalf_of` is None |
| `test_create_ticket_payload` | Module 2 | Correct JSON payload structure |
| `test_create_ticket_with_attachments` | Module 2 | Attachment data encoded and sent |
| `test_update_ticket` | Module 2 | PUT request with correct payload |
| `test_get_ticket` | Module 2 | GET request returns ticket dict |
| `test_search_tickets_pagination` | Module 2 | Multi-page search aggregates results |
| `test_list_tickets_state_filter` | Module 2 | State IDs encoded in query |
| `test_get_articles` | Module 2 | Articles list returned for ticket |
| `test_get_attachment_saves_file` | Module 2 | Attachment saved to disk and binary returned |
| `test_create_user` | Module 2 | User creation payload correct |
| `test_search_users` | Module 2 | User search query correct |
| `test_error_handling_4xx` | Module 2 | Non-2xx raises `ZammadError` |
| `test_error_handling_network` | Module 2 | Connection error raises `ZammadConnectionError` |
| `test_toolkit_tools_registered` | Module 3 | All expected tools appear in `get_tools()` |
| `test_toolkit_tool_prefix` | Module 3 | Tool names start with `zammad_` |
| `test_toolkit_delete_excluded` | Module 3 | `zammad_delete_ticket` NOT in tool list |
| `test_toolkit_start_stop` | Module 3 | Interface created/closed via lifecycle |
| `test_toolkit_attachment_returns_dict` | Module 3 | Returns `{file_path, base64, mime_type, filename}` |

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
- [ ] On-behalf-of header (default `From`) is set when `on_behalf_of` is provided (user ID, login, or email)
- [ ] On-behalf-of header is absent when `on_behalf_of` is not provided
- [ ] `on_behalf_of_header` parameter defaults to `"From"` and is configurable (e.g. `"X-On-Behalf-Of"`)
- [ ] Ticket CRUD operations work: create, get, list, update, delete, search
- [ ] User operations work: get, search, create, update, get current user
- [ ] Article retrieval works: list articles by ticket ID
- [ ] Attachment download saves file to configurable `attachment_dir` and returns binary data
- [ ] Pagination is handled for list/search endpoints
- [ ] Non-2xx responses raise `ZammadError` with status code and message
- [ ] Network errors raise `ZammadConnectionError`
- [ ] `ZammadToolkit` extends `AbstractToolkit` and generates tools from public async methods
- [ ] All toolkit tool names are prefixed with `zammad_`
- [ ] `delete_ticket` excluded from `ZammadToolkit` via `exclude_tools`
- [ ] `get_attachment` toolkit method returns `{"file_path": str, "base64": str, "mime_type": str, "filename": str}`
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

…(truncated)…
