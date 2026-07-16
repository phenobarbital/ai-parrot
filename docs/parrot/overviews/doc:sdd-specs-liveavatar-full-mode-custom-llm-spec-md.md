---
type: Wiki Overview
title: 'Feature Specification: LiveAvatar FULL Mode — ai-parrot as the brain via OpenAI-compatible
  streaming'
id: doc:sdd-specs-liveavatar-full-mode-custom-llm-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase C (FEAT-243, "Option C") gives a fluent voice-native avatar but at
  the
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.speakable
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar FULL Mode — ai-parrot as the brain via OpenAI-compatible streaming

**Feature ID**: FEAT-247
**Date**: 2026-06-18
**Author**: Jesús Lara (design w/ Claude)
**Status**: draft
**Target version**: (next minor)

> **Provenance.** This spec **revisits Option B** of
> `sdd/proposals/liveavatar-integration.brainstorm.md`, which the brainstorm
> *deferred* in favour of the A→C path. It is now adopted **as a separate,
> parallel avatar mode** by explicit user decision — NOT a replacement for
> Phase A (FEAT-242) or Phase C (FEAT-243), which keep working.

---

## 1. Motivation & Business Requirements

### Problem Statement

Phase C (FEAT-243, "Option C") gives a fluent voice-native avatar but at the
cost of **running our own real-time voice pipeline** (STT + VAD + turn-detection
+ TTS) inside a LiveKit Agents worker. That is a lot of infrastructure to
operate, tune (barge-in, plugins, provider keys) and pay for.

LiveAvatar's **FULL Mode** runs the *entire* pipeline (STT + TTS + lip-synced
video) on **their** infra and calls **our LLM** through its "Custom LLM
Integration". If ai-parrot exposes an **OpenAI-compatible streaming
chat-completions endpoint**, LiveAvatar does "ai-parrot is the brain, the avatar
hears and talks" with **no LiveKit worker, no PCM plumbing, no own STT/TTS** —
the minimal-our-infra path the team originally pictured for a talking-agent.

The brainstorm deferred this because (a) ai-parrot has **no OpenAI-compatible
surface** today and (b) **structured outputs (charts/data/canvas/tool_calls)
do not fit the OpenAI chat stream**, so they need a side channel. Both are
solvable: this spec builds the OpenAI-compat streaming endpoint and reuses the
FEAT-243 `StructuredOutputMessage` side channel (Redis→WS, keyed by
`session_id`) so artifacts still reach the AgentChat UI while LiveAvatar speaks.

### Goals
- Expose an **OpenAI-compatible streaming chat-completions endpoint**
  (`POST /v1/chat/completions`, SSE `stream=true`) backed by ai-parrot
  `ask_stream`, that LiveAvatar FULL Mode can call as its Custom LLM.
- **Bifurcate** the turn: speakable text rides the OpenAI SSE stream (→ LiveAvatar
  TTS → avatar speaks); structured outputs are published to the AgentChat WS
  channel keyed by `session_id` (reuse FEAT-243 `OutputBridge` /
  `StructuredOutputMessage`).
- Add **LiveAvatar FULL Mode** session support to `LiveAvatarClient` (today it
  only mints LITE sessions) plus browser start/stop endpoints.
- Keep our infra footprint minimal: **no LiveKit worker, no own STT/TTS** in this
  mode.

### Non-Goals (explicitly out of scope)
- Replacing Phase A (FEAT-242) or Phase C (FEAT-243). FULL Mode is an
  **additional** avatar mode; the others remain.
- Bringing our own STT/TTS — that is exactly what FULL Mode avoids (and what
  FEAT-246 covers for Option C). Voice quality/voices here are **LiveAvatar's**.
- Full OpenAI API fidelity. v1 implements `messages[]` + `stream=true` (and a
  minimal `GET /v1/models`). Function-calling/tools over the OpenAI wire,
  `n>1`, logprobs, image inputs, etc. are out of scope (ai-parrot runs its own
  tools internally; their *outputs* go via the side channel).
- Accepting vendor lock-in silently: this mode trades pipeline control for
  simplicity by design (documented tradeoff, per brainstorm Option B cons).

---

## 2. Architectural Design

### Overview

LiveAvatar FULL Mode is configured with a **Custom LLM** base URL pointing at
ai-parrot. When the user speaks, LiveAvatar does STT and POSTs an
OpenAI-style chat-completions request (streaming) to our endpoint. The endpoint:

1. Resolves the target ai-parrot agent and the conversation `session_id`
   (carried via the request — see Open Questions for the exact channel).
2. Extracts the last user message and calls `bot.ask_stream(question, session_id, ...)`.
3. For each `str` chunk → emits an OpenAI `chat.completion.chunk` SSE delta
   (LiveAvatar accumulates these and speaks them through its TTS → avatar).
4. For the final `AIMessage` → if it carries **structured output** (tool_calls /
   data / artifact_id / non-default output_mode), publishes a
   `StructuredOutputMessage` to the AgentChat WS channel (`session_id`) via the
   existing bridge; speakable `response` text still goes out as SSE deltas.
5. Closes the stream with `finish_reason:"stop"` + `data: [DONE]`.

The browser, meanwhile, joins LiveAvatar's FULL-mode session (their hosted
transport) to see/hear the avatar, and subscribes to the AgentChat WS channel
(`session_id`) to render structured artifacts — identical UI contract to Phase C.

### Component Diagram
```
[Browser] ── POST /full/start {session_id, agent} ─▶ [ai-parrot server]
   │                                                   └─ LiveAvatarClient.create_full_session(custom_llm_url, session_id)
   │ ◀── {viewer creds} ──────────────────────────────┘
   │ join LiveAvatar FULL session (their STT/TTS/video transport)
   │  ── mic ─▶ [LiveAvatar infra: STT] ─▶ POST /v1/chat/completions (stream) ─▶ [OpenAIChatCompat handler]
   │                                                                                 │ ask_stream(agent, q, session_id)
   │                                                              speakable str ◀────┤ (SSE deltas → LiveAvatar TTS → avatar speaks)
   │                                                              structured  ──────▶ OutputBridge → Redis → /ws/user (channel=session_id)
   │ ◀══ avatar video+voice (LiveAvatar) ══                          │
   │ ◀══ structured artifacts via /ws/user (channel=session_id) ═════┘
   │ POST /full/stop {session_id} ─▶ teardown
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.ask_stream()` (`bots/base.py:1456`) | uses | Token/`AIMessage` stream feeding the SSE bridge |
| `StructuredOutputMessage` (`livekit_agent/models.py:42`) | reuses | Side-channel contract (charts/data/canvas/tool_call) |
| `OutputBridge.publish()` (`output_bridge.py:39`) | reuses | Publishes structured outputs (Redis→WS) |
| `UserSocketManager.broadcast_to_channel` (`handlers/user.py:357`) | reuses | Delivery to the browser on `session_id` channel |
| FEAT-243 bifurcation (`livekit_agent/agent.py` `_is_structured`/`_classify`/`_structured_payload`) | reuses/refactors | Same speech-vs-structured split — factor into a shared helper |
| `SpeakableFlattener` (`liveavatar/speakable.py`) | reuses | Markdown→speakable before SSE deltas |
| `LiveAvatarClient` (`liveavatar/client.py`) | extends | Add FULL-mode session creation (today hardcodes `"mode":"LITE"` at :146) |
| `BotManager` bot resolver (FEAT-243) | uses | Resolve `agent_name` → bot in-process |
| aiohttp router (`manager.setup`) | adds routes | `/v1/chat/completions`, `/v1/models`, `/api/v1/agents/avatar/{agent}/full/{start,stop}` |

### Data Models
```python
# OpenAI-compatible request (subset we honour)
class ChatMessage(BaseModel):
    role: str          # "system" | "user" | "assistant"
    content: str
class ChatCompletionRequest(BaseModel):
    model: str                       # encodes/identifies the ai-parrot agent (see Open Q)
    messages: list[ChatMessage]
    stream: bool = False
    # tolerated-but-ignored: temperature, top_p, max_tokens, etc.

# Streaming chunk we emit (OpenAI chat.completion.chunk shape):
# {"id","object":"chat.completion.chunk","created","model",
#  "choices":[{"index":0,"delta":{"content": "..."},"finish_reason":null}]}
```

### New Public Interfaces
```python
# packages/ai-parrot-server/src/parrot/handlers/openai_compat.py
class OpenAIChatCompletions(BaseView):
    async def post(self) -> web.StreamResponse: ...   # SSE when stream=true, JSON otherwise
class OpenAIModels(BaseView):
    async def get(self) -> web.Response: ...          # minimal {data:[{id: <agent>}]}

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py
class LiveAvatarClient:
    async def create_full_session(self, cfg, *, custom_llm_url: str,
                                  session_id: str, ...) -> AvatarSessionHandle: ...
```

---

## 3. Module Breakdown

### Module 1: OpenAI-compatible streaming endpoint
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/openai_compat.py`
- **Responsibility**: `POST /v1/chat/completions` — parse the OpenAI request,
  resolve agent + `session_id`, call `ask_stream`, emit `chat.completion.chunk`
  SSE deltas for speakable text, terminate with `[DONE]`. Non-stream fallback
  returns a single JSON completion. Minimal `GET /v1/models`. Authenticated for
  server-to-server calls from LiveAvatar (shared secret / API key — see Open Q).
- **Depends on**: `ask_stream` (existing), bot resolver (FEAT-243).

### Module 2: Turn bifurcation + structured-output side channel
- **Path**: shared helper, e.g.
  `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/turn_bifurcation.py`
  (factored from FEAT-243 `agent.py`), consumed by Module 1.
- **Responsibility**: Run `ask_stream` output through `SpeakableFlattener`
  (speakable text → caller yields as SSE deltas) and detect structured
  `AIMessage`s (`_is_structured`/`_classify`/`_structured_payload`) → build a
  `StructuredOutputMessage` and `OutputBridge.publish` it on `session_id`. Bridge
  failures are non-fatal to the spoken stream (mirror FEAT-243).
- **Depends on**: `SpeakableFlattener`, `OutputBridge`, `StructuredOutputMessage`
  (all existing); refactors FEAT-243 logic without breaking the worker.

### Module 3: LiveAvatar FULL-mode session + browser endpoints
- **Path**: `liveavatar/client.py` (extend), `handlers/avatar.py` (add routes),
  `manager/manager.py` (register).
- **Responsibility**: Add `create_full_session(...)` to `LiveAvatarClient`
  (`"mode":"FULL"` + custom-LLM config = our `/v1/chat/completions` URL, model =
  agent). Add `POST /api/v1/agents/avatar/{agent}/full/start` (mints viewer
  creds + opens a FULL session, opt-in gated like Phase A/C) and reuse the
  shared `/stop`. Register the OpenAI-compat routes + FULL routes in
  `manager.setup`, opt-in via env (e.g. `ENABLE_LIVEAVATAR_FULL`).
- **Depends on**: Modules 1 & 2; FEAT-242/243 opt-in + session-store patterns.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_chat_completions_streams_deltas` | M1 | `stream=true` → SSE `chat.completion.chunk` deltas for each speakable chunk, ending `[DONE]` (fake bot) |
| `test_chat_completions_non_stream_json` | M1 | `stream=false` → single JSON completion |
| `test_chat_completions_resolves_agent_and_session` | M1 | agent + `session_id` extracted from the request and passed to `ask_stream` |
| `test_chat_completions_auth_required` | M1 | Unauthenticated/no-secret call rejected |
| `test_models_endpoint` | M1 | `GET /v1/models` returns the agent id |
| `test_bifurcation_speakable_vs_structured` | M2 | speakable text yielded; structured `AIMessage` → `OutputBridge.publish` with correct `type`/`payload` |
| `test_bifurcation_bridge_error_nonfatal` | M2 | bridge failure logged, speech stream continues |
| `test_bifurcation_parity_with_feat243` | M2 | refactored helper matches FEAT-243 `agent.py` classification on shared fixtures |
| `test_client_create_full_session_payload` | M3 | builds `"mode":"FULL"` + custom-LLM url/model payload (fake HTTP) |
| `test_full_start_optin_gate` | M3 | `403` when tenant not opted in; `503` when stack/env missing |

### Integration Tests
| Test | Description |
|---|---|
| `test_full_mode_roundtrip_sandbox` | LiveAvatar FULL session calls `/v1/chat/completions`; speakable text spoken; structured output arrives on `/ws/user` channel=`session_id`; `is_sandbox=true`. Requires the `liveavatar` extra + live LiveAvatar FULL access (integration, not unit). |
| `test_openai_compat_against_openai_sdk` | The `openai` Python SDK pointed at our base URL streams a completion successfully (contract conformance). |

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

- [ ] `POST /v1/chat/completions` with `stream=true` returns valid OpenAI
      `chat.completion.chunk` SSE and terminates with `data: [DONE]`; the official
      `openai` SDK can consume it.
- [ ] Each speakable `ask_stream` chunk becomes a streamed delta; the final
      `AIMessage`'s speakable `response` is also spoken.
- [ ] Structured outputs (tool_calls / data / artifact_id / non-default
      output_mode) are published as `StructuredOutputMessage` on the `/ws/user`
      channel keyed by `session_id`, and **never** crash the spoken stream.
- [ ] `LiveAvatarClient.create_full_session` produces a FULL-mode payload wired to
      our custom-LLM URL; `POST /api/v1/agents/avatar/{agent}/full/start` opens it
      (opt-in gated) and `/stop` tears it down idempotently.
- [ ] This mode runs with **no LiveKit worker and no own STT/TTS** process.
- [ ] FEAT-243 (Phase C) and FEAT-242 (Phase A) behaviour is unchanged
      (shared bifurcation refactor keeps the worker's tests green).
- [ ] Endpoint authenticates server-to-server calls from LiveAvatar.
- [ ] Frontend/operator docs explain FULL mode, the `session_id` glue, the
      structured-output side channel, and the documented tradeoff vs Phase C.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verify before use.

### Verified Imports
```python
# verified: packages/ai-parrot/src/parrot/bots/base.py:1456
#   AbstractBot.ask_stream(...) -> AsyncIterator[Union[str, AIMessage]]
# verified: livekit_agent/models.py:42
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage
# verified: liveavatar/output_bridge.py:25,39
from parrot.integrations.liveavatar.output_bridge import OutputBridge          # .publish(msg)
# verified: liveavatar/__init__.py
from parrot.integrations.liveavatar import LiveAvatarClient, LiveAvatarConfig
# verified: liveavatar/speakable.py (used across FEAT-242/243)
from parrot.integrations.liveavatar.speakable import SpeakableFlattener
# AIMessage / OutputMode (used by ask_stream return + FEAT-243 agent.py)
from parrot.models.responses import AIMessage
```

### Existing Class Signatures
```python
# bots/base.py
class AbstractBot:
    async def ask_stream(self, question: str, session_id: Optional[str]=None,
        user_id: Optional[str]=None, ..., output_mode: OutputMode=OutputMode.DEFAULT,
        ...) -> AsyncIterator[Union[str, AIMessage]]:  # :1456-1475

# livekit_agent/models.py
class StructuredOutputMessage(BaseModel):  # :42
    type: str; session_id: str; payload: Dict[str, Any]; turn_id: Optional[str] = None

# liveavatar/output_bridge.py
class OutputBridge:  # :25
    async def publish(self, msg: StructuredOutputMessage) -> None: ...  # :39

# liveavatar/client.py  (FEAT-242 — to EXTEND)
class LiveAvatarClient:  # :38  "Async HTTP client for the LiveAvatar LITE API."
    async def create_session_token(self, cfg, ...):  # :116  payload hardcodes "mode":"LITE"  # :146

# FEAT-243 bifurcation helpers to REUSE/REFACTOR (livekit_agent/agent.py)
def _is_structured(msg: AIMessage) -> bool          # agent.py:131
def _classify(msg: AIMessage) -> str                # agent.py:144
def _structured_payload(msg: AIMessage) -> Dict     # agent.py:157

# handlers/user.py
async def broadcast_to_channel(self, channel, message, exclude_ws=None)  # :357
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OpenAIChatCompletions` | `bot.ask_stream()` | async iterate | `bots/base.py:1456` |
| bifurcation helper | `OutputBridge.publish()` | structured `AIMessage` | `output_bridge.py:39` |
| `create_full_session` | LiveAvatar REST | `"mode":"FULL"` + custom-LLM cfg | extends `client.py:116,146` |
| FULL routes | `manager.setup` router | `router.add_view(...)` | `manager.py` (avatar/voice routes pattern) |

### Does NOT Exist (Anti-Hallucination)
- ~~Any `/v1/chat/completions` or OpenAI-compatible endpoint~~ — **confirmed absent**
  (grep over `packages/`); this feature creates it.
- ~~`LiveAvatarClient` FULL-mode support~~ — client is LITE-only today
  (`"mode":"LITE"` hardcoded at `client.py:146`); FULL mode is new.
- ~~An OpenAI-compat request/response model in ai-parrot~~ — must be created
  (`ChatCompletionRequest` etc.).
- ~~`ENABLE_LIVEAVATAR_FULL` config key~~ — does not exist; add to `parrot/conf.py`
  (mirror `ENABLE_LIVEAVATAR_VOICE` at conf.py:95).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- aiohttp `web.StreamResponse` for SSE; `Content-Type: text/event-stream`,
  flush per delta (mirror the streaming pattern in `AgentTalk._handle_stream_response`).
- Reuse FEAT-243's structured/speech bifurcation rather than re-deriving it —
  refactor it into a shared helper imported by BOTH the worker (`agent.py`) and
  this endpoint, so the two modes never drift.
- Async-first; `self.logger`; Pydantic for request/response models; graceful
  degradation (bridge errors non-fatal), all per CLAUDE.md.
- Opt-in + tenant gating identical to Phase A/C (`is_avatar_enabled`).

### Known Risks / Gotchas
- **session_id transport** is the crux (see Open Questions): LiveAvatar's Custom
  LLM call must convey which conversation/agent it is, so our endpoint can key
  `ask_stream` + the side channel correctly. If LiveAvatar forwards arbitrary
  headers or an `extra_body`, use that; otherwise encode in `model` (e.g.
  `"<agent>::<session_id>"`) or use a per-session endpoint URL minted at
  `/full/start`.
- **Structured outputs are invisible to voice**: a turn that is *only* a chart
  produces no speech — emit a short spoken filler (reuse FEAT-243
  `DEFAULT_FILLER_TEXT`) so the avatar isn't mute, exactly as Phase C does.
- **Auth**: the endpoint is called server-to-server by LiveAvatar, not the
  browser — needs its own auth (shared secret/API key), distinct from the user
  session cookie.
- **Vendor lock-in / control**: STT/TTS/voices are LiveAvatar's; less tuning than
  Phase C. Accepted tradeoff (brainstorm Option B).
- **Barge-in / turn-taking** is LiveAvatar's responsibility in FULL mode; verify
  their behaviour during long `ask_stream` turns.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | SSE streaming endpoint (project standard) |
| `openai` (dev/test only) | any | Contract-conformance test of our endpoint |
| LiveAvatar FULL Mode / Custom LLM | n/a (their service) | Hosts STT+TTS+video, calls our LLM (`docs/full-mode/custom-llm`) |

---

## 8. Open Questions

- [ ] **How do `session_id` + `agent_name` travel** from LiveAvatar's Custom-LLM
      call into `/v1/chat/completions`? (forwarded header? `extra_body`? encoded
      in `model`? per-session minted URL?) — *Owner: Jesús* — **blocks M1**;
      needs LiveAvatar Custom-LLM API docs.
- [ ] **FULL-mode transport**: does the browser join a LiveAvatar-hosted room, or
      is BYO LiveKit still involved? Determines `/full/start` response shape and
      frontend join code. — *Owner: Jesús*.
- [ ] **Server-to-server auth** scheme LiveAvatar supports for the custom-LLM URL
      (bearer? header secret? IP allowlist?). — *Owner: Jesús*.
- [ ] Q-skills (carried from brainstorm, still open): install LiveAvatar Agent
      Skills (`npx skills add heygen-com/liveavatar-agent-skills`) before
      implementation? — *Owner: Jesús*.
- [x] TTS for the avatar — *Resolved (mode choice)*: in FULL mode the **TTS is
      LiveAvatar's**, by definition (no own TTS, no Supertonic). Our-infra TTS is
      the Option-C concern (FEAT-246), not this spec.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential), but M1 (endpoint) and M2
  (bifurcation refactor) can be developed in parallel if needed; M3 depends on M1.
- **Cross-feature dependencies**: depends on FEAT-243 artifacts already in `dev`
  (OutputBridge, StructuredOutputMessage, SpeakableFlattener, bot resolver). The
  M2 refactor of `agent.py` must keep FEAT-243 worker tests green. Independent of
  FEAT-246 (they target different modes and can land in either order).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-18 | Jesús Lara (w/ Claude) | Initial draft — revisits brainstorm Option B (FULL Mode + Custom LLM) as a parallel avatar mode |
