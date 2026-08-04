# TASK-2103: Detect barge-in from the interrupted payload, not a phantom key

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2102
**Assigned-to**: unassigned

---

## Context

Implements spec Module 4 (gap 8). `stream_voice()` detects barge-in with:

```python
if "interruption" in event or event.get("stopReason") == "INTERRUPTED":   # line 473
```

**Neither of those strings appears anywhere in AWS's Nova Sonic samples.** The
sample detects interruption by testing whether the `textOutput` *content*
carries the interrupted payload (`nova_sonic_tool_use.py:632`):

```python
if '{ "interrupted" : true }' in text_content:
```

So barge-in has almost certainly never been detected. Since the signal arrives on
a `textOutput` frame, this task builds on TASK-2102's `textOutput` handling.

---

## Scope

- Remove the `"interruption"` / `stopReason == "INTERRUPTED"` check at line 473.
- Detect interruption from `textOutput` content: parse it as JSON and check the
  `interrupted` key when it parses; fall back to a **whitespace-insensitive**
  substring test when it does not.
- Keep the emitted response shape identical: `is_interrupted=True`,
  `is_complete=True`, `turn_metadata.was_interrupted = True`, and reset
  `accumulated_text` — existing consumers depend on this.
- Do not emit the interrupted payload itself as assistant text.
- Tests, including a regression guard that detection no longer depends on the
  removed keys.

**NOT in scope**: changing what consumers do with `is_interrupted`; stopping
audio playback (that is the client's job — `examples/clients/nova/audio.py`
already does it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | Replace the barge-in check |
| `packages/ai-parrot/tests/clients/test_nova_barge_in.py` | CREATE | Detection + regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.
> TASK-2102 will have moved the `textOutput` branch — **re-read before editing**.

### Verified Imports

```python
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py:10
from parrot.clients.live import LiveVoiceResponse    # verified: clients/live.py:156
from parrot.clients.live import VoiceTurnMetadata    # verified: clients/live.py:140
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py — the code to REPLACE
if "interruption" in event or event.get("stopReason") == "INTERRUPTED":   # line 473
    turn_metadata.was_interrupted = True
    yield LiveVoiceResponse(
        text=accumulated_text,        # line 476
        is_complete=True,
        is_interrupted=True,
        usage=usage,
        turn_metadata=turn_metadata,
        session_id=session_id, turn_id=turn_id, user_id=user_id,
    )
    accumulated_text = ""             # line 485
    continue

# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class VoiceTurnMetadata:                  # line 140
    was_interrupted: bool = False          # verified present
```

### Does NOT Exist

- ~~`event["interruption"]`~~ — not a Nova Sonic frame key. Appears in no AWS
  sample. **Being removed by this task.**
- ~~`event["stopReason"]`~~ — not emitted on the bidirectional voice stream
  (`stopReason` belongs to the *Converse* text API). **Being removed.**
- ~~`event["interrupted"]`~~ — not a top-level frame key either; the signal is
  inside `textOutput.content`.
- ~~`LiveVoiceResponse.interrupted`~~ — the field is `is_interrupted`.

---

## Implementation Notes

### Pattern to Follow

Do **not** hard-code the sample's exact spacing — `'{ "interrupted" : true }'`
is one serialization of a JSON object and the whitespace is incidental:

```python
def _is_interruption_payload(content: str) -> bool:
    """Return whether a textOutput content payload signals barge-in.

    Nova signals interruption by sending an ``{"interrupted": true}`` object as
    the text content. Parse it rather than matching the sample's exact
    whitespace, falling back to a whitespace-insensitive substring test for
    payloads embedded in surrounding text.
    """
    if not content:
        return False
    try:
        parsed = json.loads(content)
    except ValueError:
        compact = "".join(content.split())
        return '"interrupted":true' in compact
    return bool(isinstance(parsed, dict) and parsed.get("interrupted"))
```

Then, inside the `textOutput` branch added by TASK-2102, check this **before**
attributing or accumulating the text, and `continue` after yielding.

### Key Constraints

- The interrupted payload must **not** be yielded as assistant text or added to
  `accumulated_text` — it is a control signal, not speech.
- Preserve the existing emitted shape exactly (`is_interrupted`, `is_complete`,
  `was_interrupted`, `accumulated_text` reset) so `VoiceBot`,
  `VoiceChatHandler` and the example keep working untouched.
- Coordinate with TASK-2102: both touch the `textOutput` branch. Land 2102
  first (declared dependency) and add this check at the top of that branch.

### References in Codebase

- `nova_sonic_tool_use.py:632` (AWS sample) — the authoritative check.
- `examples/clients/nova/audio.py` — consumes the `interrupted` frame and stops
  queued playback; useful for an end-to-end sanity read.

---

## Acceptance Criteria

- [ ] A `textOutput` whose content is `{ "interrupted" : true }` (sample
      spacing) yields `is_interrupted=True` and `is_complete=True`, and sets
      `turn_metadata.was_interrupted`.
- [ ] The same payload with different whitespace (`{"interrupted":true}`) is
      also detected.
- [ ] The interrupted payload never appears in any yielded `text` nor in the
      accumulated terminal text.
- [ ] Ordinary assistant text containing the word "interrupted" is **not**
      misdetected.
- [ ] Regression: the strings `"interruption"` and `"INTERRUPTED"` no longer
      appear in `nova/audio.py`'s detection logic.
- [ ] All existing tests pass, including the pre-existing
      `test_stream_voice_barge_in` in `test_nova.py` — **note it feeds
      `{"interruption": True}` and will need updating to the real frame shape as
      part of this task.**
- [ ] No AWS access required.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_barge_in.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient

ASSISTANT = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
             "additionalModelFields": '{"generationStage": "SPECULATIVE"}'}}


async def _run(frames):
    client = NovaClient(model="nova-2-sonic", region="us-east-1")

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=AsyncMock()), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()):
        return [r async for r in client.stream_voice(audio())]


class TestBargeIn:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [
        '{ "interrupted" : true }',   # exact sample spacing
        '{"interrupted":true}',       # compact
        '{\n  "interrupted": true\n}',
    ])
    async def test_detected_from_payload(self, payload):
        out = await _run([ASSISTANT, {"textOutput": {"content": payload}}])
        interrupted = [r for r in out if r.is_interrupted]
        assert len(interrupted) == 1
        assert interrupted[0].is_complete is True
        assert interrupted[0].turn_metadata.was_interrupted is True

    @pytest.mark.asyncio
    async def test_payload_not_emitted_as_text(self):
        out = await _run([ASSISTANT,
                          {"textOutput": {"content": '{"interrupted":true}'}}])
        assert all("interrupted" not in (r.text or "") for r in out)

    @pytest.mark.asyncio
    async def test_ordinary_text_mentioning_interrupted_not_misdetected(self):
        out = await _run([ASSISTANT,
                          {"textOutput": {"content": "Sorry, I interrupted you."}},
                          {"completionEnd": {}}])
        assert not any(r.is_interrupted for r in out)

    def test_legacy_keys_removed_from_source(self):
        """Regression guard: neither phantom key drives detection any more."""
        from pathlib import Path
        from parrot.clients.nova import audio as audio_mod
        source = Path(audio_mod.__file__).read_text(encoding="utf-8")
        assert '"interruption" in event' not in source
        assert 'stopReason") == "INTERRUPTED"' not in source
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2102 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Re-locate the `textOutput` branch, which TASK-2102 restructured
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2103-barge-in-detection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Removed the `"interruption" in event or event.get("stopReason") ==
"INTERRUPTED"` check entirely. Added a module-private `_is_interruption_payload()`
helper (JSON-parse first, whitespace-insensitive substring fallback) next to
`_parse_generation_stage()`. Moved the check inside the `textOutput` branch
TASK-2102 built, checked first (before role/stage attribution), preserving
the exact emitted shape (`is_interrupted=True`, `is_complete=True`,
`turn_metadata.was_interrupted = True`, `accumulated_text` reset to `""`)
and `continue`-ing so the interrupted payload is never yielded as text or
accumulated. Updated the pre-existing `test_stream_voice_barge_in` in
`test_nova.py` (flagged by the task) to feed `{"textOutput": {"content":
'{"interrupted":true}'}}` instead of the old `{"interruption": True}` frame.
Created `test_nova_barge_in.py` with all 4 tests from the Test
Specification (parametrized detection across 3 payload whitespace variants,
non-emission, false-positive guard, and the source-string regression
guard) — 6 collected/passed. Regression: 139 passed/3 skipped (`-k "nova or
bedrock"`, up from 133, +6 new), 108 passed/1 skipped (`voice/`), 0
regressions. Lint: audio.py and test_nova.py both match their pre-task
baselines exactly (19 and 2 errors respectively) — no new findings.

**Deviations from spec**: none
