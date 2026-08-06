# TASK-2147: Inference Parameter Threading

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2146
**Assigned-to**: unassigned

---

## Context

`NovaAudio.stream_voice()` hardcodes `maxTokens: 1024, topP: 0.9,
temperature: 0.7` in the `sessionStart` event (line 681). The `VoiceConfig`
has `max_tokens=4096`, `temperature=0.7`, and a new `top_p=0.9` field
(from TASK-2146), but none of these values reach the Nova Sonic session.

This task threads VoiceConfig inference parameters through
`stream_voice()` to the provider's session-start event.

Implements spec §3 Module 3.

---

## Scope

- Modify `NovaAudio.stream_voice()` to accept `temperature`, `max_tokens`,
  and `top_p` via `**kwargs` and use them in the `sessionStart` event
  instead of the hardcoded values.
- Provide sensible defaults matching current behavior when kwargs are absent
  (backward compatible).
- Write a unit test verifying the `sessionStart` event uses the
  VoiceConfig values.

**NOT in scope**: modifying GeminiLiveClient's inference config (Gemini
handles this via its own `GenerationConfig`), modifying VoiceBot (that's
TASK-2151).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/nova/audio.py` | MODIFY | Thread kwargs to sessionStart at line 681 |
| `tests/clients/nova/test_nova_inference_params.py` | CREATE | Verify sessionStart uses config values |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.nova.audio import NovaAudio   # verified: nova/audio.py:245
```

### Existing Signatures to Use

```python
# parrot/clients/nova/audio.py:613
async def stream_voice(
    self,
    audio_iterator: AsyncIterator[bytes],
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs,                                      # temperature, max_tokens, top_p arrive here
) -> AsyncIterator[LiveVoiceResponse]: ...

# parrot/clients/nova/audio.py:681 — CURRENT hardcoded values
await self._send_event(stream, {"event": {"sessionStart": {
    "inferenceConfiguration": {"maxTokens": 1024, "topP": 0.9, "temperature": 0.7}
}}})
```

### Does NOT Exist

- ~~`NovaAudio.inference_config`~~ — no attribute; values are inline at line 681
- ~~`NovaAudio._build_session_start()`~~ — no such method; the dict is built inline

---

## Implementation Notes

### Pattern to Follow

Replace the hardcoded dict with kwargs extraction:

```python
# In stream_voice(), around line 681:
temperature = kwargs.get("temperature", 0.7)
max_tokens = kwargs.get("max_tokens", 1024)
top_p = kwargs.get("top_p", 0.9)

await self._send_event(stream, {"event": {"sessionStart": {
    "inferenceConfiguration": {
        "maxTokens": max_tokens,
        "topP": top_p,
        "temperature": temperature,
    }
}}})
```

### Key Constraints

- Defaults MUST match current hardcoded values (`1024`, `0.9`, `0.7`) so
  existing callers without kwargs see no behavior change.
- VoiceBot will pass these from VoiceConfig in TASK-2151; this task just
  opens the door.

---

## Acceptance Criteria

- [ ] `sessionStart` event uses kwargs values when provided
- [ ] Default behavior unchanged when no kwargs passed
- [ ] Test verifies custom values appear in sessionStart
- [ ] All tests pass: `pytest tests/clients/nova/test_nova_inference_params.py -v`

---

## Test Specification

```python
# tests/clients/nova/test_nova_inference_params.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestNovaInferenceParams:
    @pytest.mark.asyncio
    async def test_custom_inference_params_in_session_start(self):
        """stream_voice() sends custom maxTokens/topP/temperature."""
        # Mock _send_event to capture the sessionStart payload
        # Call stream_voice with temperature=0.5, max_tokens=2048, top_p=0.95
        # Assert the sessionStart event contains those values

    @pytest.mark.asyncio
    async def test_default_inference_params(self):
        """stream_voice() uses 1024/0.9/0.7 when no kwargs given."""
        # Call stream_voice with no inference kwargs
        # Assert sessionStart contains maxTokens=1024, topP=0.9, temperature=0.7
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 3
2. **Check dependencies** — TASK-2146 must be done (VoiceConfig has top_p)
3. **Verify** line 681 of `nova/audio.py` still has the hardcoded values
4. **Modify** the `stream_voice()` method to extract kwargs
5. **Write tests** and verify

---

## Completion Note

*(Agent fills this in when done)*
