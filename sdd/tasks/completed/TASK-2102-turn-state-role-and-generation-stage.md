# TASK-2102: Track contentStart role + generationStage; attribute textOutput

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2100
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3 (gaps 5 and 6) — the single highest-value task in this
feature. Nova Sonic reports the speaker and the generation stage on
`contentStart`, and those govern the `textOutput` frames that follow.
`stream_voice()` currently ignores `contentStart` entirely, with two
consequences:

- The user's transcription and the assistant's reply arrive on the same
  `LiveVoiceResponse.text` channel, indistinguishable.
- Without filtering on `generationStage`, assistant text is likely **duplicated**
  (Nova emits both speculative and final stages).

Reference: `nova_sonic_simple.py:250-269` — the sample sets `self.role` from
`contentStart['role']`, parses `additionalModelFields` for
`generationStage`, and prints assistant text only when it is `SPECULATIVE`.

---

## Scope

- Add a module-private `_TurnState` dataclass holding `role` and
  `generation_stage` (plus the two pending-tool slots TASK-2105 will use — declare
  them now so that task doesn't have to reshape the dataclass).
- Handle the `contentStart` frame: record `role`; parse
  `additionalModelFields` (a **JSON string**) and record `generationStage`.
- Set `LiveVoiceResponse.role` on every `textOutput`-derived response.
- Suppress assistant `textOutput` when `generation_stage` is present **and not**
  `"SPECULATIVE"`. A *missing* stage must emit (see Key Constraints).
- Accumulate only assistant text into `accumulated_text`, so the terminal frame's
  `text` is not polluted with the user's transcription.
- Tests for role attribution, stage filtering, and accumulation.

**NOT in scope**: barge-in detection (TASK-2103 — it also observes `textOutput`,
so coordinate but do not implement); tool frames (TASK-2105); `usageEvent`
(TASK-2106).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | `_TurnState` + `contentStart`/`textOutput` handling |
| `packages/ai-parrot/tests/clients/test_nova_turn_state.py` | CREATE | Role, stage, accumulation tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py:10
from parrot.clients.live import LiveVoiceResponse   # verified: clients/live.py:156
# already imported at the top of nova/audio.py — do not re-add:
#   from ..live import LiveCompletionUsage, LiveToolCall, LiveVoiceResponse, VoiceTurnMetadata
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
class NovaAudio:                                                             # line 125
    async def _iter_events(self, stream) -> AsyncIterator[Dict[str, Any]]: ...  # line 259
    async def stream_voice(self, ...) -> AsyncIterator[LiveVoiceResponse]: ...  # line 343

# Current per-turn locals inside stream_voice() that this task changes:
usage = LiveCompletionUsage()      # line 397
accumulated_text = ""              # line 398 — must become assistant-only
# receive loop:
async for event in self._iter_events(stream):        # line 453
    ...
    text_output = event.get("textOutput")            # line 488
    if text_output:
        chunk_text = text_output.get("content", "")
        accumulated_text += chunk_text               # line 491

# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                              # line 156
    text: str = ""                                    # line 164
    role: Optional[str] = None                        # ADDED BY TASK-2100
    is_complete: bool = False                         # line 169
```

### Frame shapes `_iter_events()` yields (already envelope-unwrapped)

```python
{"contentStart": {"role": "USER", "type": "TEXT"}}
{"contentStart": {"role": "ASSISTANT", "type": "TEXT",
                  "additionalModelFields": '{"generationStage": "SPECULATIVE"}'}}
{"textOutput": {"content": "hello"}}
```

### Does NOT Exist

- ~~`event["event"]["contentStart"]`~~ — `_iter_events()` **already unwraps** the
  `{"event": …}` envelope (see its docstring at line 259). Do not re-unwrap.
- ~~`contentStart["generationStage"]`~~ — the stage is nested inside
  `additionalModelFields`, which is a **JSON string**, not a dict.
- ~~`LiveVoiceResponse.generation_stage`~~ — not a field; stage is internal
  filtering state only, not part of the public response.
- ~~`self._turn_state`~~ — do **not** store turn state on `self`. `NovaAudio` is a
  shared mixin on a client that may serve concurrent sessions; per-turn state
  must be a local inside `stream_voice()`.
- ~~`NovaAudio.__init__`~~ — does not exist and must not be added (MRO constraint).

---

## Implementation Notes

### Pattern to Follow

```python
@dataclass
class _TurnState:
    """Receive-side state carried across frames within one Nova Sonic turn.

    Nova reports the speaker and generation stage on ``contentStart``, not on
    the ``textOutput`` frames they govern, so this must persist between frames.
    """
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None        # used by TASK-2105
    pending_tool_raw_input: Optional[str] = None       # used by TASK-2105


# inside stream_voice(), alongside the other per-turn locals (line ~397):
turn_state = _TurnState()

# in the receive loop, BEFORE the textOutput branch:
content_start = event.get("contentStart")
if content_start:
    turn_state.role = content_start.get("role")
    turn_state.generation_stage = _parse_generation_stage(
        content_start.get("additionalModelFields")
    )
    continue
```

Helper, module-private, must not raise on malformed input:

```python
def _parse_generation_stage(additional_model_fields: Any) -> Optional[str]:
    """Extract ``generationStage`` from a contentStart's additionalModelFields.

    Nova sends this as a JSON *string*. Returns None when absent or malformed —
    callers treat None as "no stage reported" and emit the text.
    """
    if not additional_model_fields:
        return None
    try:
        if isinstance(additional_model_fields, str):
            additional_model_fields = json.loads(additional_model_fields)
        return additional_model_fields.get("generationStage")
    except (ValueError, AttributeError):
        return None
```

### Key Constraints

- **Missing stage must EMIT, not suppress.** Suppress only when
  `generation_stage is not None and generation_stage != "SPECULATIVE"`. A strict
  `== "SPECULATIVE"` test would silently drop all assistant text if Nova ever
  omits `additionalModelFields` — spec §7 calls this out explicitly.
- Only `role == "ASSISTANT"` text is filtered by stage. USER transcription is
  always emitted (it has no generation stage).
- `accumulated_text` accumulates **assistant text only**. The terminal
  `completionEnd` frame and the reconnect/interrupt frames at lines 461/476 all
  read it.
- Reset `generation_stage` on each new `contentStart` so a stale stage cannot
  leak into the next content block.
- `json` is already imported at the top of `nova/audio.py` (added by the
  transport fix) — verify before re-adding.

### References in Codebase

- `nova_sonic_simple.py:250-269` (AWS sample) — the authoritative logic.
- `packages/ai-parrot/tests/clients/test_nova_audio_sdk.py` — the
  `_FakeDuplexStream` / `_payload_chunk` helpers; for THIS task you can bypass
  the SDK entirely by patching `_iter_events` with a plain async generator of
  already-unwrapped dicts.

---

## Acceptance Criteria

- [ ] A USER `contentStart` followed by `textOutput` yields
      `LiveVoiceResponse.role == "USER"`.
- [ ] An ASSISTANT `contentStart` with `generationStage: "SPECULATIVE"` followed
      by `textOutput` yields `role == "ASSISTANT"` and the text.
- [ ] An ASSISTANT `contentStart` with a non-SPECULATIVE stage suppresses its
      `textOutput`.
- [ ] An ASSISTANT `contentStart` with **no** `additionalModelFields` still
      emits its `textOutput` (missing stage ⇒ emit).
- [ ] Malformed `additionalModelFields` (not JSON) does not raise; treated as
      no stage.
- [ ] The terminal frame's `text` contains assistant text only — a full turn
      with both USER and ASSISTANT text never leaks the user's words into it.
- [ ] A full synthesized turn yields the assistant reply exactly once (no
      duplication).
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
      and `pytest packages/ai-parrot-integrations/tests/voice/ -q`
- [ ] No AWS access required by any test.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_turn_state.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient


def _client():
    return NovaClient(model="nova-2-sonic", region="us-east-1", voice_id="matthew")


async def _run(frames):
    """Feed already-unwrapped frames through stream_voice()."""
    client = _client()

    async def iter_events(_stream):
        for frame in frames:
            yield frame

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=AsyncMock()), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()):
        return [r async for r in client.stream_voice(audio())]


SPECULATIVE = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
               "additionalModelFields": '{"generationStage": "SPECULATIVE"}'}}
FINAL = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
         "additionalModelFields": '{"generationStage": "FINAL"}'}}
USER = {"contentStart": {"role": "USER", "type": "TEXT"}}
END = {"completionEnd": {}}


class TestRoleAttribution:
    @pytest.mark.asyncio
    async def test_user_text_attributed_to_user(self):
        out = await _run([USER, {"textOutput": {"content": "weather?"}}, END])
        assert [r.role for r in out if r.text] == ["USER"]

    @pytest.mark.asyncio
    async def test_assistant_speculative_text_emitted(self):
        out = await _run([SPECULATIVE, {"textOutput": {"content": "Sunny."}}, END])
        texts = [(r.role, r.text) for r in out if r.text]
        assert texts == [("ASSISTANT", "Sunny.")]

    @pytest.mark.asyncio
    async def test_assistant_non_speculative_text_suppressed(self):
        out = await _run([FINAL, {"textOutput": {"content": "Sunny."}}, END])
        assert [r for r in out if r.text and r.role == "ASSISTANT"] == []

    @pytest.mark.asyncio
    async def test_missing_stage_still_emits(self):
        """Regression guard: a strict == SPECULATIVE test would drop everything."""
        no_stage = {"contentStart": {"role": "ASSISTANT", "type": "TEXT"}}
        out = await _run([no_stage, {"textOutput": {"content": "Sunny."}}, END])
        assert any(r.text == "Sunny." for r in out)

    @pytest.mark.asyncio
    async def test_malformed_additional_model_fields_does_not_raise(self):
        bad = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
                                "additionalModelFields": "not json{"}}
        out = await _run([bad, {"textOutput": {"content": "Sunny."}}, END])
        assert any(r.text == "Sunny." for r in out)


class TestAccumulation:
    @pytest.mark.asyncio
    async def test_terminal_text_excludes_user_transcription(self):
        out = await _run([
            USER, {"textOutput": {"content": "what is the weather"}},
            SPECULATIVE, {"textOutput": {"content": "It is sunny."}},
            END,
        ])
        terminal = [r for r in out if r.is_complete][-1]
        assert "what is the weather" not in terminal.text

    @pytest.mark.asyncio
    async def test_assistant_reply_not_duplicated(self):
        out = await _run([
            SPECULATIVE, {"textOutput": {"content": "It is sunny."}},
            FINAL, {"textOutput": {"content": "It is sunny."}},
            END,
        ])
        assert [r.text for r in out if r.text] == ["It is sunny."]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2100 is in `sdd/tasks/completed/`; this
   task sets `LiveVoiceResponse.role`, which TASK-2100 creates
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm `_iter_events()` still unwraps the envelope (read its docstring)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2102-turn-state-role-and-generation-stage.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Added module-private `_TurnState` dataclass (role,
generation_stage, plus the two pending-tool slots reserved for TASK-2105) and
`_parse_generation_stage()` helper next to the other module-private helpers
above `NovaAudio`. Added `from dataclasses import dataclass` (not previously
imported). Instantiated `turn_state = _TurnState()` as a per-turn local
(never on `self`). In the receive loop: added a `contentStart` branch before
`textOutput` that records `role`/`generation_stage` and `continue`s;
rewrote the `textOutput` branch to attribute `role` on the yielded
`LiveVoiceResponse`, suppress ASSISTANT text only when
`generation_stage is not None and generation_stage != "SPECULATIVE"`
(missing stage still emits), and accumulate into `accumulated_text` only
when `role == "ASSISTANT"`. Left the `completionEnd` branch's `text=""`
unchanged — it is not one of the lines the spec's Gap Sites table lists
under gap 5 (`nova/audio.py:398, 461, 476, 485, 491` in the pre-task
numbering), and the acceptance criterion ("terminal frame's text contains
assistant text only") already holds trivially for an empty string; changing
it would be scope creep beyond this task's Scope section. Barge-in
(currently the pre-existing `"interruption" in event` check) intentionally
left untouched for TASK-2103. Created `test_nova_turn_state.py` with all 7
tests from the Test Specification (with the same `sys.modules` SDK-stub
addition as TASK-2101, for the same "passes on 3.11 and 3.13" reason).
Regression: 133 passed/3 skipped (`-k "nova or bedrock"`, up from 126, +7
new tests), 108 passed/1 skipped (`voice/`), 0 regressions. New ruff
findings are all `UP045` (5 new, same pre-existing style category — the new
`Optional[str]`/`Optional[LiveToolCall]` fields on `_TurnState` and the new
helper's `Optional[str]` return, matching the task's required
`Optional[str]` idiom); `BLE001` count unchanged (2, pre-existing,
unrelated to this task's lines).

**Deviations from spec**: none (see Notes on `completionEnd` being
intentionally out of scope).
