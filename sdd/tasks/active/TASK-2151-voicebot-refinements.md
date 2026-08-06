# TASK-2151: VoiceBot Refinements

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2145, TASK-2146
**Assigned-to**: unassigned

---

## Context

`VoiceBot` (line 80, `parrot/bots/voice.py`) is a working voice bot but
has three gaps:
1. Not exported from `parrot.bots` — users must know the private module path.
2. No `stt_only` parameter on `ask_stream()` — GeminiLiveClient supports
   it but VoiceBot doesn't wire it through.
3. Uses the old core `VoiceConfig` (plain `provider` string) instead of the
   unified version with `VoiceProvider` enum.
4. `_create_llm_client()` returns `AbstractClient` without type-checking
   for voice capability.

Implements spec §3 Module 7.

---

## Scope

- Add `VoiceBot` to `parrot.bots.__init__.__all__` and import it.
- Add `stt_only: bool = False` parameter to `VoiceBot.ask_stream()` and
  pass it through to `client.stream_voice(**kwargs)`.
- Update `VoiceBot.__init__()` and `_resolve_llm_config()` to use the
  unified `VoiceConfig` with `VoiceProvider` enum.
- Type-annotate the client in `_create_llm_client()` return as
  `VoiceCapable` (runtime check with `isinstance`).
- Thread `VoiceConfig` inference parameters (`temperature`, `max_tokens`,
  `top_p`, `parallel_tool_execution`) through `ask_stream()` kwargs to the
  client's `stream_voice()`.
- Write unit tests.

**NOT in scope**: modifying VoiceSession (TASK-2149), modifying clients,
or modifying VoiceChatHandler (TASK-2152).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/voice.py` | MODIFY | stt_only, unified VoiceConfig, VoiceCapable check |
| `parrot/bots/__init__.py` | MODIFY | Export VoiceBot |
| `tests/bots/test_voicebot_refinements.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.voice import VoiceBot                 # verified: voice.py:80
from parrot.clients.protocols import VoiceCapable      # TASK-2145 creates this
from parrot.models.voice import VoiceConfig, VoiceProvider  # TASK-2146 unifies
from parrot.clients.base import AbstractClient         # verified: base.py:253
from parrot.clients.live import GeminiLiveClient       # verified: live.py:488
from parrot.clients.nova import NovaClient             # verified: nova/client.py:30
```

### Existing Signatures to Use

```python
# parrot/bots/voice.py:80
class VoiceBot(A2AEnabledMixin, BaseBot):
    def __init__(self, name="Voice Assistant", system_prompt=None,
        llm=None, tools=None, voice_config=None, **kwargs):     # line 106

    def _resolve_llm_config(self, llm=None, model=None,
        preset=None, model_config=None, **kwargs):              # line 151

    def _create_llm_client(self, config,
        conversation_memory=None) -> AbstractClient:            # line 214

    async def ask_stream(self,
        audio_input: Union[bytes, AsyncIterator[bytes]],
        session_id=None, user_id=None,
        **kwargs) -> AsyncIterator[LiveVoiceResponse]:          # line 400

# parrot/bots/__init__.py:11 — current __all__
__all__ = (
    "AbstractBot", "Agent", "BaseBot", "BasicAgent",
    "BasicBot", "Chatbot", "WebAgent", "WebSearchAgent",
)
```

### Does NOT Exist

- ~~`VoiceBot` in `parrot.bots.__all__`~~ — NOT exported
- ~~`VoiceBot.ask_stream(stt_only=...)`~~ — no stt_only param

---

## Implementation Notes

### Export Pattern

```python
# parrot/bots/__init__.py — add import and __all__ entry
from parrot.bots.voice import VoiceBot

__all__ = (
    "AbstractBot", "Agent", "BaseBot", "BasicAgent",
    "BasicBot", "Chatbot", "VoiceBot", "WebAgent", "WebSearchAgent",
)
```

### stt_only Passthrough

```python
# In VoiceBot.ask_stream():
async def ask_stream(
    self,
    audio_input: Union[bytes, AsyncIterator[bytes]],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    stt_only: bool = False,
    **kwargs,
) -> AsyncIterator[LiveVoiceResponse]:
    # ... existing setup ...
    async for response in client.stream_voice(
        audio_iterator,
        system_prompt=self.system_prompt,
        session_id=session_id,
        user_id=user_id,
        stt_only=stt_only,
        temperature=self.voice_config.temperature,
        max_tokens=self.voice_config.max_tokens,
        top_p=self.voice_config.top_p,
        parallel_tool_execution=self.voice_config.parallel_tool_execution,
        **kwargs,
    ):
        yield response
```

### VoiceCapable Check

```python
# In _create_llm_client():
client = ...  # existing creation logic
if not isinstance(client, VoiceCapable):
    raise TypeError(
        f"Provider '{self.voice_config.provider}' created a client "
        f"({type(client).__name__}) that does not implement VoiceCapable. "
        f"Voice streaming is not supported."
    )
return client
```

### Key Constraints

- The `VoiceBot` import in `__init__.py` should be conditional or lazy to
  avoid import errors when voice dependencies are not installed (check if
  the existing pattern in `__init__.py` uses lazy imports).
- `stt_only` for Nova should raise `NotImplementedError` — but that's the
  client's responsibility, not VoiceBot's.

---

## Acceptance Criteria

- [ ] `from parrot.bots import VoiceBot` works
- [ ] `VoiceBot.ask_stream(stt_only=True)` passes `stt_only=True` to client
- [ ] `_create_llm_client()` raises `TypeError` for non-VoiceCapable clients
- [ ] VoiceConfig inference params threaded through to `stream_voice()`
- [ ] All tests pass: `pytest tests/bots/test_voicebot_refinements.py -v`

---

## Test Specification

```python
# tests/bots/test_voicebot_refinements.py
import pytest


class TestVoiceBotExport:
    def test_import_from_bots(self):
        from parrot.bots import VoiceBot
        assert VoiceBot is not None

    def test_voicebot_in_all(self):
        import parrot.bots
        assert "VoiceBot" in parrot.bots.__all__


class TestVoiceBotSttOnly:
    @pytest.mark.asyncio
    async def test_stt_only_passed_to_client(self):
        """ask_stream(stt_only=True) passes through to stream_voice."""
        # Mock VoiceCapable client, capture kwargs in stream_voice
        # Assert stt_only=True arrives


class TestVoiceBotVoiceCapableCheck:
    def test_non_voice_client_raises(self):
        """_create_llm_client raises TypeError for non-VoiceCapable."""
        # Create VoiceBot with a provider that yields AbstractClient
        # without stream_voice
        # Assert TypeError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 7
2. **Check dependencies** — TASK-2145 and TASK-2146 must be done
3. **Read** `parrot/bots/voice.py` and `parrot/bots/__init__.py`
4. **Modify** both files per the scope
5. **Write tests** and verify

---

## Completion Note

*(Agent fills this in when done)*
