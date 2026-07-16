---
type: Wiki Overview
title: 'TASK-1592: FULL Mode Client Extension'
id: doc:sdd-tasks-completed-task-1592-fullmode-client-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extends `LiveAvatarClient` with FULL mode session creation and read-only
relates_to:
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
---

# TASK-1592: FULL Mode Client Extension

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1591
**Assigned-to**: unassigned

---

## Context

Extends `LiveAvatarClient` with FULL mode session creation and read-only
provisioning methods. The client already handles LITE sessions; this task adds
a second session creation path (`mode: "FULL"` without `livekit_config`) and
GET methods for avatar/voice listing and transcript retrieval.

Implements spec §3 Module 2.

---

## Scope

- Add `create_full_session_token(cfg: FullModeConfig) -> FullModeSessionHandle`
  to `LiveAvatarClient`. Payload: `mode: "FULL"`, `avatar_id`, `avatar_persona`
  (voice_id, language), `interactivity_type`, `video_settings`, `max_session_duration`.
  Critically: **no `context_id`**, **no `llm_configuration_id`** (restricted mode).
- Add `_get()` helper (mirrors `_post()` pattern) for GET requests.
- Add `list_avatars(cfg) -> List[Dict]` — `GET /v1/avatars` (public + user).
- Add `list_voices(cfg) -> List[Dict]` — `GET /v1/voices`.
- Add `get_session_transcript(cfg, session_id) -> Dict` — `GET /v1/sessions/{id}/transcript`.
- Override `start_session()` behavior for FULL mode: populate `livekit_url` and
  `livekit_client_token` from the `/start` response on `FullModeSessionHandle`.
- Write unit tests (mocked HTTP).

**NOT in scope**: Per-tenant config resolution (TASK-1593), REST handler endpoints
(TASK-1594/1595), room observer (TASK-1596).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` | MODIFY | Add `create_full_session_token()`, `_get()`, `list_avatars()`, `list_voices()`, `get_session_transcript()` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py` | MODIFY | Add tests for new methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.client import LiveAvatarClient  # __init__.py:10
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,  # models.py:86
    LiveAvatarConfig,     # models.py:18
    FullModeConfig,       # added by TASK-1591
    FullModeSessionHandle,  # added by TASK-1591
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py
class LiveAvatarClient:  # line 37
    def __init__(self, cfg: LiveAvatarConfig, *, session: Optional[aiohttp.ClientSession] = None) -> None:  # line 57
    cfg: LiveAvatarConfig  # set in __init__
    _session: Optional[aiohttp.ClientSession]  # line 65
    _handle: Optional[AvatarSessionHandle]  # line 68

    # Auth helpers to reuse:
    def _api_key_headers(self, cfg: LiveAvatarConfig) -> Dict[str, str]:  # line 283
    def _bearer_headers(self, handle: AvatarSessionHandle) -> Dict[str, str]:  # line 297
    async def _post(self, url: str, *, headers: Dict[str, str], json: Dict[str, Any]) -> Dict[str, Any]:  # line 311

    # Existing LITE session creation (reference for pattern):
    async def create_session_token(self, cfg: LiveAvatarConfig, *, livekit_config: Optional[Dict[str, Any]] = None) -> AvatarSessionHandle:  # line 116
    async def start_session(self, handle: AvatarSessionHandle) -> Dict[str, Any]:  # line 187
```

### Does NOT Exist
- ~~`LiveAvatarClient._get()`~~ — no GET helper exists; only `_post()` at line 311. This task creates `_get()`.
- ~~`LiveAvatarClient.create_full_session_token()`~~ — does not exist yet; this task creates it
- ~~`LiveAvatarClient.list_avatars()`~~ — does not exist yet
- ~~`LiveAvatarClient.list_voices()`~~ — does not exist yet
- ~~`LiveAvatarClient.get_session_transcript()`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow create_session_token() at line 116 for the session creation pattern.
# The key difference for FULL mode:
# 1. payload["mode"] = "FULL" (not "LITE")
# 2. No livekit_config (LiveAvatar manages the room)
# 3. Add avatar_persona with voice_id + language
# 4. Add interactivity_type
# 5. Return FullModeSessionHandle (not AvatarSessionHandle)

async def create_full_session_token(
    self,
    cfg: FullModeConfig,
) -> FullModeSessionHandle:
    url = f"{cfg.base_url}/v1/sessions/token"
    headers = self._api_key_headers(cfg)
    payload = {
        "mode": "FULL",
        "avatar_id": cfg.avatar_id,
        "interactivity_type": cfg.interactivity_type,
    }
    # avatar_persona — only include voice_id if set
    persona = {}
    if cfg.voice_id:
        persona["voice_id"] = cfg.voice_id
    if cfg.language:
        persona["language"] = cfg.language
    if persona:
        payload["avatar_persona"] = persona
    # ... (video_settings, max_session_duration, is_sandbox)
```

```python
# _get() helper — mirrors _post() at line 311:
async def _get(self, url: str, *, headers: Dict[str, str]) -> Dict[str, Any]:
    if self._session is None:
        raise RuntimeError("LiveAvatarClient has no active aiohttp session.")
    async with self._session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        if resp.content_type == "application/json":
            return await resp.json()
        return {}
```

### Key Constraints
- The FULL mode `/start` response differs from LITE: it returns `livekit_url`
  and `livekit_client_token` (not `ws_url`). The `start_session()` method must
  detect `FullModeSessionHandle` and populate these fields.
- **Never** include `context_id` or `llm_configuration_id` in the FULL mode payload.
- LiveAvatar wraps responses in a `{"code": ..., "data": ..., "message": ...}` envelope.
  Extract from `data` (same as `create_session_token` at line 166).

---

## Acceptance Criteria

- [ ] `create_full_session_token()` sends correct payload with `mode: "FULL"`, `avatar_persona`, no `context_id`/`llm_configuration_id`
- [ ] `start_session()` populates `livekit_url` + `livekit_client_token` on `FullModeSessionHandle`
- [ ] `_get()` helper works for GET requests with `X-API-KEY` auth
- [ ] `list_avatars()` calls `GET /v1/avatars` with correct headers
- [ ] `list_voices()` calls `GET /v1/voices` with correct headers
- [ ] `get_session_transcript()` calls `GET /v1/sessions/{id}/transcript`
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import FullModeConfig, FullModeSessionHandle


@pytest.fixture
def fullmode_cfg():
    return FullModeConfig(
        api_key="test-key", avatar_id="test-avatar",
        voice_id="test-voice", language="en",
    )


class TestCreateFullSessionToken:
    async def test_payload_mode_full(self, fullmode_cfg):
        """Payload contains mode=FULL, avatar_persona, no context_id."""
        # Mock _post, verify payload
        ...

    async def test_no_llm_configuration(self, fullmode_cfg):
        """llm_configuration_id and context_id are absent from payload."""
        ...

    async def test_returns_fullmode_handle(self, fullmode_cfg):
        """Returns FullModeSessionHandle (not AvatarSessionHandle)."""
        ...


class TestStartSessionFullMode:
    async def test_populates_livekit_fields(self):
        """start_session sets livekit_url and livekit_client_token on FullModeSessionHandle."""
        ...


class TestListAvatars:
    async def test_calls_get_avatars(self, fullmode_cfg):
        """GET /v1/avatars with X-API-KEY header."""
        ...


class TestListVoices:
    async def test_calls_get_voices(self, fullmode_cfg):
        """GET /v1/voices with X-API-KEY header."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/liveavatar-fullmode-speaktext.spec.md` §2, §3 Module 2
2. **Check dependencies** — TASK-1591 must be completed (FullModeConfig, FullModeSessionHandle exist)
3. **Verify the Codebase Contract** — confirm `_post()`, `_api_key_headers()`, `create_session_token()` still at documented lines
4. **Implement** in `client.py`: add `_get()`, `create_full_session_token()`, listing methods, and update `start_session()` for FULL mode
5. **Write tests** with mocked HTTP responses
6. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
