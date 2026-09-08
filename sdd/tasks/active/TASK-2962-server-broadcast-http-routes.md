# TASK-2962: Server HTTP API `/api/v1/agents/{agent_id}/voice-broadcasts` and manager wiring

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2961
**Parallel**: false
**Parallelism notes**: Only task editing `packages/ai-parrot-server` (new `handlers/voice_broadcast.py`, `manager/manager.py` wiring, one guard test on `handlers/avatar.py`).

---

## Context

Spec §2 "New Public Interfaces" table (Module 5): 11 endpoints with exact status codes and role checks, all through the same authorization service as the WebSocket. Also: "Review `handlers/avatar.py` for legacy viewer admission bypass; broadcast IDs must not be accepted via its unbounded token helper" (`_mint_viewer_tokens` mints up to 50 tokens for any `session_id` found in `app[AVATAR_SESSIONS_KEY]`).

## Scope

- `handlers/voice_broadcast.py`:
  - `register_voice_broadcast_routes(app: web.Application, service: BroadcastService, *, prefix: str = "/api/v1/agents/{agent_id}/voice-broadcasts", principal_resolver=None) -> None` — plain aiohttp handlers (so the example server in TASK-2963 can reuse them with a demo resolver). Default `principal_resolver` = `navigator_principal_resolver(request) -> ParticipantPrincipal` which reads `request.session or await get_session(request)` (pattern `handlers/agent.py:906`) and maps `user_id`, tenant (`session.get("tenant_id")`/program), `display_name`; unauthenticated ⇒ 401.
  - Endpoints & codes exactly per spec: `POST /` 201 (create, no credentials, no moderator claim); `GET /{bid}` 200 / 404 out-of-scope; `POST /{bid}/viewers` 201 `{lease_id, role, media_ready:false|true, public_state}` / 409 `viewer_limit_reached` / 410 terminal; `GET /{bid}/viewers/{lease}/connection` 200 `ViewerJoinResponse` / 409 retryable while starting / 403 not lease owner; `DELETE /{bid}/viewers/{lease}` 204 idempotent; `POST /{bid}/hands`, `DELETE /{bid}/hands/me` (admitted, own lease), `DELETE /{bid}/hands/{lease}` (moderator); `POST /{bid}/floor` body `{lease_id|null, expected_version}` 200 / 409 stale/switching (`{"reason":..., "state": public_state}`); `POST /{bid}/floor/release` (current speaker); `POST /{bid}/stop` 202 (moderator only; creator gets 403). Error bodies `{"error": <BroadcastReason>, "state": public_state?}`.
  - Hardening: JSON body ≤ 8 KiB, `Origin` allow-list from `PARROT_BROADCAST_ALLOWED_ORIGINS` (default same-origin), simple per-principal rate limit (token bucket 30 req/10 s) → 429; never echo tokens in logs; share link = `f"{base}/?broadcast={bid}"` (ID only).
- `manager/manager.py`: new `_register_voice_broadcast_routes(app) -> bool` next to `_register_voice_chat_routes` (`:1816`): lazy-import guard; builds `RedisBroadcastRegistry.from_url(os.environ["PARROT_BROADCAST_REDIS_URL"])`, `LiveKitRoomManager()`, a Nova `VoiceBot` factory (`VoiceConfig(provider=VoiceProvider.NOVA, model="nova-2-sonic", voice_name="matthew")`), `BroadcastService(...)`, passes it to `VoiceChatHandler(broadcast_service=service, nova_bot_factory=...)` (extend the existing instantiation at `:1839`), registers routes, starts the reconciler on `app.on_startup`, closes on `app.on_cleanup`. Skips with a warning when env is missing (server still boots).
- `handlers/avatar.py`: add a **test** asserting a broadcast room name never appears in `app[AVATAR_SESSIONS_KEY]` and therefore `_mint_viewer_tokens` returns 404 for it; if any code path in `BroadcastService` would write to that store, remove it. No functional change to `avatar.py` unless the test fails.
- Tests `packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py` with `aiohttp.test_utils` + a fake `BroadcastService` (or the real one over `InMemoryBroadcastRegistry`) and a stub resolver: every endpoint's success and each failure code; response bodies contain no `token`/`secret`/`ws_url` except `client_token` in `connection`; creator≠moderator 403 on stop.

**NOT in scope**: example server (TASK-2963), HTML, Redis integration tests (TASK-2967).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/voice_broadcast.py` | CREATE | Routes + navigator resolver |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `_register_voice_broadcast_routes` + call site near `:2194` |
| `packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py` | CREATE | Endpoint tests |
| `packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py` | MODIFY | Guard test: broadcast rooms not mintable via legacy helper |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                             # handlers/avatar.py:43
from navigator.views import BaseView                                 # handlers/avatar.py:45 (legacy class-based views; NOT required here)
from navigator_auth.decorators import is_authenticated, user_session # handlers/avatar.py:46
from navigator_session import get_session                            # handlers/agent.py:24 ; usage :906 `self.request.session or await get_session(self.request)`
from parrot.handlers.avatar import AVATAR_SESSIONS_KEY, _mint_viewer_tokens  # avatar.py:56, :560
from parrot.voice.handler import VoiceChatHandler                    # manager.py:1830 (lazy)
from parrot.integrations.liveavatar.broadcast.service import BroadcastService            # TASK-2961
from parrot.integrations.liveavatar.broadcast.redis_registry import RedisBroadcastRegistry  # TASK-2953
from parrot.integrations.liveavatar.broadcast.models import ParticipantPrincipal, BroadcastReason  # TASK-2951
from parrot.models.voice import VoiceConfig, VoiceProvider           # models/voice.py:55/:34 (NOVA = "nova" :51; VoiceConfig.model :78, voice_name :79)
from parrot.bots.voice import VoiceBot                               # bots/voice.py:89
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
def _register_voice_chat_routes(self, app: web.Application) -> bool   # :1816 ; handler = VoiceChatHandler() :1839 ; handler.setup_routes(app, include_health=False, include_static=False) :1840
def _register_avatar_routes(self, router) -> bool                     # :1844
self.app["bot_manager"] = self                                        # :2027
# call sites: self._register_voice_chat_routes(self.app) :2194 ; self._register_avatar_routes(router) :2199

# packages/ai-parrot-server/src/parrot/handlers/avatar.py
AVATAR_SESSIONS_KEY = "avatar_sessions"                               # :56
_VIEWERS_MAX_COUNT = 50                                               # :556
async def _mint_viewer_tokens(request) -> web.Response                # :560 (404 when session_id not in store :605-608; room = session_id :611)
def register_avatar_routes(router) -> bool                            # :656 (add_view ".../avatar/{agent_id}/{action}" and "/api/v1/avatar/{agent_id}/viewers")

# tests pattern: packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py:27 _make_request(body, app_store=...) — MagicMock request with .match_info/.json/.app
```

### Does NOT Exist
- ~~`handlers/voice_broadcast.py`, `_register_voice_broadcast_routes`~~ — new.
- ~~`request["user_id"]`~~ — navigator-auth never sets it (`agent.py:888-900` comment); use the session.
- ~~A moderator claim in `POST /`~~ — moderator is the first admitted participant only.
- ~~Returning `LiveKitRoomTokens` whole~~ — only `client_token` via `ViewerJoinResponse`.

## Implementation Notes

- Implement handlers as `async def` functions taking `request` and closing over `service`/`resolver`; map `errors.*` → status via one `_error_response(exc)` helper (`ViewerLimitReached→409`, `BroadcastTerminal→410`, `StaleVersion→409`, `NotModerator/NotSpeaker→403`, `BroadcastNotReady→409 Retry-After: 1`, unknown broadcast→404).
- Keep manager change minimal and guarded exactly like `_register_voice_chat_routes`.
- Origin/CSRF: for state-changing methods require `Origin` ∈ allow-list or same host; document in module docstring.

## Acceptance Criteria

- [ ] All 11 endpoints return the spec's codes in success/failure tests; bodies never include secret-like keys except `client_token` in `connection`.
- [ ] Creator who is not the first admitted participant gets 403 on `stop` and `floor`.
- [ ] `_mint_viewer_tokens` returns 404 for a broadcast room name (guard test).
- [ ] Server boots without `PARROT_BROADCAST_REDIS_URL` (routes skipped with warning); with it, routes + WS route registered (unit-test the register function with fakes).
- [ ] `pytest packages/ai-parrot-server/tests/handlers/test_voice_broadcast.py packages/ai-parrot-server/tests/handlers/test_avatar_viewers.py -q` green; `ruff check` clean.

## Test Specification

```python
@pytest.fixture
async def client(aiohttp_client): app = web.Application(); register_voice_broadcast_routes(app, fake_service, principal_resolver=stub_resolver); return await aiohttp_client(app)

async def test_create_returns_201_without_credentials(client): ...
async def test_eleventh_viewer_409(client): ...
async def test_connection_409_while_starting_then_200(client): ...
async def test_stop_requires_moderator_not_creator(client): ...
async def test_floor_stale_version_409_with_state(client): ...
async def test_no_secret_keys_in_any_response(client): ...
def test_legacy_viewer_helper_rejects_broadcast_room(): ...
```

## Agent Instructions
1. Read spec §2 "New Public Interfaces" table + hardening paragraph. 2. Verify anchors. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
