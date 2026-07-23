# TASK-1874: OpenAI-compatible streaming chat-completions endpoint

**Feature**: FEAT-247 — LiveAvatar FULL Mode Custom LLM
**Spec**: `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. LiveAvatar FULL Mode with Custom LLM integration needs an
OpenAI-compatible endpoint that LiveAvatar's infra can call server-to-server.
FEAT-248 already built the full-mode session lifecycle, bifurcation, and
`speak_text` flow. This task adds the missing OpenAI-compat surface so
LiveAvatar can call ai-parrot directly (removing the frontend from the LLM
relay loop).

The endpoint uses a **per-session minted URL** pattern:
`POST /v1/chat/completions/{session_id}?agent={agent_name}` — the `session_id`
is baked into the URL path (minted by `/full/start` in TASK-1875), and the
agent is a query parameter. Bearer token auth for server-to-server calls.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/openai_compat.py` with:
  - `OpenAIChatCompletions(BaseView)`: `POST /v1/chat/completions/{session_id}`
    - Validate bearer token from `Authorization` header
    - Look up `session_id` in `app[FULLMODE_SESSIONS_KEY]` — 404 if missing
    - Resolve agent from `?agent=` query param via `BotManager.get_bot()`
    - Parse `ChatCompletionRequest` body (Pydantic model)
    - Extract last user message from `messages[]`
    - Call `bot.ask_stream(question, session_id=session_id)`
    - Run text chunks through `SpeakableFlattener`
    - Emit `chat.completion.chunk` SSE deltas for speakable text
    - For final `AIMessage` with structured output, publish via the existing
      bifurcation pattern (reuse `_maybe_publish_bifurcated_output` logic)
    - Terminate with `finish_reason:"stop"` + `data: [DONE]`
    - Non-stream fallback: return single JSON completion
  - `OpenAIModels(BaseView)`: `GET /v1/models`
    - Return available agent names as model IDs
- Create Pydantic models: `ChatMessage`, `ChatCompletionRequest`
- Create `register_openai_compat_routes(router)` function
- Write unit tests

**NOT in scope**: modifying `/full/start` response (TASK-1875), route
registration in manager.py (TASK-1876), session lifecycle (FEAT-248).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/openai_compat.py` | CREATE | OpenAI-compat endpoint + models |
| `packages/ai-parrot-server/tests/handlers/test_openai_compat.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handlers/agent.py:102 — BaseView for aiohttp handlers
from parrot.handlers.base import BaseView  # verified pattern from avatar_fullmode.py

# handlers/avatar_fullmode.py:52 — session store key
from parrot.handlers.avatar_fullmode import FULLMODE_SESSIONS_KEY

# bots/base.py — ask_stream interface
# AbstractBot.ask_stream() -> AsyncIterator[Union[str, AIMessage]]

# liveavatar/speakable.py:87
from parrot.integrations.liveavatar.speakable import SpeakableFlattener

# models/responses.py
from parrot.models.responses import AIMessage

# manager resolution
# BotManager.get_bot(agent_name) — async, returns AbstractBot instance
```

### Existing Signatures to Use
```python
# handlers/avatar_fullmode.py:52
FULLMODE_SESSIONS_KEY = "avatar_fullmode_sessions"
# app[FULLMODE_SESSIONS_KEY] is a dict: {session_id: FullModeSessionHandle}

# handlers/agent.py:2674-2692
# AgentTalk._handle_stream_response(...) — reference for streaming pattern
# Uses web.StreamResponse with Content-Type: text/plain; charset=utf-8

# handlers/agent.py:2577
# AgentTalk._maybe_publish_bifurcated_output(session_id, ai_message, ...)
# Publishes structured output via Redis transport (FEAT-249 Mode B)

# liveavatar/speakable.py:87
class SpeakableFlattener:
    # Converts markdown to speakable plain text

# handlers/avatar_fullmode.py:181-185
# _start_fullmode_session returns: {session_id, livekit_url, livekit_client_token}
```

### Does NOT Exist
- ~~`/v1/chat/completions` endpoint~~ — this task creates it
- ~~`ChatCompletionRequest` model~~ — this task creates it
- ~~`openai_compat.py`~~ — this task creates it
- ~~`parrot.handlers.openai_compat`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# SSE streaming — OpenAI chat.completion.chunk format:
# data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234,
#        "model":"agent_name","choices":[{"index":0,"delta":{"content":"text"},
#        "finish_reason":null}]}
# ...
# data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234,
#        "model":"agent_name","choices":[{"index":0,"delta":{},
#        "finish_reason":"stop"}]}
# data: [DONE]

# Use web.StreamResponse with Content-Type: text/event-stream
resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                    "Cache-Control": "no-cache"})
await resp.prepare(request)
await resp.write(f"data: {json.dumps(chunk)}\n\n".encode())
```

### Key Constraints
- Bearer token stored in env var (e.g. `OPENAI_COMPAT_BEARER_TOKEN`)
- `session_id` from URL path, not from request body
- Structured-output-only turns should emit a short filler text so avatar speaks
- Bridge failures must be non-fatal to the spoken stream
- Async-first, `logging.getLogger(__name__)`, Pydantic models

---

## Acceptance Criteria

- [ ] `POST /v1/chat/completions/{session_id}?agent=xxx` with `stream=true` returns valid OpenAI SSE chunks ending with `data: [DONE]`
- [ ] Missing/invalid bearer token → 401
- [ ] Unknown `session_id` (not in `FULLMODE_SESSIONS_KEY`) → 404
- [ ] `stream=false` returns a single JSON completion
- [ ] `GET /v1/models` returns available agent names
- [ ] Structured outputs published via bifurcation, never crash the stream
- [ ] `ruff check` clean on new files
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_openai_compat.py -v`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_openai_compat.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.handlers.openai_compat import OpenAIChatCompletions, OpenAIModels


@pytest.fixture
def fake_bot():
    bot = AsyncMock()
    async def _stream(question, session_id=None, **kw):
        yield "Hello "
        yield "world."
    bot.ask_stream = _stream
    bot.name = "test_agent"
    return bot


class TestOpenAIChatCompletions:
    async def test_streams_deltas(self, fake_bot):
        """stream=true → SSE chat.completion.chunk deltas ending [DONE]."""

    async def test_non_stream_json(self, fake_bot):
        """stream=false → single JSON completion response."""

    async def test_auth_required(self):
        """Missing bearer token → 401."""

    async def test_unknown_session_404(self):
        """session_id not in FULLMODE_SESSIONS_KEY → 404."""

    async def test_resolves_agent_and_session(self, fake_bot):
        """agent from query param + session_id from URL passed to ask_stream."""


class TestOpenAIModels:
    async def test_models_endpoint(self):
        """GET /v1/models returns available agents."""
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
2. **Check dependencies** — none (this is the foundation task)
3. **Verify the Codebase Contract** — confirm FULLMODE_SESSIONS_KEY, BaseView, SpeakableFlattener exist
4. **Update status** in `sdd/tasks/index/liveavatar-full-mode-custom-llm.json` → `"in-progress"`
5. **Implement** the handler and tests
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
