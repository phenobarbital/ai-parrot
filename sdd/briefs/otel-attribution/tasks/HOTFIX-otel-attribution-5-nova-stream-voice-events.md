# HOTFIX-otel-attribution-5: NovaAudio.stream_voice emits client lifecycle events

**Feature**: otel-attribution — tag every agent LLM call's OTel telemetry with agent and tenant
**Spec**: `sdd/briefs/otel-attribution.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)` emits lifecycle events on its text path
(`BedrockConverseBase`, e.g. `ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:1120`, with
`client_name=self.client_name`), but its voice path `NovaAudio.stream_voice`
(`ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:1293`) emits nothing. `VoiceBot.ask_stream`
calls `client.stream_voice(...)` (`bots/voice.py:659`), so a Nova Sonic voice session produces no LLM span or
metric. The operator chose to include this in the brief (Q&A).

## Scope

In `NovaAudio.stream_voice` (one before/after-or-failed pair **per session**):

1. Immediately before the outer `try:` (`audio.py:1849`): `_lc_tc = self._emit_before_call(
   client_name=self.client_name, model=self.model or "", temperature=None, system_prompt=system_prompt,
   has_tools=<True when tools are configured for the session, else False>, parent_trace=None)`,
   `_lc_t0 = time.perf_counter()`, `_lc_error: Optional[BaseException] = None`.
2. Tokens: `usage` is one `LiveCompletionUsage` per session (`audio.py:1403`), set from Nova's `usageEvent`
   (`:2013-2036`, totals assigned, not summed). Report `usage.input_tokens` / `usage.output_tokens` at session end
   (`None` when 0).
3. In `except Exception as exc:` (`:2175`), set `_lc_error = exc` **unless** the existing `is_idle_timeout` (`:2190`)
   check is true — Nova's 55 s idle `ValidationException` is a normal session end (the code already logs it at
   INFO). Leave `except asyncio.CancelledError:` (`:2172`) unchanged (normal end for telemetry).
4. Add a `finally:` to that same outer `try` statement that emits exactly once: `_emit_failed_call(...)` when
   `_lc_error` is set, otherwise `_emit_after_call(..., input_tokens=..., output_tokens=..., finish_reason=None)`.
   Wrap the emission in `try/except Exception` and log at debug. It must also run on early `aclose()`.
5. Tests in a new `packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py`.

**NOT in scope**: per-turn events, the text path, the sender task, reconnect logic, Gemini Live
(HOTFIX-otel-attribution-4).

## Files to Create / Modify

| File | Action | What |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | MODIFY | session-level lifecycle events in `stream_voice` |
| `packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py` | CREATE | tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.amazon.nova.client import NovaClient    # nova/client.py:34
from parrot.models.voice import LiveCompletionUsage          # models/voice.py:263
from parrot.core.events.lifecycle.events import BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py  (class AbstractClient, :297) — inherited by NovaClient
def _emit_before_call(self, *, client_name, model, temperature=None, system_prompt=None,
                      has_tools=False, parent_trace=None) -> "TraceContext"                      # :638
async def _emit_after_call(self, tc, *, client_name, model, duration_ms, input_tokens=None,
                           output_tokens=None, finish_reason=None, usage=None) -> Optional[float]  # :775
async def _emit_failed_call(self, tc, *, client_name, model, duration_ms, exc) -> None           # :898

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py
class NovaAudio:                                                                                  # :349
    async def stream_voice(self, audio_iterator, system_prompt=None, session_id=None, user_id=None,
                           stt_only=False, options=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]   # :1293
    #   :1403 usage = LiveCompletionUsage()   :1849 try:   :2013 usage_event = event.get("usageEvent")
    #   :2172 except asyncio.CancelledError:   :2175 except Exception as exc:   (is_idle_timeout computed below)
```

`"nova"` maps to `aws.bedrock` in `observability/attributes.py:67`; use `self.client_name` exactly as the
text path does (`bedrock.py:1121`).

### Does NOT Exist

- ~~Lifecycle emission anywhere in `nova/audio.py`~~ today.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py#NovaAudio",
    "sym:packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py#NovaAudio.stream_voice",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_before_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_failed_call"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Same rules as HOTFIX-otel-attribution-4: emit in the generator body, exactly one terminal event, emission
  errors never mask the stream's exit, no `yield` in `finally`.
- An idle-timeout end must produce an after event, not a failed event.

## Implementation Blueprint

### Steps (in order)

1. Before-event, timer, error slot before `:1849`.
2. `_lc_error = exc` in `except Exception` unless idle timeout.
3. `finally` with the single terminal emission using the session `usage`.
4. Tests, following the fake bidirectional-stream approach in `packages/ai-parrot/tests/clients/test_nova_audio_sdk.py`.

## Acceptance Criteria

- [ ] A fake session that delivers a `usageEvent` emits one `BeforeClientCallEvent` and one `AfterClientCallEvent`
      carrying those token totals.
- [ ] A session failing with a non-idle exception emits one `ClientCallFailedEvent` and no after event.
- [ ] An idle-timeout `ValidationException`, a cancellation and an early `aclose()` each emit one `AfterClientCallEvent`.
- [ ] With `current_agent_name` / `current_tenant` bound, the emitted events carry them.
- [ ] Existing Nova tests still pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py -q`
- `pytest packages/ai-parrot/tests/clients/test_nova_audio_sdk.py -q`
- `pytest packages/ai-parrot/tests/clients/test_nova_audio_guard.py -q`
- `pytest packages/ai-parrot/tests/clients/test_nova.py -q`

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_stream_voice_events.py
# Reuse the fake stream from test_nova_audio_sdk.py; record events by patching the three _emit_* helpers.
# - test_session_with_usage_event_emits_one_pair_with_totals
# - test_session_error_emits_failed_only
# - test_idle_timeout_emits_after_not_failed
# - test_cancelled_and_aclosed_sessions_emit_after
# - test_events_carry_bound_agent_and_tenant
```

## Agent Instructions

1. Work in the brief worktree (`fix-otel-attribution-otel-attribution`), never on `dev`.
2. Read `sdd/briefs/otel-attribution.brief.md` (Decisions, Assumptions: voice granularity).
3. Verify the anchors above; if one moved, update this file first.
4. Mark this task `in-progress` and commit only the index file.
5. Implement; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-amazon/src`.
6. Commit only the two files above: `fix(otel-attribution): HOTFIX-otel-attribution-5 — Nova voice session events`.
7. Close with `parrot sdd task close HOTFIX-otel-attribution-5 otel-attribution verified`, fill in the
   Completion Note, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
