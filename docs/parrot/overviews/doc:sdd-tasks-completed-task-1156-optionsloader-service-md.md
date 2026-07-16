---
type: Wiki Overview
title: 'TASK-1156: OptionsLoader Service'
id: doc:sdd-tasks-completed-task-1156-optionsloader-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 3, Module 18. Creates `services/options_loader.py` — an async HTTP
---

# TASK-1156: OptionsLoader Service

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1149, TASK-1155
**Assigned-to**: unassigned

---

## Context

Phase 3, Module 18. Creates `services/options_loader.py` — an async HTTP
service that fetches `FieldOption` lists from `OptionsSource` endpoints.
Features: TTL cache reusing `services/cache.py`, single-flight per
`(source_ref, auth_ref)` to prevent cache stampede, failure-safe (returns
`[]` on errors without raising).

---

## Scope

- Create `services/options_loader.py` with `OptionsLoader` class
- `async def fetch(source, *, auth_context=None) -> list[FieldOption]`
- TTL cache reusing `FormCache` or a compatible in-memory store from `services/cache.py`
- Single-flight per `(source_ref, auth_ref)` using `asyncio.Event` + in-flight dict
- On any error (timeout, 5xx, auth rejection): return `[]` and log warning
- Use `aiohttp.ClientSession` — NO `requests` / `httpx`
- Mirror `SubmissionForwarder` pattern for session lifecycle

**NOT in scope**: RemoteResponseResolver (TASK-1157), API handler wiring (TASK-1158).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/options_loader.py` | CREATE | OptionsLoader async service |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add OptionsLoader unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Pattern to follow: services/forwarder.py:36
import aiohttp
from pydantic import BaseModel
from ..core.schema import SubmitAction  # forwarder uses this

# For OptionsLoader:
import asyncio
import logging
import aiohttp
from ..core.options import FieldOption, OptionsSource
from ..services.auth_context import AuthContext  # from TASK-1155
from ..services.cache import FormCache            # reuse existing cache

# SubmissionForwarder pattern (verified at forwarder.py:36):
class SubmissionForwarder:
    DEFAULT_TIMEOUT: int = 30
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
    async def forward(self, data, submit_action) -> ForwardResult: ...
```

### Existing Signatures to Use
```python
# core/options.py (after TASK-1149):
class OptionsSource(BaseModel):
    source_type: str
    source_ref: str
    value_field: str = "value"
    label_field: str = "label"
    cache_ttl_seconds: int | None = None
    http_method: Literal["GET", "POST"] = "GET"  # TASK-1149
    auth_ref: str | None = None                   # TASK-1149

# core/options.py:12:
class FieldOption(BaseModel):
    value: str
    label: LocalizedString
    description: LocalizedString | None = None
    disabled: bool = False
    icon: str | None = None

# services/cache.py — FormCache (read this file to understand the API)
# FormCache is for FormSchema objects. OptionsLoader needs a simpler
# in-memory TTL structure. Either adapt FormCache or create a lightweight
# in-memory dict with expiry timestamps inside OptionsLoader itself.
```

### Does NOT Exist
- ~~`OptionsLoader`~~ — THIS task creates it
- ~~`services/options_loader.py`~~ — THIS task creates it
- ~~`requests` / `httpx`~~ — FORBIDDEN; use aiohttp only

---

## Implementation Notes

### Single-Flight Pattern
```python
class OptionsLoader:
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, cache: FormCache | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        self._cache: dict[tuple, tuple[list[FieldOption], float]] = {}  # key → (options, expiry)
        self._in_flight: dict[tuple, asyncio.Event] = {}
        self._in_flight_results: dict[tuple, list[FieldOption]] = {}

    async def fetch(
        self,
        source: OptionsSource,
        *,
        auth_context: AuthContext | None = None,
    ) -> list[FieldOption]:
        """Fetch and normalise options. Cache key = (source_ref, auth_ref).
        Single-flight: concurrent calls for same key share one request.
        Failure returns [] and logs a warning — never raises.
        """
        cache_key = (source.source_ref, source.auth_ref)

        # 1. Check TTL cache
        # 2. Check if in-flight (another coroutine is fetching this key)
        # 3. Mark as in-flight, fetch, normalise, cache, release event
        # 4. Return results
```

### Option Normalisation
```python
def _normalise(self, raw: list[dict], source: OptionsSource) -> list[FieldOption]:
    """Map raw API response items to FieldOption using value_field and label_field."""
    options = []
    for item in raw:
        value = str(item.get(source.value_field, ""))
        label = str(item.get(source.label_field, value))
        options.append(FieldOption(value=value, label=label))
    return options
```

---

## Acceptance Criteria

- [ ] `services/options_loader.py` exists with `OptionsLoader` class
- [ ] `from parrot_formdesigner.services.options_loader import OptionsLoader` resolves
- [ ] `fetch()` uses `value_field` / `label_field` (NOT `value_column` / `label_column`)
- [ ] Cache hit within TTL does NOT make a second HTTP call
- [ ] Two concurrent calls for same key share exactly one HTTP request (single-flight)
- [ ] Mocked 500 response yields `[]` without raising
- [ ] `test_options_loader_fetch_uses_value_label_fields` passes
- [ ] `test_options_loader_cache_hit_within_ttl` passes
- [ ] `test_options_loader_single_flight` passes
- [ ] `test_options_loader_failure_returns_empty` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py (or new test file)
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from parrot_formdesigner.services.options_loader import OptionsLoader
from parrot_formdesigner.core.options import OptionsSource
from parrot_formdesigner.services.auth_context import AuthContext


@pytest.mark.asyncio
async def test_options_loader_fetch_uses_value_label_fields():
    """Mocked aiohttp returns [{"id":1,"name":"A"}]; loader uses value_field=id, label_field=name."""
    loader = OptionsLoader()
    source = OptionsSource(
        source_type="endpoint",
        source_ref="https://api.test/users",
        value_field="id",
        label_field="name",
    )
    mock_response = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    with patch("aiohttp.ClientSession.get") as mock_get:
        # Set up mock to return mock_response
        mock_get.return_value.__aenter__ = AsyncMock(return_value=...)
        # ... configure mock
        options = await loader.fetch(source)
    assert len(options) == 2
    assert options[0].value == "1"
    assert options[0].label == "Alice"


@pytest.mark.asyncio
async def test_options_loader_cache_hit_within_ttl():
    """Second call within TTL does not hit aiohttp."""
    # Use aiohttp_mocker or patch to count calls
    pass


@pytest.mark.asyncio
async def test_options_loader_single_flight():
    """Two concurrent calls for same (source_ref, auth_ref) share one in-flight request."""
    loader = OptionsLoader()
    call_count = 0
    # Patch fetch to count HTTP calls, launch two concurrent coroutines
    pass


@pytest.mark.asyncio
async def test_options_loader_failure_returns_empty():
    """Mocked 500 response yields [] (no raise)."""
    loader = OptionsLoader()
    source = OptionsSource(source_type="endpoint", source_ref="https://api.test/fail")
    with patch("aiohttp.ClientSession.get") as mock_get:
        # mock 500 response
        pass
    options = await loader.fetch(source)
    assert options == []
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
