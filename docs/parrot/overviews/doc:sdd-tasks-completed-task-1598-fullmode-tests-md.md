---
type: Wiki Overview
title: 'TASK-1598: End-to-End Tests'
id: doc:sdd-tasks-completed-task-1598-fullmode-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Final task: integration-level tests that verify the full FULL mode flow'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.tenant_config
  rel: mentions
---

# TASK-1598: End-to-End Tests

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1591, TASK-1592, TASK-1593, TASK-1594, TASK-1595, TASK-1596, TASK-1597
**Assigned-to**: unassigned

---

## Context

Final task: integration-level tests that verify the full FULL mode flow
end-to-end with mocked LiveAvatar API. This complements the unit tests
written in each prior task by testing the assembled pipeline.

Implements spec §3 Module 8.

---

## Scope

- Write integration tests covering the full start → speak → stop lifecycle:
  1. Config resolution → client creation → session token → start session
  2. Handler start → returns viewer creds → handler stop → idempotent
  3. Observer connects (or stubs if Q-room-token unresolved) → disconnects
- Test the opt-in gate chain: avatar disabled → fullmode disabled → fullmode enabled
- Test error cases: missing env vars, LiveAvatar API errors, malformed responses
- All tests use mocked HTTP (no real LiveAvatar API calls)

**NOT in scope**: Actual LiveAvatar API integration testing (requires credentials).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_fullmode_integration.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (all created by prior tasks)
```python
from parrot.integrations.liveavatar.models import (
    FullModeConfig, FullModeSessionHandle, TenantAvatarConfig,
)
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
from parrot.integrations.liveavatar.optin import is_fullmode_enabled
from parrot.integrations.liveavatar.fullmode_observer import FullModeRoomObserver
```

### Does NOT Exist
- Real LiveAvatar API responses — all tests must mock the HTTP layer
- ~~`FullModeIntegrationTest`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.liveavatar.models import FullModeConfig, FullModeSessionHandle
from parrot.integrations.liveavatar.client import LiveAvatarClient


@pytest.fixture
def mock_liveavatar_responses():
    """Mock responses matching LiveAvatar API envelope format."""
    return {
        "token": {
            "code": 200,
            "data": {
                "session_id": "test-session",
                "session_token": "test-token",
            },
            "message": "success",
        },
        "start": {
            "code": 200,
            "data": {
                "livekit_url": "wss://test.livekit.cloud",
                "livekit_client_token": "eyJtest...",
            },
            "message": "success",
        },
    }
```

### Key Constraints
- Tests must be deterministic (no real API calls, no randomness)
- Use `pytest-asyncio` for async tests
- Use `aiohttp.test_utils` or `aioresponses` for mocking HTTP
- Cover error paths: missing config, API failures, malformed responses
- Each test should be independent (no shared state between tests)

---

## Acceptance Criteria

- [ ] Full lifecycle test: config → client → token → start → stop
- [ ] Opt-in chain test: disabled-avatar → disabled-fullmode → enabled-fullmode
- [ ] Error handling test: missing LIVEAVATAR_API_KEY raises RuntimeError
- [ ] Error handling test: LiveAvatar API 500 → graceful error
- [ ] Observer lifecycle test: connect → disconnect (with Q-room-token gate)
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_fullmode_integration.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, patch


class TestFullModeLifecycle:
    """End-to-end lifecycle with mocked HTTP."""

    async def test_start_to_stop(self, mock_liveavatar_responses):
        """Config → client → token → start → stop works end-to-end."""
        ...

    async def test_start_returns_livekit_creds(self, mock_liveavatar_responses):
        """After start, handle has livekit_url and livekit_client_token."""
        ...


class TestOptinChain:
    """Opt-in gate layering: avatar → fullmode."""

    def test_avatar_disabled_blocks_fullmode(self, monkeypatch):
        ...

    def test_fullmode_disabled_blocks_despite_avatar(self, monkeypatch):
        ...

    def test_fullmode_enabled(self, monkeypatch):
        ...


class TestErrorHandling:
    """Error paths: config, API failures."""

    def test_missing_api_key(self, monkeypatch):
        ...

    async def test_liveavatar_api_500(self):
        ...

    async def test_malformed_api_response(self):
        ...


class TestObserverLifecycle:
    """Room observer connect/disconnect."""

    async def test_connect_disconnect(self):
        ...

    async def test_connect_without_livekit_url(self):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 8 and §5 Test Specification
2. **Check dependencies** — ALL prior tasks (1591-1597) must be completed
3. **Review unit tests** from each prior task for coverage gaps
4. **Write integration tests** covering the full pipeline
5. **Run ALL tests** across the feature to verify nothing is broken:
   ```bash
   pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/ -v
   pytest packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py -v
   ```

---

## Completion Note

Implemented by sdd-worker (2026-06-19):

Created `test_fullmode_integration.py` with 4 test classes:

- **TestFullModeLifecycle**: config resolution (success + missing-key + missing-avatar-id),
  create_full_session_token populates handle fields, start_session populates livekit
  fields, full start-to-stop lifecycle with 3 sequential mocked POST responses.
- **TestOptinChain**: avatar-disabled blocks fullmode, fullmode env absent blocks,
  both wildcards allow, tenant-specific fullmode gate, None tenant always denied.
- **TestErrorHandling**: missing LIVEAVATAR_API_KEY raises RuntimeError, API 500
  propagates from create_full_session_token and start_session, malformed response
  (missing 'data' key) uses empty defaults instead of crashing.
- **TestObserverLifecycle**: instantiation, connect with/without livekit_url (Q-room-token
  stub), idempotent disconnect, full connect+disconnect cycle, output_bridge wiring,
  _on_data wrong-topic ignore, malformed JSON handling, valid event processing, bridge
  forwarding verified via AsyncMock.assert_awaited_once.

All tests are fully independent. No real LiveAvatar API calls.
