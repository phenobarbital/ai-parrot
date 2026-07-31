---
type: Wiki Overview
title: 'TASK-1595: Avatar/Voice Listing Handler'
id: doc:sdd-tasks-completed-task-1595-avatar-voice-listing-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The frontend needs endpoints to list available avatars and voices for the
relates_to:
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.tenant_config
  rel: mentions
---

# TASK-1595: Avatar/Voice Listing Handler

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1592
**Assigned-to**: unassigned

---

## Context

The frontend needs endpoints to list available avatars and voices for the
configuration UI. This task adds GET handlers that proxy through `LiveAvatarClient`'s
new `list_avatars()` and `list_voices()` methods (created in TASK-1592).

These endpoints live in the same `avatar_fullmode.py` handler file created by
TASK-1594, but this task can start as soon as TASK-1592 is done (it does not
depend on the start/stop handler logic from TASK-1594).

Implements spec §3 Module 5.

---

## Scope

- Add two handlers to `avatar_fullmode.py`:
  - `GET /api/v1/avatar/avatars` → `_list_avatars(request)` — proxies `client.list_avatars(cfg)`
  - `GET /api/v1/avatar/voices` → `_list_voices(request)` — proxies `client.list_voices(cfg)`
- Both handlers: resolve config via `resolve_fullmode_config()`, create a temporary
  client, call the listing method, return the result.
- Register GET routes in server route setup.
- Write unit tests with mocked client.

**NOT in scope**: Start/stop handlers (TASK-1594), room observer (TASK-1596).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` | MODIFY | Add `_list_avatars`, `_list_voices` handlers |
| `packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py` | MODIFY | Add tests for listing endpoints |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.client import LiveAvatarClient  # client.py:37
from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config  # TASK-1593
```

### Existing Signatures to Use
```python
# Added by TASK-1592:
# LiveAvatarClient.list_avatars(cfg: LiveAvatarConfig) -> List[Dict]
# LiveAvatarClient.list_voices(cfg: LiveAvatarConfig) -> List[Dict]
```

### Does NOT Exist
- ~~`_list_avatars()`~~ — does not exist yet; this task creates it
- ~~`_list_voices()`~~ — does not exist yet
- ~~`GET /api/v1/avatar/avatars`~~ — route does not exist yet
- ~~`GET /api/v1/avatar/voices`~~ — route does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
async def _list_avatars(request: web.Request) -> web.Response:
    from parrot.integrations.liveavatar.client import LiveAvatarClient
    from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

    cfg = resolve_fullmode_config()
    async with LiveAvatarClient(cfg) as client:
        avatars = await client.list_avatars(cfg)
        return web.json_response({"avatars": avatars})
```

### Key Constraints
- These are read-only, public-ish endpoints (gated by API auth, not avatar opt-in)
- Use lazy imports (same pattern as start/stop handlers)
- Tenant context is optional — if no tenant_id in query params, use global config
- Error handling: 500 with safe message if LiveAvatar API returns an error

---

## Acceptance Criteria

- [ ] `GET /api/v1/avatar/avatars` returns a list of available avatars
- [ ] `GET /api/v1/avatar/voices` returns a list of available voices
- [ ] Both endpoints use config resolver (not hardcoded API keys)
- [ ] Lazy imports pattern followed
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py -v -k "list"`

---

## Test Specification

```python
class TestListAvatars:
    async def test_returns_avatars(self, aiohttp_client):
        """GET /api/v1/avatar/avatars returns avatar list."""
        ...

    async def test_handles_api_error(self, aiohttp_client):
        """Returns 500 on LiveAvatar API failure."""
        ...


class TestListVoices:
    async def test_returns_voices(self, aiohttp_client):
        """GET /api/v1/avatar/voices returns voice list."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 5
2. **Check dependencies** — TASK-1592 must be completed (`list_avatars()`, `list_voices()` exist on client)
3. **Check if `avatar_fullmode.py` exists** — if TASK-1594 finished first, add to it; otherwise create it
4. **Add handlers** and register GET routes
5. **Write tests** and verify acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
