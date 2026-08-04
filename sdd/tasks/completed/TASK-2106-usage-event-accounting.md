# TASK-2106: Populate token usage from Nova's usageEvent frames

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 7 (gap 7). Nova Sonic emits `usageEvent` frames
(`nova_sonic_tool_use.py:659-660` handles them), but `stream_voice()` never reads
them. The only fields ever populated on `LiveCompletionUsage` are
`tool_calls_executed` and `tool_execution_time_ms` (lines 538-539), so **voice
token counts are permanently zero** — visible in the example UI as
`"usage": null` / zeros on every turn.

> ⚠️ **This is the one gap whose frame *shape* is unverified.** The AWS sample
> only debug-prints the whole `usageEvent`; it does not name the fields. Spec §8
> open question 1 tracks this. Implement defensively (see Key Constraints) and
> record what you assumed.

---

## Scope

- Handle the `usageEvent` frame in the receive loop and map its token counts onto
  the existing per-turn `LiveCompletionUsage`.
- Accept several plausible key spellings, since the exact names are unconfirmed;
  an unrecognized shape must leave usage at zero rather than raise.
- Preserve the existing `tool_calls_executed` / `tool_execution_time_ms`
  accounting untouched.
- Tests, including one asserting an unknown shape is tolerated.

**NOT in scope**: changing `LiveCompletionUsage`'s fields; audio-duration
metrics (`input_audio_duration_ms` / `output_audio_duration_ms` — leave for a
follow-up once real frames are observed); usage on the text path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | Handle `usageEvent` |
| `packages/ai-parrot/tests/clients/test_nova_usage_event.py` | CREATE | Mapping + tolerance tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
from parrot.clients.nova import NovaClient             # verified: clients/nova/__init__.py:10
from parrot.clients.live import LiveCompletionUsage    # verified: clients/live.py:60
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveCompletionUsage:                          # line 60
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    input_tokens: int = 0                            # alias, synced in __post_init__
    output_tokens: int = 0                           # alias, synced in __post_init__
    input_audio_duration_ms: float = 0.0
    output_audio_duration_ms: float = 0.0
    response_time_ms: float = 0.0
    first_token_time_ms: float = 0.0
    tool_calls_executed: int = 0
    tool_execution_time_ms: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

# packages/ai-parrot/src/parrot/clients/nova/audio.py
usage = LiveCompletionUsage()          # line 397 — the per-turn instance to populate
usage.tool_calls_executed += 1         # line 538 — existing accounting, keep
usage.tool_execution_time_ms += tc.execution_time_ms   # line 539 — keep
```

### Does NOT Exist

- ~~a confirmed `usageEvent` field schema~~ — **unverified**. Do not assert exact
  key names as though they were known; see Key Constraints.
- ~~`LiveCompletionUsage.from_nova_usage()`~~ — no such classmethod. There IS a
  `from_gemini_usage()` (clients/live.py) — it is Gemini-specific, do not reuse.
- ~~`usage.tokens`~~ / ~~`usage.token_count`~~ — not fields.
- ~~`event["event"]["usageEvent"]`~~ — `_iter_events()` already unwraps.
- `__post_init__` syncs `input_tokens`→`prompt_tokens` **only at construction**.
  Mutating `input_tokens` later does NOT update `prompt_tokens`. Set the
  canonical fields directly.

---

## Implementation Notes

### Pattern to Follow

Defensive, additive, and honest about what it does not know:

```python
# Candidate key spellings, most-likely first. The Pre-Alpha samples do not
# document usageEvent's schema (spec §8 Q1), so probe rather than assume.
_USAGE_INPUT_KEYS = ("inputTokens", "promptTokens", "input_tokens")
_USAGE_OUTPUT_KEYS = ("outputTokens", "completionTokens", "output_tokens")
_USAGE_TOTAL_KEYS = ("totalTokens", "total_tokens")


def _first_int(source: Dict[str, Any], keys: tuple) -> Optional[int]:
    """Return the first key present in *source* whose value is an int."""
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


# in the receive loop:
usage_event = event.get("usageEvent")
if usage_event:
    # Nova may nest the counts under a "details"/"totals" sub-object; flatten
    # one level so both shapes work.
    flat = {**usage_event}
    for nested_key in ("details", "totals", "usage"):
        nested = usage_event.get(nested_key)
        if isinstance(nested, dict):
            flat.update(nested)
    if (value := _first_int(flat, _USAGE_INPUT_KEYS)) is not None:
        usage.prompt_tokens = value
    if (value := _first_int(flat, _USAGE_OUTPUT_KEYS)) is not None:
        usage.completion_tokens = value
    total = _first_int(flat, _USAGE_TOTAL_KEYS)
    usage.total_tokens = (
        total if total is not None
        else usage.prompt_tokens + usage.completion_tokens
    )
    # Keep the raw frame so the shape can be inspected from a real session.
    usage.extra["usage_event"] = usage_event
    self.logger.debug("Nova Sonic usageEvent: %s", usage_event)
    continue
```

### Key Constraints

- **Never raise on an unexpected shape.** An unrecognized `usageEvent` must leave
  the counters as they were. A wrong guess about field names must not break voice.
- Stash the raw frame in `usage.extra["usage_event"]` — that is how the real
  schema gets discovered from the first live session, closing spec §8 Q1.
- `log.debug` the frame for the same reason. Do not log at info (these arrive
  frequently).
- Set `prompt_tokens`/`completion_tokens` (canonical), not `input_tokens`/
  `output_tokens` (aliases only synced in `__post_init__`).
- Usage frames may arrive more than once per turn — **assign**, don't accumulate,
  unless a real session proves they are incremental. Note which you chose.

### References in Codebase

- `nova_sonic_tool_use.py:659-660` (AWS sample) — the only reference, and it only
  debug-prints the frame.
- `packages/ai-parrot/src/parrot/clients/live.py` — `LiveCompletionUsage`
  and `from_gemini_usage()` as a shape-mapping precedent (Gemini-specific).

---

## Acceptance Criteria

- [ ] A `usageEvent` carrying recognizable token counts populates
      `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`.
- [ ] `total_tokens` is derived as prompt+completion when the frame omits a total.
- [ ] An unrecognized `usageEvent` shape leaves counters at zero and does **not**
      raise.
- [ ] The raw frame is preserved in `usage.extra["usage_event"]`.
- [ ] `tool_calls_executed` and `tool_execution_time_ms` still accumulate
      correctly alongside.
- [ ] The terminal `LiveVoiceResponse.usage` reflects the counts, so
      `to_websocket_message()["usage"]` is no longer all zeros.
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
- [ ] No AWS access required.
- [ ] Completion Note records the assumed key names and whether usage frames were
      treated as absolute or incremental, so spec §8 Q1 can be closed against a
      real session.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_usage_event.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient

END = {"completionEnd": {}}


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


def _terminal_usage(out):
    return [r for r in out if r.is_complete][-1].usage


class TestUsageEvent:
    @pytest.mark.asyncio
    async def test_populates_token_counts(self):
        out = await _run([
            {"usageEvent": {"inputTokens": 12, "outputTokens": 30, "totalTokens": 42}},
            END,
        ])
        usage = _terminal_usage(out)
        assert usage.prompt_tokens == 12
        assert usage.completion_tokens == 30
        assert usage.total_tokens == 42

    @pytest.mark.asyncio
    async def test_total_derived_when_absent(self):
        out = await _run([{"usageEvent": {"inputTokens": 5, "outputTokens": 7}}, END])
        assert _terminal_usage(out).total_tokens == 12

    @pytest.mark.asyncio
    async def test_unknown_shape_tolerated(self):
        """The real schema is unverified — a wrong guess must not break voice."""
        out = await _run([{"usageEvent": {"somethingElse": {"nested": True}}}, END])
        usage = _terminal_usage(out)
        assert usage.total_tokens == 0
        assert out[-1].is_complete is True

    @pytest.mark.asyncio
    async def test_raw_frame_preserved_for_schema_discovery(self):
        frame = {"inputTokens": 1, "outputTokens": 2}
        out = await _run([{"usageEvent": frame}, END])
        assert _terminal_usage(out).extra["usage_event"] == frame

    @pytest.mark.asyncio
    async def test_websocket_usage_not_all_zero(self):
        out = await _run([
            {"usageEvent": {"inputTokens": 3, "outputTokens": 4}}, END,
        ])
        msg = [r for r in out if r.is_complete][-1].to_websocket_message()
        assert msg["usage"]["total_tokens"] == 7
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `LiveCompletionUsage`'s field names and that `__post_init__` only
     syncs aliases at construction time
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2106-usage-event-accounting.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Added module-level `_USAGE_INPUT_KEYS`/`_USAGE_OUTPUT_KEYS`/
`_USAGE_TOTAL_KEYS` candidate-key tuples and `_first_int()` helper next to
`_parse_tool_arguments()`. Added a `usageEvent` branch in the receive loop
(placed before the `toolUse` branch): flattens one level of nesting under
`details`/`totals`/`usage` sub-keys, sets `usage.prompt_tokens`/
`usage.completion_tokens` via `_first_int()` when a recognizable key is
found (leaving them unchanged otherwise), derives `total_tokens` as
prompt+completion when no total key matches, stashes the raw frame in
`usage.extra["usage_event"]`, logs at `debug` (not `info`, since these
arrive frequently), and `continue`s. `tool_calls_executed`/
`tool_execution_time_ms` accounting (TASK-2105's code) is untouched — a
different branch entirely. Created `test_nova_usage_event.py` with all 5
tests from the Test Specification. Regression: 158 passed/3 skipped (`-k
"nova or bedrock"`, up from 153, +5 new), 108 passed/1 skipped (`voice/`),
0 regressions. New lint findings (+1 UP006, +1 UP045) match the file's
existing style categories (`_first_int`'s `Dict[str, Any]` param and
`Optional[int]` return).
**Assumed usageEvent keys**: input — `inputTokens` / `promptTokens` /
`input_tokens`; output — `outputTokens` / `completionTokens` /
`output_tokens`; total — `totalTokens` / `total_tokens` (first match wins,
in that order); also probes one level of nesting under `details`/`totals`/
`usage` sub-objects. Per spec §8 Q1, none of this is verified against a
real Nova Sonic session — the raw frame is preserved in
`usage.extra["usage_event"]` specifically so the real shape can be read
off the first live session and this guess list corrected.
**Usage frames treated as**: absolute (assign, not accumulate) — chosen
per the task's explicit default ("assign, don't accumulate, unless a real
session proves they are incremental"); no evidence either way exists yet.

**Deviations from spec**: none
