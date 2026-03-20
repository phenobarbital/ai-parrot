# TASK-093: MassiveToolkit Client Wrapper

**Feature**: MassiveToolkit
**Spec**: `sdd/specs/massive-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-092
**Assigned-to**: claude-opus-session

---

## Context

This task implements the client wrapper around the Massive SDK. The SDK is synchronous, so all calls must be wrapped with `asyncio.to_thread()`. The wrapper handles retry logic, rate limiting, and provides typed methods for each endpoint.

Reference: Spec Section 3 "Module 2: Client Wrapper"

---

## Scope

- Create `MassiveClient` class wrapping `massive.RESTClient`
- Wrap all SDK calls in `asyncio.to_thread()` for async compatibility
- Implement retry logic for transient errors (5xx, network timeouts)
- Implement rate limit handling (429 responses) with exponential backoff
- Provide typed methods for each endpoint:
  - `list_snapshot_options_chain()`
  - `list_short_interest()`
  - `list_short_volume()`
  - `get_benzinga_earnings()`
  - `get_benzinga_analyst_ratings()`
  - `get_benzinga_consensus_ratings()`

**NOT in scope**:
- Caching (TASK-094)
- Toolkit class (TASK-095)
- Benzinga availability detection (TASK-095)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/massive/client.py` | CREATE | SDK wrapper with async + retry |

---

## Implementation Notes

### Pattern to Follow

```python
# Reference pattern from parrot/tools/finnhub.py
import asyncio
from typing import Any
from massive import RESTClient

class MassiveClient:
    """Async wrapper for Massive SDK with retry and rate limit handling."""

    def __init__(self, api_key: str):
        self._client = RESTClient(api_key=api_key)
        self.logger = logging.getLogger(__name__)

    async def list_snapshot_options_chain(
        self, underlying: str, **params
    ) -> list[Any]:
        """Fetch options chain with Greeks."""
        return await self._call_with_retry(
            self._client.list_snapshot_options_chain,
            underlying,
            params=params,
        )

    async def _call_with_retry(
        self, method: callable, *args, max_retries: int = 3, **kwargs
    ) -> Any:
        """Execute SDK method with retry and rate limit handling."""
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(method, *args, **kwargs)
            except Exception as e:
                if self._is_rate_limit(e):
                    await self._handle_rate_limit(attempt)
                elif self._is_transient(e) and attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
```

### Key Constraints

- **Must use `asyncio.to_thread()`** — SDK is synchronous
- Max 3 retries for transient errors
- Exponential backoff: 1s, 2s, 4s
- Rate limit (429): respect Retry-After header or default 60s
- Log all retries at WARNING level

### References in Codebase

- `parrot/interfaces/http.py` — `HTTPService` retry patterns
- `parrot/tools/finnhub.py` — API wrapper pattern

---

## Acceptance Criteria

- [ ] `MassiveClient` class implemented with all 6 endpoint methods
- [ ] All SDK calls wrapped in `asyncio.to_thread()`
- [ ] Retry logic works for 5xx errors
- [ ] Rate limit handling respects 429 + Retry-After
- [ ] No linting errors: `ruff check parrot/tools/massive/`
- [ ] Importable: `from parrot.tools.massive.client import MassiveClient`

---

## Test Specification

```python
# tests/test_massive_client.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from parrot.tools.massive.client import MassiveClient


@pytest.fixture
def mock_sdk():
    """Mock the massive SDK."""
    with patch("parrot.tools.massive.client.RESTClient") as mock:
        yield mock


class TestMassiveClient:
    @pytest.mark.asyncio
    async def test_options_chain_success(self, mock_sdk):
        """Successful options chain fetch."""
        mock_sdk.return_value.list_snapshot_options_chain.return_value = [
            MagicMock(ticker="O:AAPL250321C00185000")
        ]
        client = MassiveClient(api_key="test")
        result = await client.list_snapshot_options_chain("AAPL")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, mock_sdk):
        """Retries on 5xx errors."""
        mock_sdk.return_value.list_short_interest.side_effect = [
            Exception("503 Service Unavailable"),
            [MagicMock(short_interest=1000000)],
        ]
        client = MassiveClient(api_key="test")
        result = await client.list_short_interest("GME")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rate_limit_backoff(self, mock_sdk):
        """Handles 429 with backoff."""
        rate_limit_error = Exception("429 Too Many Requests")
        mock_sdk.return_value.list_short_volume.side_effect = [
            rate_limit_error,
            [MagicMock(short_volume=5000000)],
        ]
        client = MassiveClient(api_key="test")
        # Should succeed after backoff
        result = await client.list_short_volume("TSLA")
        assert len(result) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/massive-toolkit.spec.md` for API details
2. **Check dependencies** — TASK-092 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the client wrapper in `parrot/tools/massive/client.py`
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-093-massive-client.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented `MassiveClient` class with all 6 endpoint methods
- Used `asyncio.to_thread()` for all SDK calls to maintain async compatibility
- Implemented retry logic with exponential backoff (1s, 2s, 4s) for transient errors
- Implemented rate limit handling with configurable wait time (default 60s)
- Added custom error classes: MassiveAPIError, MassiveRateLimitError, MassiveTransientError
- Added lazy import for `massive` SDK to handle case where not installed
- All 28 unit tests pass

**Deviations from spec**: Added lazy import pattern and custom exception classes (not in original scope but necessary for robust error handling)
