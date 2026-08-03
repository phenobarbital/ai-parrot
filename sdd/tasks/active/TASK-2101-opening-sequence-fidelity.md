# TASK-2101: Complete the Nova Sonic opening event sequence

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2 (spec gap 10, plus the `toolUseOutputConfiguration`
half of gap 1). `stream_voice()`'s opening frames omit several fields AWS's
official samples always send: `audioType`, the `interactive` flags, and
`textInputConfiguration` on the SYSTEM text `contentStart`.

Reference: `aws-samples/amazon-nova-samples`,
`speech-to-speech/amazon-nova-2-sonic/sample-codes/console-python/nova_sonic_simple.py`
lines 78–175.

Also extracts `_build_prompt_start()` so TASK-2104 has a seam to add
`toolConfiguration` into without re-touching `stream_voice()`.

---

## Scope

- Add `"audioType": "SPEECH"` to `audioOutputConfiguration` and
  `audioInputConfiguration`.
- Add `"interactive": True` to the AUDIO `contentStart`.
- Add `"interactive": False` and
  `"textInputConfiguration": {"mediaType": "text/plain"}` to the SYSTEM text
  `contentStart`.
- Add `"toolUseOutputConfiguration": {"mediaType": "application/json"}` to
  `promptStart`.
- Extract the `promptStart` frame construction into
  `_build_prompt_start(prompt_name, voice_id) -> Dict[str, Any]`.
- Test the captured frames.

**NOT in scope**: `toolConfiguration.tools[]` (TASK-2104); any receive-side
change; `promptEnd`/`sessionEnd` (TASK-2107).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | Opening frames + `_build_prompt_start()` |
| `packages/ai-parrot/tests/clients/test_nova_protocol_frames.py` | CREATE | Frame-shape assertions |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.
> **Verify before editing** — this checkout is shared and HEAD has moved mid-session before.

### Verified Imports

```python
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py:10
from parrot.clients.nova import audio as audio_mod  # verified: module exists
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
class NovaAudio:                                      # line 125
    INPUT_SAMPLE_RATE_HZ: int = 16000                 # line 154
    OUTPUT_SAMPLE_RATE_HZ: int = 24000                # line 155
    async def _send_event(self, stream, event: Dict[str, Any]) -> None: ...  # line 234
    async def stream_voice(self, audio_iterator, system_prompt=None,
                           session_id=None, user_id=None, **kwargs
                           ) -> AsyncIterator[LiveVoiceResponse]: ...        # line 343
```

Frames to modify, as they exist today:

```python
# nova/audio.py:412 — promptStart
{"event": {"promptStart": {
    "promptName": prompt_name,
    "textOutputConfiguration": {"mediaType": "text/plain"},
    "audioOutputConfiguration": {            # line 415 — needs audioType
        "mediaType": "audio/lpcm", "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
        "sampleSizeBits": 16, "channelCount": 1,
        "voiceId": resolved_voice_id, "encoding": "base64",
    },
}}}
# nova/audio.py:425 — SYSTEM text contentStart (needs interactive + textInputConfiguration)
{"event": {"contentStart": {
    "promptName": prompt_name, "contentName": f"{content_name}-sys",
    "type": "TEXT", "role": "SYSTEM",
}}}
# nova/audio.py:437 — AUDIO contentStart (needs interactive)
{"event": {"contentStart": {
    "promptName": prompt_name, "contentName": content_name,
    "type": "AUDIO", "role": "USER",
    "audioInputConfiguration": {             # line 440 — needs audioType
        "mediaType": "audio/lpcm", "sampleRateHertz": self.INPUT_SAMPLE_RATE_HZ,
        "sampleSizeBits": 16, "channelCount": 1, "encoding": "base64",
    },
}}}
```

### Does NOT Exist

- ~~`NovaAudio._build_prompt_start()`~~ — **this task creates it**.
- ~~`NovaAudio.__init__`~~ — `NovaAudio` is a plain mixin and defines **no**
  `__init__` (MRO constraint, `novaclient-amazon-aws.spec.md` §7). Do not add
  one; keep per-turn state in locals.
- ~~`self.audio_type` / `self.interactive`~~ — not configurable attributes; these
  are literal frame fields.
- ~~`"audioType": "speech"`~~ (lowercase) — the samples use uppercase `"SPEECH"`.

---

## Implementation Notes

### Pattern to Follow

Extract, don't restructure. `_build_prompt_start()` returns the full frame dict
so `stream_voice()` keeps a single `await self._send_event(...)` call:

```python
    def _build_prompt_start(self, prompt_name: str, voice_id: str) -> Dict[str, Any]:
        """Build the promptStart event frame for a voice turn.

        Args:
            prompt_name: Per-turn prompt identifier.
            voice_id: Resolved Nova Sonic synthesis voice.

        Returns:
            The complete ``promptStart`` event frame.
        """
        return {"event": {"promptStart": {
            "promptName": prompt_name,
            "textOutputConfiguration": {"mediaType": "text/plain"},
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": self.OUTPUT_SAMPLE_RATE_HZ,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": voice_id,
                "encoding": "base64",
                "audioType": "SPEECH",
            },
            "toolUseOutputConfiguration": {"mediaType": "application/json"},
        }}}
```

### Key Constraints

- Frames are plain dicts above the SDK seam — `_send_event()` serializes them.
  Do not pre-serialize to JSON here.
- Keep field ordering close to the sample's for reviewability, but nothing
  depends on dict order.
- Do not change `sampleRateHertz` sources — they must stay
  `self.INPUT_SAMPLE_RATE_HZ` / `self.OUTPUT_SAMPLE_RATE_HZ`.

### References in Codebase

- `packages/ai-parrot/tests/clients/test_nova_audio_sdk.py` — established
  pattern for capturing sent frames by patching `_send_event`; reuse it.
- `nova_sonic_simple.py:78-175` (AWS sample) — the authoritative frame shapes.

---

## Acceptance Criteria

- [ ] `audioOutputConfiguration` and `audioInputConfiguration` both carry
      `"audioType": "SPEECH"`.
- [ ] AUDIO `contentStart` carries `"interactive": True`.
- [ ] SYSTEM text `contentStart` carries `"interactive": False` and
      `"textInputConfiguration": {"mediaType": "text/plain"}`.
- [ ] `promptStart` carries `"toolUseOutputConfiguration"`.
- [ ] `_build_prompt_start()` exists and `stream_voice()` uses it.
- [ ] Tests assert against captured frames — no AWS access required.
- [ ] All existing tests still pass:
      `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
- [ ] Passes on Python 3.11 (SDK absent, skips cleanly) and 3.13 (SDK present).

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_protocol_frames.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient


def _client():
    return NovaClient(model="nova-2-sonic", region="us-east-1", voice_id="matthew")


async def _capture_opening_frames(client, system_prompt="be brief"):
    """Drive stream_voice() far enough to capture the opening sequence."""
    sent = []

    async def capture(_stream, event):
        sent.append(event)

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    async def no_events(_stream):
        return
        yield  # pragma: no cover — makes this an async generator

    with patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=capture), \
         patch.object(client, "_iter_events", new=no_events), \
         patch.object(client, "_close_stream", new=AsyncMock()):
        async for _ in client.stream_voice(audio(), system_prompt=system_prompt):
            pass
    return sent


def _frame(sent, name):
    return next(e["event"][name] for e in sent if name in e.get("event", {}))


class TestOpeningSequence:
    @pytest.mark.asyncio
    async def test_audio_output_declares_audio_type_speech(self):
        sent = await _capture_opening_frames(_client())
        assert _frame(sent, "promptStart")["audioOutputConfiguration"]["audioType"] == "SPEECH"

    @pytest.mark.asyncio
    async def test_prompt_start_declares_tool_use_output_configuration(self):
        sent = await _capture_opening_frames(_client())
        assert "toolUseOutputConfiguration" in _frame(sent, "promptStart")

    @pytest.mark.asyncio
    async def test_audio_content_start_is_interactive(self):
        sent = await _capture_opening_frames(_client())
        audio_starts = [
            e["event"]["contentStart"] for e in sent
            if "contentStart" in e.get("event", {})
            and e["event"]["contentStart"].get("type") == "AUDIO"
        ]
        assert audio_starts[0]["interactive"] is True
        assert audio_starts[0]["audioInputConfiguration"]["audioType"] == "SPEECH"

    @pytest.mark.asyncio
    async def test_system_content_start_shape(self):
        sent = await _capture_opening_frames(_client())
        sys_starts = [
            e["event"]["contentStart"] for e in sent
            if "contentStart" in e.get("event", {})
            and e["event"]["contentStart"].get("role") == "SYSTEM"
        ]
        assert sys_starts[0]["interactive"] is False
        assert sys_starts[0]["textInputConfiguration"] == {"mediaType": "text/plain"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm the line numbers above still point at the frames described
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2101-opening-sequence-fidelity.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
