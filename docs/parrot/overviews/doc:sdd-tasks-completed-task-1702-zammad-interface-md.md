---
type: Wiki Overview
title: 'TASK-1702: Implement ZammadInterface async HTTP client'
id: doc:sdd-tasks-completed-task-1702-zammad-interface-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The core async HTTP client wrapping the Zammad REST API v1. All toolkit
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces.http
  rel: mentions
- concept: mod:parrot.interfaces.zammad
  rel: mentions
---

# TASK-1702: Implement ZammadInterface async HTTP client

**Feature**: FEAT-218 — Zammad Interface & Toolkit
**Spec**: `sdd/specs/zammad-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1701
**Assigned-to**: unassigned

---

## Context

The core async HTTP client wrapping the Zammad REST API v1. All toolkit
methods will delegate to this interface. Must handle authentication,
on-behalf-of headers, pagination, attachment downloads, and error handling.

Implements: Spec §3 Module 2 (ZammadInterface).

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/zammad.py` with:
  - **Exception classes**: `ZammadError`, `ZammadAuthError`, `ZammadConnectionError`
  - **Pydantic models**: `ZammadConfig`, `TicketCreatePayload`, `TicketUpdatePayload`, `UserCreatePayload`
  - **`ZammadInterface` class** with:
    - Constructor accepting kwargs or falling back to `parrot.conf` env vars
    - `on_behalf_of_header` parameter (default `"From"`, configurable to `"X-On-Behalf-Of"`)
    - `attachment_dir` parameter (default: temp directory)
    - Async context manager (`__aenter__`/`__aexit__`)
    - Lazy `aiohttp.ClientSession` creation via `_get_session()`
    - Core `_request()` method with auth headers and optional on-behalf-of
    - Ticket operations: `list_tickets`, `get_ticket`, `create_ticket`, `update_ticket`, `delete_ticket`, `search_tickets`
    - User operations: `get_user`, `get_current_user`, `search_users`, `create_user`, `update_user`
    - Article operations: `get_articles`
    - Attachment operations: `get_attachment` — saves to `attachment_dir`, returns `(bytes, file_path)`
- Write unit tests in `packages/ai-parrot/tests/interfaces/test_zammad.py`

**NOT in scope**: ZammadToolkit (TASK-1703), TOOL_REGISTRY (TASK-1704).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/zammad.py` | CREATE | ZammadInterface + models + exceptions |
| `packages/ai-parrot/tests/interfaces/test_zammad.py` | CREATE | Unit tests with mocked aiohttp |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import (                          # verified: conf.py
    ZAMMAD_INSTANCE, ZAMMAD_TOKEN,                 # added by TASK-1701
    ZAMMAD_DEFAULT_CUSTOMER, ZAMMAD_DEFAULT_GROUP,
    ZAMMAD_DEFAULT_CATALOG, ZAMMAD_ORGANIZATION,
    ZAMMAD_DEFAULT_ROLE,
)
from navconfig.logging import logging              # verified: used in odoointerface.py:13
import aiohttp                                     # verified: used throughout codebase
from pydantic import BaseModel, Field              # verified: used throughout codebase
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/odoointerface.py — PATTERN TO FOLLOW
class OdooInterface:                                # line 130
    def __init__(self, url=None, ...) -> None: ...  # line 156
    async def _get_session(self) -> aiohttp.ClientSession: ...  # line 195
    async def close(self) -> None: ...              # line 210
    async def __aenter__(self) -> "OdooInterface": ...  # line 218
    async def __aexit__(self, ...) -> None: ...      # line 227

# Exception hierarchy pattern from odoointerface.py
class OdooError(Exception): ...                     # line 27
class OdooAuthenticationError(OdooError): ...       # line 31
class OdooRPCError(OdooError): ...                  # line 35
class OdooConnectionError(OdooError): ...           # line 49
```

### Does NOT Exist
- ~~`parrot.interfaces.zammad`~~ — does not exist yet; must be created
- ~~`parrot.interfaces.http.HTTPService`~~ — exists but do NOT use it; use `aiohttp.ClientSession` directly
- ~~`AbstractTicket`~~ — navigator-only class, does not exist in AI-Parrot
- ~~`RESTAction`~~ — navigator-only class, does not exist in AI-Parrot
- ~~`self.async_request()`~~ — navigator method, does not exist here
- ~~`self.build_url()`~~ — navigator method, does not exist here

---

## Implementation Notes

### Pattern to Follow
Follow `OdooInterface` structure exactly:
```python
class ZammadInterface:
    def __init__(self, instance_url=None, token=None, ...):
        self.config = ZammadConfig(
            instance_url=instance_url or ZAMMAD_INSTANCE,
            token=token or ZAMMAD_TOKEN,
            ...
        )
        self._session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger("parrot.interfaces.zammad")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
                headers={
                    "Authorization": f"Bearer {self.config.token}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def _request(self, method, path, data=None, params=None, on_behalf_of=None):
        session = await self._get_session()
        url = f"{self.config.instance_url.rstrip('/')}{path}"
        headers = {}
        if on_behalf_of:
            headers[self.config.on_behalf_of_header] = str(on_behalf_of)
        async with session.request(method, url, json=data, params=params, headers=headers) as resp:
            if resp.status == 401:
                raise ZammadAuthError(...)
            if resp.status >= 400:
                raise ZammadError(...)
            return await resp.json()
```

### Zammad REST API v1 Endpoints

| Operation | Method | Path |
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

### Key Constraints
- All IO via `aiohttp` — no blocking calls
- `get_attachment` must save binary to `attachment_dir` (use `aiofiles` or sync write via `asyncio.to_thread`) and return `(bytes, file_path)`
- When `attachment_dir` is None, use `tempfile.mkdtemp()` as default
- Pagination: `list_tickets` and `search_tickets` accept `page` and `per_page` params
- `?expand=true` support via `expand` parameter on `get_ticket`, `get_user`
- Use `self.logger` for all logging

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/odoointerface.py` — primary pattern
- `packages/ai-parrot/src/parrot/human/actions/backends/zammad.py` — existing Zammad HTTP calls (DO NOT modify)
- Navigator `zammad.py` (external) — reference for endpoint usage and payload structure

---

## Acceptance Criteria

- [ ] `ZammadInterface` can be instantiated from env vars or explicit kwargs
- [ ] Async context manager works (`async with ZammadInterface(...) as z:`)
- [ ] `Authorization: Bearer {token}` header sent on all requests
- [ ] On-behalf-of header set when `on_behalf_of` provided (default `From`)
- [ ] On-behalf-of header absent when `on_behalf_of` is None
- [ ] Configurable header name via `on_behalf_of_header`
- [ ] Ticket CRUD: create, get, list, update, delete, search
- [ ] User ops: get, search, create, update, get_current_user
- [ ] Article retrieval: get_articles by ticket_id
- [ ] Attachment download: saves to disk, returns (bytes, file_path)
- [ ] `ZammadError` raised on non-2xx, `ZammadAuthError` on 401, `ZammadConnectionError` on network failure
- [ ] All tests pass: `pytest packages/ai-parrot/tests/interfaces/test_zammad.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/interfaces/zammad.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_zammad.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.interfaces.zammad import (
    ZammadInterface, ZammadConfig, ZammadError, ZammadAuthError, ZammadConnectionError,
    TicketCreatePayload, TicketUpdatePayload, UserCreatePayload,
)

@pytest.fixture
def zammad():
    return ZammadInterface(
        instance_url="https://zammad.example.com",
        token="test-token",
        default_group="Support",
    )

class TestZammadConfig:
    def test_config_from_kwargs(self):
        cfg = ZammadConfig(instance_url="https://z.example.com", token="tok")
        assert cfg.on_behalf_of_header == "From"

    def test_config_custom_header(self):
        cfg = ZammadConfig(instance_url="https://z.example.com", token="tok",
                           on_behalf_of_header="X-On-Behalf-Of")
        assert cfg.on_behalf_of_header == "X-On-Behalf-Of"

class TestZammadInterface:
    @pytest.mark.asyncio
    async def test_context_manager(self, zammad):
        async with zammad:
            assert zammad._session is not None
        assert zammad._session is None or zammad._session.closed

    @pytest.mark.asyncio
    async def test_request_auth_header(self, zammad):
        # Mock aiohttp session and verify Authorization header
        ...

    @pytest.mark.asyncio
    async def test_request_on_behalf_of(self, zammad):
        # Verify From header is set
        ...

    @pytest.mark.asyncio
    async def test_error_4xx(self, zammad):
        # Verify ZammadError raised on 400
        ...

    @pytest.mark.asyncio
    async def test_error_401(self, zammad):
        # Verify ZammadAuthError raised on 401
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/zammad-interface-toolkit.spec.md` §2, §3, §7
2. **Read** `packages/ai-parrot/src/parrot/interfaces/odoointerface.py` for the full pattern
3. **Verify** TASK-1701 is complete (ZAMMAD_* vars exist in conf.py)
4. **Implement** `zammad.py` following OdooInterface structure
5. **Write tests** using mocked aiohttp (no live server needed for unit tests)
6. **Commit** and update status

---

## Completion Note

Implemented `ZammadInterface` in `parrot/interfaces/zammad.py`, mirroring
`OdooInterface`'s structure: Pydantic `ZammadConfig`, lazy `aiohttp.ClientSession`
creation with Bearer-auth headers baked in, async context manager, and a
centralized `_request()` core method. Exception hierarchy
(`ZammadError` → `ZammadAuthError`/`ZammadConnectionError`) with `status_code`
carried on `ZammadError`. All ticket/user/article operations implemented per
signatures in spec §2. `get_attachment` streams binary content directly
(bypassing `_request`'s JSON parsing), saves to `attachment_dir` via
`asyncio.to_thread`, and returns `(bytes, file_path)`.

Deviation note: added an optional `attachments` field to `TicketCreatePayload`
(not listed in the spec's literal model) because the spec's own Test
Specification (§4) requires `test_create_ticket_with_attachments` — "attachment
data encoded and sent" — which cannot be satisfied without a place to carry
attachment data on the payload. Kept minimal: `list[dict[str, str]]` matching
Zammad's native article attachment shape (`filename`, `data`, `mime-type`).

22/22 unit tests pass (`pytest packages/ai-parrot/tests/interfaces/test_zammad.py -v`).
`ruff check` clean on both new files.
