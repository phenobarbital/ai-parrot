---
type: Wiki Overview
title: 'TASK-1584: Extract request-agnostic voice-native helpers from avatar.py'
id: doc:sdd-tasks-completed-task-1584-extract-voice-native-helpers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-244. Today the logic to mint a publish-capable
relates_to:
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.room_manager
  rel: mentions
---

# TASK-1584: Extract request-agnostic voice-native helpers from avatar.py

**Feature**: FEAT-244 — Unified Voice Control on the StreamHandler WebSocket
**Spec**: `sdd/specs/unified-voice-control-streamhandler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-244. Today the logic to mint a publish-capable
LiveKit token + dispatch the FEAT-243 worker is inline inside the aiohttp
request handler `_start_voice_native_session(request)`, and the teardown is
inline inside `_stop_avatar_session(request)`. `StreamHandler` (TASK-1585) needs
to call that same logic without an aiohttp `request`. This task extracts two
request-agnostic helpers so both the REST view and the WebSocket handler share
one implementation. **Pure refactor — REST behavior must stay identical.**

---

## Scope

- Add `async def start_voice_native(app, agent_id, session_id, tenant_id) -> dict`
  to `avatar.py`, containing the body currently in `_start_voice_native_session`
  AFTER `agent_id` / `session_id` / `tenant_id` have been parsed: opt-in gate
  (`is_avatar_enabled`), `LiveKitRoomManager()` construction (mapping `KeyError`
  → `HTTPServiceUnavailable`), `mint_browser_token`, `AvatarJobMetadata` build,
  `dispatch_worker` (mapping failure → `HTTPServiceUnavailable`), and the
  `app[AVATAR_VOICE_SESSIONS_KEY]` bookkeeping. Returns
  `{"livekit_url", "token", "session_id"}`.
- Add `async def stop_voice_native(app, session_id) -> None` containing the
  Phase C portion of `_stop_avatar_session`: pop from `AVATAR_VOICE_SESSIONS_KEY`
  and call `_delete_voice_dispatch`. Idempotent on unknown `session_id`.
- Rewire `_start_voice_native_session(request)` to parse the request (`agent_id`
  from `match_info`, `session_id`/`tenant_id` from JSON body, the existing
  required-field validation) and then delegate to `start_voice_native(...)`,
  returning `web.json_response(result)`.
- Rewire `_stop_avatar_session(request)` so its Phase C branch calls
  `stop_voice_native(...)` instead of the inline pop + `_delete_voice_dispatch`.
  The Phase A branch stays exactly as-is.
- Keep all `parrot.integrations.liveavatar` imports **lazy** (inside the
  helpers/handlers) — never hard-require the optional extra at module import.
- Write unit tests for the helpers (see Test Specification).

**NOT in scope**: any change to `StreamHandler` (TASK-1585), the output
subscriber (TASK-1586), the worker, or Phase A `/start`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar.py` | MODIFY | Extract `start_voice_native` / `stop_voice_native`; rewire the two request handlers to delegate |
| `packages/ai-parrot-server/tests/test_avatar_voice_helpers.py` | CREATE | Unit tests for the extracted helpers + a "REST view unchanged" test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already present at top of avatar.py (keep as-is)
from aiohttp import web                                            # avatar.py:39
# Lazy imports INSIDE handlers/helpers (keep lazy — do NOT hoist):
from parrot.integrations.liveavatar import LiveKitRoomManager      # avatar.py:314
from parrot.integrations.liveavatar.livekit_agent.models import AvatarJobMetadata  # avatar.py:315
from parrot.integrations.liveavatar.optin import is_avatar_enabled # avatar.py:318
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/avatar.py
AVATAR_VOICE_SESSIONS_KEY = "avatar_voice_sessions"               # line 57
async def _delete_voice_dispatch(record: dict) -> None: ...       # line 198 (best-effort; never raises)
async def _stop_avatar_session(request) -> web.Response: ...      # line 223 (voice branch: lines 247-251)
def _worker_agent_name() -> str: ...                              # line 277 (env, default "liveavatar-voice")
async def _start_voice_native_session(request) -> web.Response:   # line 287
#   mint_browser_token -> token (await asyncio.to_thread, line 353)
#   AvatarJobMetadata(ws_url=room_manager.url, session_id=, agent_name=agent_id, tenant_id=)  (line 359)
#   room_manager.dispatch_worker(room=session_id, worker_agent_name=_worker_agent_name(), metadata_json=meta.model_dump_json())  (line 366)
#   voice_store[session_id] = {"room": session_id, "dispatch_id": dispatch_id}  (line 383)
class VoiceNativeAvatarView(BaseView):                            # line 420 (post -> _start_voice_native_session, line 432)

# parrot.integrations.liveavatar.room_manager.LiveKitRoomManager (do NOT modify)
#   .url: str
#   .mint_browser_token(room: str, identity: str) -> str          (sync; called via asyncio.to_thread)
#   async .dispatch_worker(room, worker_agent_name, metadata_json) -> str  (dispatch_id)
#   async .delete_dispatch(room, dispatch_id) -> None
```

### Does NOT Exist
- ~~`start_voice_native` / `stop_voice_native` in `avatar.py`~~ — this task creates them.
- ~~A non-lazy top-level `import parrot.integrations.liveavatar`~~ — imports are lazy by design; keep them lazy.
- ~~`LiveKitRoomManager.mint_browser_token` as async~~ — it is sync; call via `asyncio.to_thread` (as line 353 already does).

---

## Implementation Notes

### Pattern to Follow
Keep the request-parsing/validation in the `request`-handlers and move only the
work into the helpers. Signature shape:
```python
async def start_voice_native(app, agent_id, session_id, tenant_id):
    # opt-in gate -> LiveKitRoomManager() -> mint_browser_token (to_thread)
    # -> AvatarJobMetadata -> dispatch_worker -> voice_store bookkeeping
    return {"livekit_url": room_manager.url, "token": token, "session_id": session_id}
```
Raise the same `web.HTTPForbidden` / `web.HTTPServiceUnavailable` the inline code
raises today — callers (REST view AND StreamHandler) handle them.

### Key Constraints
- Async throughout; JWT signing stays off the event loop via `asyncio.to_thread`.
- `stop_voice_native` must never raise (mirror `_delete_voice_dispatch` semantics).
- No behavior change to the REST contract: `_start_voice_native_session` still
  returns `{"livekit_url", "token", "session_id"}`; `/stop` still 204.

### References in Codebase
- `avatar.py:287-397` — source of `start_voice_native`.
- `avatar.py:223-274` — source of `stop_voice_native` (Phase C branch only).

---

## Acceptance Criteria

- [ ] `start_voice_native` / `stop_voice_native` exist and contain the extracted logic.
- [ ] `VoiceNativeAvatarView.post` returns byte-identical JSON to pre-refactor.
- [ ] `/stop` Phase C path delegates to `stop_voice_native`; Phase A path unchanged.
- [ ] LiveAvatar imports remain lazy (no top-level hard import added).
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_avatar_voice_helpers.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/avatar.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_avatar_voice_helpers.py
import pytest
from aiohttp import web
from parrot.handlers import avatar


@pytest.fixture
def app_with_room_manager(mocker):
    app = web.Application()
    rm = mocker.Mock()
    rm.url = "wss://test.livekit.cloud"
    rm.mint_browser_token.return_value = "browser-jwt"
    rm.dispatch_worker = mocker.AsyncMock(return_value="dispatch-123")
    rm.delete_dispatch = mocker.AsyncMock()
    mocker.patch.object(avatar, "LiveKitRoomManager", return_value=rm, create=True)
    mocker.patch("parrot.integrations.liveavatar.optin.is_avatar_enabled", return_value=True)
    return app, rm


async def test_start_voice_native_dispatches_and_records(app_with_room_manager):
    app, rm = app_with_room_manager
    out = await avatar.start_voice_native(app, "my-agent", "sess-1", None)
    assert out == {"livekit_url": "wss://test.livekit.cloud", "token": "browser-jwt", "session_id": "sess-1"}
    rm.dispatch_worker.assert_awaited_once()
    assert app[avatar.AVATAR_VOICE_SESSIONS_KEY]["sess-1"]["dispatch_id"] == "dispatch-123"


async def test_stop_voice_native_deletes_dispatch(app_with_room_manager):
    app, rm = app_with_room_manager
    await avatar.start_voice_native(app, "my-agent", "sess-1", None)
    await avatar.stop_voice_native(app, "sess-1")
    rm.delete_dispatch.assert_awaited_once()
    assert "sess-1" not in app[avatar.AVATAR_VOICE_SESSIONS_KEY]


async def test_stop_voice_native_unknown_is_idempotent(app_with_room_manager):
    app, _ = app_with_room_manager
    await avatar.stop_voice_native(app, "does-not-exist")  # must not raise
```

---

## Agent Instructions

1. Read the spec (§2, §6) for full context.
2. Verify the Codebase Contract against `avatar.py` before editing.
3. Update index status → `in-progress`.
4. Implement per scope; keep the REST contract identical.
5. Run the tests + ruff; verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/` and update the index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Extracted `start_voice_native(app, agent_id, session_id, tenant_id) -> dict`
and `stop_voice_native(app, session_id) -> None` from `avatar.py`. All LiveAvatar
imports remain lazy. `_start_voice_native_session` now parses the request and
delegates to `start_voice_native`. `_stop_avatar_session` Phase C branch delegates to
`stop_voice_native`. 9 unit tests pass, no ruff errors.
**Deviations from spec**: none
