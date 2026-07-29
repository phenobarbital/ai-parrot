---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar FULL Mode — ai-parrot as the brain via OpenAI-compatible streaming

**Feature ID**: FEAT-247
**Date**: 2026-06-18
**Author**: Jesús Lara (design w/ Claude)
**Status**: approved
**Target version**: (next minor)

> **Provenance.** This spec **revisits Option B** of
> `sdd/proposals/liveavatar-integration.brainstorm.md`, which the brainstorm
> *deferred* in favour of the A→C path. It is now adopted **as a separate,
> parallel avatar mode** by explicit user decision — NOT a replacement for
> Phase A (FEAT-242) or Phase C (FEAT-243), which keep working.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-248 (`liveavatar-fullmode-speaktext`) built the full-mode session
lifecycle: `FullModeConfig`, `FullModeSessionHandle`, FULL mode client
extension, REST handlers (`/api/v1/avatar/fullmode/{agent_id}/start|stop`),
per-tenant config resolver, opt-in gate (`is_fullmode_enabled`), room observer,
and the Mode-B bifurcation in `AgentTalk` (`avatar_bifurcate=True` →
`_maybe_publish_bifurcated_output`). All on `dev`.

In that architecture the **frontend** drives the conversation loop: it calls
`agent.ask` via the AgentTalk WebSocket, receives the response, and sends
`avatar.speak_text` over the LiveKit data channel. This works but requires the
frontend to orchestrate the LLM↔avatar relay.

LiveAvatar's **Custom LLM Integration** offers a simpler path: LiveAvatar calls
**our LLM directly** via an OpenAI-compatible streaming endpoint. The frontend
only joins the LiveAvatar room — no relay code, no `speak_text` orchestration.

ai-parrot has **no OpenAI-compatible surface** today. This spec adds it.

### Goals
- Expose an **OpenAI-compatible streaming chat-completions endpoint**
  (`POST /v1/chat/completions/<session_id>`, SSE `stream=true`) backed by
  ai-parrot `ask_stream`, that LiveAvatar FULL Mode can call as its Custom LLM.
- Reuse the existing bifurcation (`_maybe_publish_bifurcated_output` in
  `agent.py`) so structured outputs still reach the AgentChat WS channel.
- Wire the endpoint into the existing FULL mode start flow so `/full/start`
  returns the per-session custom-LLM URL to LiveAvatar.

### Non-Goals (explicitly out of scope)
- Replacing Phase A (FEAT-242) or Phase C (FEAT-243). FULL Mode is an
  **additional** avatar mode; the others remain.
- Bringing our own STT/TTS — that is exactly what FULL Mode avoids.
- Full OpenAI API fidelity. v1 implements `messages[]` + `stream=true` (and a
  minimal `GET /v1/models`). Function-calling/tools over the OpenAI wire,
  `n>1`, logprobs, image inputs, etc. are out of scope.
- FULL mode session lifecycle, bifurcation, opt-in, tenant config, room
  observer — **all already built by FEAT-248**.

---

## 2. Architectural Design

### What FEAT-248 Already Built (reuse, do not rebuild)

| Component | Location | What it does |
|---|---|---|
| `FullModeConfig` / `FullModeSessionHandle` | `liveavatar/models.py` | Data models for FULL mode sessions |
| `LiveAvatarClient` FULL mode sessions | `liveavatar/client.py` | Mints FULL sessions via LiveAvatar API |
| Start/stop REST handlers | `handlers/avatar_fullmode.py` | `/api/v1/avatar/fullmode/{agent_id}/start\|stop` |
| Per-tenant config resolver | `liveavatar/tenant_config.py` | Env defaults + DB overrides |
| Opt-in gate | `liveavatar/optin.py:is_fullmode_enabled` | Tenant allowlist for FULL mode |
| Room observer | `liveavatar/room_manager.py` | Passive LiveKit room participant |
| Mode-B bifurcation | `handlers/agent.py:_maybe_publish_bifurcated_output` | Structured output via Redis when `avatar_bifurcate=True` |
| `OutputBridge` / `SpeakableFlattener` | `liveavatar/output_bridge.py`, `liveavatar/speakable.py` | Speech/structured split |
| Manager wiring | `manager/manager.py:_register_fullmode_avatar_routes` | Route registration + shutdown cleanup |

### What This Spec Adds

LiveAvatar FULL Mode with Custom LLM configured with a **per-session URL**
pointing at ai-parrot. When the user speaks, LiveAvatar does STT and POSTs an
OpenAI-style chat-completions request (streaming) to our endpoint. The endpoint:

1. Extracts `session_id` from the URL path and `agent_name` from the query
   param (per-session URL minted by `/full/start`).
2. Extracts the last user message and calls `bot.ask_stream(question, session_id, ...)`.
3. For each `str` chunk → emits an OpenAI `chat.completion.chunk` SSE delta
   (LiveAvatar accumulates these and speaks them through its TTS → avatar).
4. For the final `AIMessage` → reuses `_maybe_publish_bifurcated_output` to
   publish structured outputs to the WS side channel.
5. Closes the stream with `finish_reason:"stop"` + `data: [DONE]`.

### Component Diagram
```
[Browser] ── POST /fullmode/start {agent} ─▶ [ai-parrot server]  (FEAT-248, exists)
   │                                           └─ mints session_id, returns:
   │                                              - LiveKit viewer creds (exists)
   │                                              - custom_llm_url: /v1/chat/completions/<session_id>?agent=<name> (NEW)
   │ ◀── {viewer creds, custom_llm_url} ──────┘
   │ join LiveAvatar FULL session (LiveAvatar-hosted room)
   │  ── mic ─▶ [LiveAvatar STT] ─▶ POST /v1/chat/completions/<session_id> ─▶ [OpenAIChatCompat]  (NEW)
   │                                   Authorization: Bearer <token>             │ ask_stream(agent, q, session_id)
   │                                                          speakable str ◀────┤ (SSE deltas → LiveAvatar TTS)
   │                                                          structured  ──────▶ _maybe_publish_bifurcated_output (exists)
   │ ◀══ avatar video+voice (LiveAvatar) ══                      │                  → OutputBridge → Redis → /ws/user
   │ ◀══ structured artifacts via /ws/user (channel=session_id) ═┘
   │ POST /fullmode/stop {session_id} ─▶ teardown  (FEAT-248, exists)
```

### Data Models
```python
# OpenAI-compatible request (subset we honour) — NEW
class ChatMessage(BaseModel):
    role: str          # "system" | "user" | "assistant"
    content: str
class ChatCompletionRequest(BaseModel):
    model: str                       # informational (agent resolved from URL)
    messages: list[ChatMessage]
    stream: bool = False
    # tolerated-but-ignored: temperature, top_p, max_tokens, etc.

# Streaming chunk we emit (OpenAI chat.completion.chunk shape):
# {"id","object":"chat.completion.chunk","created","model",
#  "choices":[{"index":0,"delta":{"content": "..."},"finish_reason":null}]}
```

### New Public Interfaces
```python
# packages/ai-parrot-server/src/parrot/handlers/openai_compat.py  — NEW
class OpenAIChatCompletions(BaseView):
    async def post(self) -> web.StreamResponse: ...   # SSE when stream=true, JSON otherwise
class OpenAIModels(BaseView):
    async def get(self) -> web.Response: ...          # minimal {data:[{id: <agent>}]}
```

### Integration Points (existing components consumed)

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.ask_stream()` | uses | Token/`AIMessage` stream feeding the SSE bridge |
| `_maybe_publish_bifurcated_output` (`handlers/agent.py`) | reuses | Structured output → Redis → WS (FEAT-249 Mode B) |
| `SpeakableFlattener` (`liveavatar/speakable.py`) | reuses | Markdown→speakable before SSE deltas |
| `BotManager` bot resolver | uses | Resolve `agent_name` → bot in-process |
| `FULLMODE_SESSIONS_KEY` store (`avatar_fullmode.py`) | reads | Validate session_id is an active FULL mode session |
| aiohttp router (`manager.setup`) | adds routes | `/v1/chat/completions/{session_id}`, `/v1/models` |

---

## 3. Module Breakdown

### Module 1: OpenAI-compatible streaming endpoint (NEW)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/openai_compat.py`
- **Responsibility**: `POST /v1/chat/completions/{session_id}` — validate
  bearer token, look up `session_id` in `FULLMODE_SESSIONS_KEY`, resolve
  agent from `?agent=` query param via `BotManager`, extract last user
  message, call `ask_stream`, run through `SpeakableFlattener`, emit
  `chat.completion.chunk` SSE deltas for speakable text, publish structured
  outputs via `_maybe_publish_bifurcated_output`, terminate with `[DONE]`.
  Non-stream fallback returns a single JSON completion.
  Minimal `GET /v1/models`.
- **Depends on**: `ask_stream` (existing), bot resolver (existing),
  `SpeakableFlattener` (FEAT-248), `_maybe_publish_bifurcated_output`
  (FEAT-249 Mode B), `FULLMODE_SESSIONS_KEY` (FEAT-248).

### Module 2: Start-flow wiring (MODIFY existing)
- **Path**: `handlers/avatar_fullmode.py` (modify start handler)
- **Responsibility**: When `/full/start` mints a FULL mode session, also
  compute and return the `custom_llm_url` (per-session URL:
  `{base}/v1/chat/completions/{session_id}?agent={agent_name}`) in the
  response payload so the frontend can pass it to LiveAvatar's Custom LLM
  config. Pass `custom_llm_url` to `LiveAvatarClient.create_full_session`
  if LiveAvatar needs it at session creation time.
- **Depends on**: Module 1 (route must exist).

### Module 3: Route registration (MODIFY existing)
- **Path**: `manager/manager.py`
- **Responsibility**: Register the OpenAI-compat routes
  (`/v1/chat/completions/{session_id}`, `/v1/models`) alongside the
  existing FULL mode routes.

### ~~Module 2 (original): Turn bifurcation~~ — ALREADY BUILT (FEAT-249 Mode B)
### ~~Module 3 (original): FULL-mode session lifecycle~~ — ALREADY BUILT (FEAT-248)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_chat_completions_streams_deltas` | M1 | `stream=true` → SSE `chat.completion.chunk` deltas for each speakable chunk, ending `[DONE]` (fake bot) |
| `test_chat_completions_non_stream_json` | M1 | `stream=false` → single JSON completion |
| `test_chat_completions_resolves_agent_and_session` | M1 | `session_id` from URL path + `agent` from query param passed to `ask_stream` |
| `test_chat_completions_auth_required` | M1 | Missing/invalid bearer token → 401 |
| `test_chat_completions_unknown_session` | M1 | `session_id` not in `FULLMODE_SESSIONS_KEY` → 404 |
| `test_models_endpoint` | M1 | `GET /v1/models` returns available agents |
| `test_start_returns_custom_llm_url` | M2 | `/full/start` response includes `custom_llm_url` with session_id and agent |

### Integration Tests
| Test | Description |
|---|---|
| `test_openai_compat_against_openai_sdk` | The `openai` Python SDK pointed at our per-session URL streams a completion successfully (contract conformance). |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_bot():
    class _Bot:
        name = "pokemon_analyst"
        async def ask_stream(self, question, session_id=None, **kw):
            yield "Pikachu is "
            yield "an Electric type."
            yield AIMessage(response="", data={"hp": 35}, output_mode=OutputMode.DEFAULT)
    return _Bot()
```

---

## 5. Acceptance Criteria

- [ ] `POST /v1/chat/completions/{session_id}` with `stream=true` returns valid
      OpenAI `chat.completion.chunk` SSE and terminates with `data: [DONE]`; the
      official `openai` SDK can consume it.
- [ ] Each speakable `ask_stream` chunk becomes a streamed delta; the final
      `AIMessage`'s speakable `response` is also spoken.
- [ ] Structured outputs are published via the existing
      `_maybe_publish_bifurcated_output` path and **never** crash the spoken stream.
- [ ] `/full/start` response includes `custom_llm_url` with the per-session
      endpoint URL.
- [ ] Endpoint authenticates server-to-server calls via bearer token.
- [ ] Unknown `session_id` (not in `FULLMODE_SESSIONS_KEY`) returns 404.
- [ ] Existing FEAT-248 FULL mode behaviour and FEAT-242/243 behaviour unchanged.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verify before `/sdd-task`.
> Updated 2026-07-22 to reflect FEAT-248/FEAT-249 artifacts already on `dev`.

### Verified Imports
```python
# AbstractBot.ask_stream — the streaming interface we wrap
from parrot.bots.base import AbstractBot  # .ask_stream() → AsyncIterator[str | AIMessage]

# FEAT-248 FULL mode infrastructure (all on dev)
from parrot.integrations.liveavatar import LiveAvatarClient, FullModeConfig, FullModeSessionHandle
from parrot.integrations.liveavatar.speakable import SpeakableFlattener
from parrot.integrations.liveavatar.optin import is_fullmode_enabled

# FEAT-249 Mode-B bifurcation (on dev, in handlers/agent.py)
# AgentTalk._maybe_publish_bifurcated_output — reuse pattern, not import directly

# FEAT-248 session store key
from parrot.handlers.avatar_fullmode import FULLMODE_SESSIONS_KEY

# AIMessage / OutputMode
from parrot.models.responses import AIMessage
```

### Existing Signatures (FEAT-248, on dev)
```python
# liveavatar/models.py
class FullModeConfig(LiveAvatarConfig): ...        # :131
class FullModeSessionHandle(AvatarSessionHandle): ...  # :160

# liveavatar/optin.py
def is_fullmode_enabled(tenant_id, agent_name=None) -> bool  # :121

# handlers/avatar_fullmode.py
FULLMODE_SESSIONS_KEY = ...                        # app-level dict of active sessions
def register_fullmode_routes(router) -> bool       # registers start/stop routes
async def close_all_fullmode_sessions(app) -> None # shutdown cleanup

# handlers/agent.py (FEAT-249 Mode B)
# AgentTalk._maybe_publish_bifurcated_output(session_id, ai_message, ...) — private method
```

### Does NOT Exist (Anti-Hallucination)
- ~~Any `/v1/chat/completions` or OpenAI-compatible endpoint~~ — **confirmed absent**
  (grep 2026-07-22); this feature creates it.
- ~~An OpenAI-compat request/response model~~ — must be created
  (`ChatCompletionRequest`, `ChatMessage`).
- ~~`custom_llm_url` in `/full/start` response~~ — start handler does not
  return it today; Module 2 adds it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- aiohttp `web.StreamResponse` for SSE; `Content-Type: text/event-stream`,
  flush per delta (mirror the streaming pattern in `AgentTalk._handle_stream_response`).
- Reuse the existing `_maybe_publish_bifurcated_output` for structured outputs
  rather than re-deriving bifurcation logic.
- Async-first; `self.logger`; Pydantic for request/response models; graceful
  degradation (bridge errors non-fatal), all per CLAUDE.md.
- Validate `session_id` against `FULLMODE_SESSIONS_KEY` — reject requests for
  sessions that aren't active FULL mode sessions.
- Bearer token auth for server-to-server calls from LiveAvatar.

### Known Risks / Gotchas
- **Structured outputs are invisible to voice**: a turn that is *only* a chart
  produces no speech — emit a short spoken filler so the avatar isn't mute.
- **Barge-in / turn-taking** is LiveAvatar's responsibility in FULL mode; verify
  their behaviour during long `ask_stream` turns.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | SSE streaming endpoint (project standard) |
| `openai` (dev/test only) | any | Contract-conformance test of our endpoint |
| LiveAvatar FULL Mode / Custom LLM | n/a (their service) | Hosts STT+TTS+video, calls our LLM |

---

## 8. Open Questions

- [x] **How do `session_id` + `agent_name` travel** from LiveAvatar's Custom-LLM
      call into `/v1/chat/completions`? — *Resolved 2026-07-22*: **Per-session
      minted URL** (Option B). `/full/start` returns a unique endpoint like
      `/v1/chat/completions/<session_id>?agent=<agent_name>` as the custom LLM
      base URL. No encoding hacks, no dependency on LiveAvatar header forwarding.
- [x] **FULL-mode transport**: does the browser join a LiveAvatar-hosted room, or
      is BYO LiveKit still involved? — *Resolved 2026-07-22*: **LiveAvatar-hosted
      room**. Browser joins LiveAvatar's transport directly; no BYO LiveKit.
- [x] **Server-to-server auth** scheme LiveAvatar supports for the custom-LLM URL.
      — *Resolved 2026-07-22*: **Bearer token** auth.
- [x] Q-skills: install LiveAvatar Agent Skills before implementation?
      — *Resolved 2026-07-22*: **No**, not needed.
- [x] TTS for the avatar — *Resolved (mode choice)*: in FULL mode the **TTS is
      LiveAvatar's**, by definition (no own TTS, no Supertonic). Our-infra TTS is
      the Option-C concern (FEAT-246), not this spec.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential). Small scope (3 modules, one
  new file + two modifications) — no worktree needed, direct branch from `dev`.
- **Cross-feature dependencies**: depends on FEAT-248 (FULL mode lifecycle)
  and FEAT-249 Mode B (bifurcation), both already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-18 | Jesús Lara (w/ Claude) | Initial draft — revisits brainstorm Option B (FULL Mode + Custom LLM) as a parallel avatar mode |
| 0.2 | 2026-07-22 | Jesús Lara (w/ Claude) | Scoped down: FEAT-248 already built session lifecycle, bifurcation, opt-in, tenant config, room observer. Remaining scope is the OpenAI-compat endpoint (M1), start-flow wiring (M2), route registration (M3). Resolved all open questions. Status → approved. |
