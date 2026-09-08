# TASK-2963: Extend the runnable example backend (`examples/clients/voice/server.py`) with broadcast mode

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2962
**Parallel**: false
**Parallelism notes**: Only task editing `examples/clients/voice/server.py`. TASK-2965 (HTML) and TASK-2968 (browser harness) depend on its `__CONFIG__.broadcast` contract.

---

## Context

Spec §2 "Reused HTML example and runnable backend": "`examples/clients/voice/server.py`: extend the existing runnable aiohttp app and Nova factory with the same authenticated broadcast service/routes, explicit `VoiceConfig` (`provider=NOVA`, `model="nova-2-sonic"`, compatible voice such as `matthew`, input16k/output24k), scoped principal mapping and shutdown hooks. Reuse FEAT-536's tool-aware factory, configuration and SDK asset route." Demo auth: "explicit localhost-only demo mode may map server-configured participant tokens to fixed scoped principals … Refuse non-loopback binding in demo mode … Keep a server-controlled failure-injection hook disabled by default." Module 6 backend half; AC15 (no second backend).

## Scope

- `server.py` (extend, do not fork):
  - `make_nova_bot()` (`:288`) — make the `VoiceConfig` explicit: `VoiceConfig(provider=VoiceProvider.NOVA, model="nova-2-sonic", voice_name="matthew", input_sample_rate=16000, output_sample_rate=24000)`; keep `NOVA_AVAILABLE` guard and `VoiceDemoWeatherTool`.
  - New `build_broadcast_service(app) -> BroadcastService | None`: env `VOICEBOT_BROADCAST_REDIS_URL` (required for broadcast mode; when unset → broadcast disabled, log why, page shows "Broadcast unavailable"), `LIVEKIT_*` (reuse `LiveKitRoomManager()`), `LIVEAVATAR_*` (already read by `VoiceAvatarSession.start`), `VOICEBOT_BROADCAST_WORKER_ID` (default `f"demo-{pid}"`).
  - Demo principals: `VOICEBOT_DEMO_PARTICIPANTS="alice:tokA,bob:tokB,..."` → `demo_principal_resolver(request)` reads `Authorization: Bearer <tok>` (or WS `Sec-WebSocket-Protocol: jwt, <tok>` via a `TokenValidator(validator_func=...)` so the **same** table authenticates the WS route) and maps to `ParticipantPrincipal(user_id=name, tenant_id="demo", agent_id="voice-assistant", display_name=name.title())`. No token ⇒ 401. Moderator/speaker authority still comes from admission/grants only.
  - Loopback guard: if demo participants are configured and `--host` is not `localhost`/`127.0.0.1`/`::1`, `main()` refuses to start with an actionable error (spec: "Refuse non-loopback binding in demo mode").
  - Wire `register_voice_broadcast_routes(app, service, principal_resolver=demo_principal_resolver)` and a third `VoiceChatHandler(bot_factory=make_nova_bot, broadcast_service=service, nova_bot_factory=make_nova_bot, require_auth=True, token_validator=demo_validator, ws_route="/ws/nova-broadcast", health_route="/health/broadcast")` whose `setup_routes` mounts `/ws/voice/broadcast/{agent_id}/{broadcast_id}`; `app.on_startup` starts `service.run_reconciler()`, `app.on_cleanup` stops it and closes the registry.
  - `index_handler` (`:362`) `cfg["broadcast"] = {"available": bool, "apiPrefix": "/api/v1/agents/voice-assistant/voice-broadcasts", "wsPath": "/ws/voice/broadcast/voice-assistant/{broadcast_id}", "agentId": "voice-assistant", "demoParticipants": [names only — never tokens], "unavailableReason": str|None}`. Broadcast mode is Nova-only for the broadcast's lifetime; the provider toggle must not affect a running broadcast (server side: the broadcast producer is independent of any socket).
  - Failure injection (disabled by default): env `VOICEBOT_BROADCAST_FAILURE_HOOK=1` enables `POST /__demo__/broadcasts/{bid}/inject` with `{"kind": "avatar_control_close"|"avatar_track_lost"|"owner_death"}` calling `service.inject_failure(...)` (add that method in the service **only** behind the same flag); route absent otherwise and never registered by `manager.py`.
- Tests `packages/ai-parrot-integrations/tests/voice/test_voice_demo_broadcast_backend.py` using the `_load_server_module()` pattern (`test_voice_demo_assets.py`/`test_voice_demo_avatar_browser.py:61`): config block shape, no tokens in `__CONFIG__`, 401 without demo token, loopback refusal, hook absent by default, Nova `VoiceConfig` explicit fields.

**NOT in scope**: HTML/JS (TASK-2964/2965), README/guide (TASK-2966), real vendor runs.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/server.py` | MODIFY | Broadcast service, demo auth, routes, config, guards |
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_broadcast_backend.py` | CREATE | Backend tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                                    # server.py:83
from parrot.bots import VoiceBot                                            # server.py:84
from parrot.models.voice import VoiceCapabilities, VoiceConfig, VoiceProvider  # server.py:87 (VoiceConfig fields models/voice.py:66-79: provider, input_sample_rate, output_sample_rate, model, voice_name)
from parrot.voice.handler import VoiceChatHandler                           # server.py:89 (+ TASK-2959/2960/2961 kwargs broadcast_service, nova_bot_factory)
from parrot.core.ws_auth import TokenValidator                              # ws_auth.py:44 (validator_func=callable(token)->dict|None ; validate() builds AuthenticatedUser from user_id/username :77-104)
from parrot.handlers.voice_broadcast import register_voice_broadcast_routes # TASK-2962 (ai-parrot-server is a workspace sibling; import lazily inside build_broadcast_service with an actionable ImportError message)
from parrot.integrations.liveavatar.broadcast.service import BroadcastService                 # TASK-2961
from parrot.integrations.liveavatar.broadcast.redis_registry import RedisBroadcastRegistry    # TASK-2953
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager                    # room_manager.py:47
```

### Existing Signatures to Use
```python
# examples/clients/voice/server.py
_ENV_FILE = Path(__file__).resolve().parents[3] / "env" / ".env"          # :73 (loaded before parrot imports)
STATIC_DIR, INDEX_ASSET = static/, static/dual_provider.html               # :97-98
class VoiceDemoWeatherTool(AbstractTool)                                   # :128
NOVA_AVAILABLE / NOVA_UNAVAILABLE_REASON                                   # :194-198
_LIVEKIT_UMD_ROUTE = "/voice-assets/livekit-client.umd.js"; voice_assets_livekit_handler  # :213, :246
def make_gemini_bot() -> VoiceBot; def make_nova_bot() -> VoiceBot         # :278, :288 (VoiceConfig(provider=VoiceProvider.NOVA, voice_name="matthew"))
def build_capabilities() -> dict                                           # :330
async def index_handler(request) -> web.Response                           # :362 (cfg = {"providers": {...}, "capabilities": ..., "avatar": {"sdkUrl", "available"}}; replaces "window.__CONFIG__ = __CONFIG__;" once :395-399)
def build_app() -> web.Application                                         # :407 (two VoiceChatHandler(bot_factory=..., ws_route=..., health_route=...); setup_routes(app, include_static=False); add_get("/"), add_static("/static/"), add_get(_LIVEKIT_UMD_ROUTE))
def parse_args(); def main()                                               # :442 (--host default "localhost", --port 8080), :452
```
- Test loader pattern: `tests/voice/test_voice_demo_avatar_browser.py:61 _load_server_module()`.

### Does NOT Exist
- ~~`app["bot_manager"]` in the example~~ — that is `manager.py:2027` only.
- ~~A second HTML/backend~~ — forbidden (AC15).
- ~~Broadcast without Redis~~ — spec: production and the runnable example use Redis; in-memory registry is for unit tests only.
- ~~Failure-injection route in production `manager.py`~~ — forbidden.

## Implementation Notes

- Keep the existing Gemini/Nova single-user handlers untouched; the broadcast handler is a third instance.
- `demo_validator = TokenValidator(validator_func=lambda tok: {"user_id": name, "username": name} if tok in table else None)`.
- `__CONFIG__` must stay JSON-serialisable and contain **no** tokens; verify with a test that walks the dict.

## Acceptance Criteria

- [ ] `build_app()` without `VOICEBOT_BROADCAST_REDIS_URL` still serves Gemini/Nova routes and `cfg["broadcast"]["available"] is False` with reason.
- [ ] With env set (registry patched to in-memory in tests), REST prefix + `/ws/voice/broadcast/...` are mounted; unauthenticated `POST /api/v1/agents/voice-assistant/voice-broadcasts` ⇒ 401; with `Bearer tokA` ⇒ 201.
- [ ] `main()` refuses `--host 0.0.0.0` when demo participants are configured.
- [ ] Failure-injection route 404 by default, present only with the flag.
- [ ] `make_nova_bot().voice_config` has `provider=NOVA, model="nova-2-sonic", voice_name="matthew", input_sample_rate=16000, output_sample_rate=24000`.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_demo_broadcast_backend.py packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py -q` green; `ruff check examples/clients/voice/server.py` clean.

## Test Specification

```python
def test_config_broadcast_block_has_no_tokens(monkeypatch): ...
async def test_broadcast_unavailable_without_redis(aiohttp_client): ...
async def test_demo_bearer_required(aiohttp_client, monkeypatch): ...
def test_refuses_non_loopback_in_demo_mode(monkeypatch): ...
def test_nova_voice_config_explicit(): ...
```

## Agent Instructions
1. Read spec §2 "Reused HTML example and runnable backend" (all paragraphs). 2. Verify anchors (server.py may have shifted). 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
