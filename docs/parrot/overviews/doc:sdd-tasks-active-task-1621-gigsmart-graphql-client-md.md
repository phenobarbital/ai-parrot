---
type: Wiki Overview
title: 'TASK-1621: GigSmart GraphQL Client'
id: doc:sdd-tasks-active-task-1621-gigsmart-graphql-client-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core aiohttp-based GraphQL client for the GigSmart API. Sends queries/mutations,
relates_to:
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.auth
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.client
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: mentions
---

# TASK-1621: GigSmart GraphQL Client

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1616, TASK-1617, TASK-1618, TASK-1619, TASK-1620
**Assigned-to**: unassigned

---

## Context

Core aiohttp-based GraphQL client for the GigSmart API. Sends queries/mutations,
handles error classification, Relay pagination, retry with backoff, and rate limiting.
This is the integration layer between the raw queries (TASK-1620) and the toolkit
(TASK-1622). Implements Spec §2 Module 6.

---

## Scope

- Implement `GigSmartClient` class wrapping `aiohttp.ClientSession`
- `execute(query, variables, operation_name)` → sends GraphQL POST
- Error classification: map `extensions.code` to typed exceptions
- Relay auto-pagination: `paginate(query, variables, extract_path)` → yields all nodes
- Retry with exponential backoff for transient errors (5xx, rate limits)
- Concurrency limiting via `asyncio.Semaphore`
- PII scrubbing in logs (controlled by `GIGSMART_LOG_PII`)
- Write unit tests with mocked HTTP responses

**NOT in scope**: toolkit methods (TASK-1622), OAuth logic (TASK-1618 — consumed via composition).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/client.py` | CREATE | GraphQL client |
| `tests/tools/gigsmart/test_client.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp  # CLAUDE.md mandates aiohttp
import asyncio
import logging
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig  # TASK-1617
from parrot_tools.interfaces.gigsmart.auth import GigSmartAuth  # TASK-1618
from parrot_tools.interfaces.gigsmart.exceptions import (  # TASK-1616
    GigSmartError, GigSmartAuthError, GigSmartValidationError,
    GigSmartRateLimitError, GigSmartNotFoundError,
    GigSmartTransportError, GigSmartGraphQLError, GigSmartConflictError,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/http.py:126-190
# REFERENCE PATTERN for aiohttp.ClientSession lifecycle
class HTTPService:
    def __init__(self, base_url: str, ...):
        self._session: aiohttp.ClientSession | None = None
    async def _ensure_session(self) -> aiohttp.ClientSession: ...
    async def close(self) -> None: ...
```

### Does NOT Exist
- ~~`httpx.AsyncClient`~~ — do NOT use; CLAUDE.md mandates aiohttp
- ~~`gql` library~~ — not used; execute queries as raw POST with aiohttp
- ~~`parrot.interfaces.graphql.GraphQLClient`~~ — does NOT exist
- ~~`GigSmartService`~~ — brainstorm SPEC name; use `GigSmartClient`

---

## Implementation Notes

### GraphQL POST Format
```python
async def execute(self, query: str, variables: dict | None = None,
                  operation_name: str | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    if operation_name:
        payload["operationName"] = operation_name
    # POST to endpoint_url with auth headers
    # Parse response, classify errors, return data
```

### Error Classification Table (from Spec §7)
| `extensions.code` | Exception |
|---|---|
| `UNAUTHENTICATED` | `GigSmartAuthError` |
| `FORBIDDEN` | `GigSmartAuthError` |
| `BAD_USER_INPUT` | `GigSmartValidationError` |
| `NOT_FOUND` | `GigSmartNotFoundError` |
| `CONFLICT` | `GigSmartConflictError` |
| HTTP 429 | `GigSmartRateLimitError` |
| HTTP 5xx | `GigSmartTransportError` |
| Other GraphQL error | `GigSmartGraphQLError` |

### Relay Auto-Pagination
```python
async def paginate(self, query: str, variables: dict,
                   extract_path: str, page_size: int = 25) -> list[dict]:
    """Fetch all pages of a Relay connection.

    extract_path: dot-separated path to the connection field in response data.
    Example: "organization.gigs" for data.organization.gigs.edges
    """
    all_nodes = []
    variables = {**variables, "first": page_size, "after": None}
    while True:
        data = await self.execute(query, variables)
        connection = _extract_path(data, extract_path)
        all_nodes.extend(edge["node"] for edge in connection["edges"])
        page_info = connection["pageInfo"]
        if not page_info.get("hasNextPage"):
            break
        variables["after"] = page_info["endCursor"]
    return all_nodes
```

### Retry Policy
- Max 3 retries for transient errors
- Exponential backoff: 1s, 2s, 4s
- Rate limit: use `retry_after` from `GigSmartRateLimitError`
- Non-retryable: auth errors, validation errors, not-found, conflict

### Concurrency
- Use `asyncio.Semaphore(config.max_concurrent_requests)` to limit parallel requests
- Default: 8 concurrent requests

### PII Scrubbing
```python
if not self.config.log_pii:
    # Scrub worker names, addresses from log output
    # Scrub access_token from logged headers
```

---

## Acceptance Criteria

- [ ] `execute()` sends GraphQL POST and returns parsed `data`
- [ ] Error classification maps `extensions.code` to correct exception types
- [ ] `paginate()` follows `hasNextPage` / `endCursor` across multiple pages
- [ ] Retry logic retries on 5xx and 429, not on 4xx
- [ ] Concurrency semaphore limits parallel requests
- [ ] PII scrubbing active when `GIGSMART_LOG_PII` is falsy
- [ ] `async with` context manager support for session lifecycle
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_client.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_tools.interfaces.gigsmart.client import GigSmartClient
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartAuthError, GigSmartValidationError, GigSmartRateLimitError,
    GigSmartTransportError, GigSmartGraphQLError,
)

@pytest.fixture
def config():
    return GigSmartConfig(client_id="test", client_secret="secret")

class TestGigSmartClient:
    async def test_execute_returns_data(self, config):
        client = GigSmartClient(config)
        # Mock aiohttp response with {"data": {"gigs": {...}}}
        result = await client.execute("query { gigs { edges { node { id } } } }")
        assert "gigs" in result

    async def test_error_classification_auth(self, config):
        client = GigSmartClient(config)
        # Mock response with errors[].extensions.code = "UNAUTHENTICATED"
        with pytest.raises(GigSmartAuthError):
            await client.execute("query { me { id } }")

    async def test_paginate_follows_pages(self, config):
        client = GigSmartClient(config)
        # Mock two pages of results
        nodes = await client.paginate("query ...", {}, "gigs")
        assert len(nodes) > 1  # collected from multiple pages

    async def test_retry_on_transient_error(self, config):
        client = GigSmartClient(config)
        # Mock first call returns 500, second returns data
        result = await client.execute("query { gigs { edges { node { id } } } }")
        assert result is not None
```

---

## Completion Note

*(Agent fills this in when done)*
