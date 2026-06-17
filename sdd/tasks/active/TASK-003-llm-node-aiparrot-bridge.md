# TASK-003: `LiveAvatarAgent.llm_node` ai-parrot bridge

**Feature**: FEAT-243 — LiveAvatar Phase C (voice-native hybrid, ai-parrot as the brain)
**Spec**: `sdd/specs/liveavatar-phase-c-voice-native.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001, TASK-002
**Assigned-to**: unassigned

---

## ⛔ BLOCKED ON FEAT-242

This task references the FEAT-242 `SpeakableFlattener` (Phase A). **Do NOT start
until FEAT-242 has merged to `dev`** and
`packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speakable.py`
exists. If `SpeakableFlattener` is absent when you pick this up, STOP and report —
do not stub or reinvent it.

---

## Context

Implements spec §3 **Module 2** (capability `llm-node-aiparrot-bridge`). This is the
heart of Phase C: the LiveKit Agents pipeline keeps STT/VAD/turn-detection/TTS, but the
LLM node is replaced. `LiveAvatarAgent.llm_node()` extracts the last user message from
`chat_ctx`, calls ai-parrot's `ask_stream()`, and bifurcates the response:

- **speakable text** → run through the FEAT-242 `SpeakableFlattener`, then `yield` plain
  `str` so LiveKit's TTS node speaks it through the avatar;
- **structured outputs** (`AIMessage` with `tool_calls` / `data` / `artifact_id` / non-
  default `output_mode`) → routed to the `OutputBridge` (TASK-002) → AgentChat UI.

Long `tool_calls` must not produce dead air → emit a filler / "thinking" utterance
(Q-filler).

---

## Scope

- Create `agent.py` under `liveavatar/livekit_agent/` with:
  - `LiveAvatarAgent(Agent)` (LiveKit Agents `Agent`) constructed with `agent_name`,
    `session_id`, `tenant_id`, and an injected `OutputBridge`.
  - `async def llm_node(self, chat_ctx, tools, model_settings)` override that streams
    from ai-parrot and `yield`s speakable `str` chunks.
  - `_last_user_text(chat_ctx)` helper → the last `role="user"` message text.
  - Bot resolution: obtain the ai-parrot bot for `agent_name` and call `ask_stream(...)`.
  - Speakable filtering via the FEAT-242 `SpeakableFlattener` (`feed()` / `flush()`).
  - Structured-output routing to `OutputBridge.publish(StructuredOutputMessage(...))`.
  - Filler/"thinking" emission while a long `tool_calls` turn is in flight (Q-filler).
- Write unit tests: `test_llm_node_yields_speakable_str`, `test_llm_node_last_user_text`,
  `test_llm_node_filler_on_tool_calls`, `test_speakable_flatten_reused`.

**NOT in scope**:
- `worker.py` / `pipeline.py` / `build_session` (TASK-004).
- The `OutputBridge` body (TASK-002 — import & call it).
- Defining models (TASK-001 — import them).
- Modifying FEAT-242 `SpeakableFlattener` (reuse only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/agent.py` | CREATE | `LiveAvatarAgent` + `llm_node` override + `_last_user_text` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent.py` | CREATE | `llm_node` / speakable / filler unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage  # TASK-001
from parrot.integrations.liveavatar.output_bridge import OutputBridge                     # TASK-002
# LiveKit Agents base (from the liveavatar-voice extra — pinned in TASK-001):
from livekit.agents import Agent          # VALIDATE exact import + llm_node signature vs the pinned version (P5)
# ai-parrot streaming + final sentinel:
from parrot.models.responses import AIMessage           # verified: responses.py:72
```

### Existing Signatures to Use (VERIFIED this session)
```python
# packages/ai-parrot/src/parrot/bots/base.py:1456  (abstract decl: abstract.py:3740)
async def ask_stream(
    self,
    question: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    search_type: str = "similarity",
    ...
    output_mode: OutputMode = OutputMode.DEFAULT,
    **kwargs,
) -> AsyncIterator[Union[str, AIMessage]]: ...
# NOTE: ask_stream has NO `agent_name` and NO `tenant_id` parameters. The agent is
# selected by WHICH bot instance you call; pass session_id (and user_id if available).
# tenant_id is NOT a direct ask_stream arg — thread it via the resolved bot / kwargs.

# Bot resolution (server package):
# packages/ai-parrot-server/src/parrot/manager/manager.py:658
async def get_bot(self, name: str, new: bool = False, session_id: str = "",
                  request: Optional[web.Request] = None, **kwargs) -> AbstractBot: ...
# Inject the bot (or a get_bot callable) into LiveAvatarAgent rather than importing a
# global BotManager — keep ai-parrot-integrations decoupled from the server singleton.

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):                      # line 72
    response: Optional[str]
    output: Any
    data: Optional[Any]
    code: Optional[str]
    tool_calls: List[ToolCall]                   # line 129
    output_mode: OutputMode                      # line 210
    artifact_id: Optional[str]                   # line 214
    @property
    def to_text(self) -> str: ...                # line 249
```

### Provided by FEAT-242 (MUST verify exists before use — created by Phase A)
```python
# .../liveavatar/speakable.py
class SpeakableFlattener:
    def feed(self, chunk: str) -> list[str]: ...   # incremental → complete sentences
    def flush(self) -> list[str]: ...
```

### Does NOT Exist
- ~~`ask_stream(agent_name=..., tenant_id=...)`~~ — those are NOT params of `ask_stream`
  (see note above). The spec's `ai_parrot_ask_stream(agent_name=...)` is an
  illustrative wrapper; implement it by resolving the bot then calling `ask_stream`.
- ~~`before_llm_cb`~~ — superseded by the 1.x `llm_node` override (spec §2 integration table).
- ~~a current `livekit.agents` install~~ — comes from the `liveavatar-voice` extra (TASK-001);
  validate the `llm_node(chat_ctx, tools, model_settings)` signature against the pinned
  version (P5) before finalising.
- ~~`SpeakableFlattener` in the current tree~~ — created by FEAT-242; STOP if absent.

---

## Implementation Notes

### Pattern to Follow
```python
async def llm_node(self, chat_ctx, tools, model_settings):
    user_text = self._last_user_text(chat_ctx)
    bot = await self._resolve_bot(self._agent_name)          # injected resolver
    async for chunk in bot.ask_stream(question=user_text, session_id=self._session_id):
        if isinstance(chunk, str):
            for sentence in self._flattener.feed(chunk):     # FEAT-242 SpeakableFlattener
                yield sentence                                # → LiveKit TTS → avatar
        else:  # AIMessage sentinel — bifurcate
            if chunk.tool_calls or chunk.data or chunk.artifact_id:
                await self._bridge.publish(StructuredOutputMessage(
                    type=..., session_id=self._session_id, payload=...))
            for sentence in self._flattener.flush():
                yield sentence
```

### Key Constraints
- Async throughout; `llm_node` is an async generator that may `yield` plain `str`.
- Speakable text MUST pass through `SpeakableFlattener` before `yield` (acceptance).
- During a long `tool_calls` turn, emit a filler utterance so the avatar isn't silent
  (Q-filler — a short configurable phrase or a "thinking" marker; document the choice).
- Keep the module importable without a live LiveKit room (tests use fakes/mocks for
  `chat_ctx`, the bot, the flattener, and the bridge).
- `self.logger`; no `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py:1456` — `ask_stream`.
- `packages/ai-parrot/src/parrot/models/responses.py:72` — `AIMessage`.
- FEAT-242 `.../liveavatar/speakable.py` — `SpeakableFlattener`.

---

## Acceptance Criteria

- [ ] `LiveAvatarAgent.llm_node` calls `ask_stream` and `yield`s speakable `str`
- [ ] Speakable text is filtered through FEAT-242 `SpeakableFlattener` before `yield`
- [ ] `_last_user_text` returns the last `role="user"` message from `chat_ctx`
- [ ] Structured outputs (`tool_calls`/`data`/`artifact_id`) routed to `OutputBridge.publish`
- [ ] Long `tool_calls` emit a filler/"thinking" utterance (no dead air)
- [ ] `llm_node` signature validated against the pinned `livekit-agents` (P5)
- [ ] No linting errors: `ruff check .../liveavatar/livekit_agent/agent.py`
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent.py
import pytest

# Use lightweight fakes for chat_ctx (messages with .role/.content), the bot
# (async ask_stream generator), SpeakableFlattener, and OutputBridge.

@pytest.mark.asyncio
async def test_llm_node_last_user_text():
    """_last_user_text extracts the last role='user' message."""
    ...

@pytest.mark.asyncio
async def test_llm_node_yields_speakable_str():
    """Plain str chunks from ask_stream are yielded as speakable strings."""
    ...

@pytest.mark.asyncio
async def test_speakable_flatten_reused():
    """Markdown is stripped via SpeakableFlattener before TTS yield."""
    ...

@pytest.mark.asyncio
async def test_llm_node_filler_on_tool_calls():
    """A long tool_calls turn emits a filler/'thinking' utterance (no dead air)."""
    ...
```

---

## Agent Instructions

1. **Read the spec** for full context.
2. **VERIFY FEAT-242 IS MERGED** — `speakable.py` / `SpeakableFlattener` must exist. STOP if not.
3. **Check dependencies** — TASK-001 and TASK-002 in `sdd/tasks/completed/`.
4. **Verify the Codebase Contract** — re-grep `ask_stream`, `AIMessage`, `SpeakableFlattener`;
   validate the `llm_node` signature against the pinned `livekit-agents` (P5).
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** per scope.
7. **Verify** acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
