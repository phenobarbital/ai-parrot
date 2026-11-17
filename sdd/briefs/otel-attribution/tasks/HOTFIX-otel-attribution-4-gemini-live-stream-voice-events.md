# HOTFIX-otel-attribution-4: GeminiLiveClient.stream_voice emits client lifecycle events

**Feature**: otel-attribution — tag every agent LLM call's OTel telemetry with agent and tenant
**Spec**: `sdd/briefs/otel-attribution.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`VoiceBot.ask_stream` (`bots/voice.py:659`) drives audio sessions through `client.stream_voice(...)`. For the
default provider, `GeminiLiveClient.stream_voice` (`ai-parrot-client-google/src/parrot/clients/google/live.py:693`)
never calls the `AbstractClient._emit_*` helpers, so a voice session produces no LLM span and no LLM metric —
with or without agent/tenant binding. `GeminiLiveClient.ask` (`live.py:1290`) already emits
(`_emit_before_call` at `:1324`, `_emit_failed_call` at `:1443`, `_emit_after_call` at `:1461`); mirror it.

This task was added as a brief **assumption** after the Q&A round (the operator chose to include Nova voice;
Gemini Live has the same gap). It is independent: drop the task file and its index entry to descope it.

## Scope

In `GeminiLiveClient.stream_voice` (one before/after-or-failed pair **per session**):

1. Immediately before the outer `try:` (`live.py:803`, after the `"Starting voice session ..."` log at `:801`):
   `_lc_tc = self._emit_before_call(client_name="gemini-live", model=self.model or "", temperature=None,
   system_prompt=system_prompt, has_tools=<True when tools are configured for the session, else False>,
   parent_trace=None)`, `_lc_t0 = time.perf_counter()`, `_lc_error: Optional[BaseException] = None`, and two
   session accumulators `_lc_in_tokens = 0`, `_lc_out_tokens = 0`.
2. `usage` is per turn: it is rebound at `live.py:980` after each `turn_complete` (`:957`). Immediately before
   that rebinding, add the finished turn's `usage.input_tokens` / `usage.output_tokens` to the accumulators. At
   session end, add the current (last, possibly partial) turn's tokens once.
3. In `except Exception as e:` (`:1159`), set `_lc_error = e` as its first statement. Leave
   `except asyncio.CancelledError:` (`:1156`) unchanged — a cancelled session is a normal end for telemetry.
4. Add a `finally:` to that same outer `try` statement that emits exactly once: `_emit_failed_call(_lc_tc,
   client_name="gemini-live", model=..., duration_ms=..., exc=_lc_error)` when `_lc_error` is set, otherwise
   `_emit_after_call(_lc_tc, client_name="gemini-live", model=..., duration_ms=..., input_tokens=<total or None
   when 0>, output_tokens=<total or None when 0>, finish_reason=None)`. Wrap the emission in
   `try/except Exception` and log at debug, so telemetry never masks the stream's own exit. It must also run when
   the consumer closes the generator early (`aclose()` → `GeneratorExit`).
5. Tests in a new `packages/ai-parrot/tests/clients/test_live_stream_voice_events.py`.

**NOT in scope**: per-turn events, `GeminiLiveClient.ask`, `_audio_sender`, session-resumption logic, Nova
(HOTFIX-otel-attribution-5).

## Files to Create / Modify

| File | Action | What |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` | MODIFY | session-level lifecycle events in `stream_voice` |
| `packages/ai-parrot/tests/clients/test_live_stream_voice_events.py` | CREATE | tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.google.live import GeminiLiveClient
from parrot.models.voice import LiveCompletionUsage        # models/voice.py:263 (fields input_tokens/output_tokens)
from parrot.core.events.lifecycle.events import BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py  (class AbstractClient, :297)
def _emit_before_call(self, *, client_name: str, model: str, temperature=None, system_prompt=None,
                      has_tools: bool = False, parent_trace=None) -> "TraceContext"          # :638
async def _emit_after_call(self, tc, *, client_name: str, model: str, duration_ms: float,
                           input_tokens=None, output_tokens=None, finish_reason=None, usage=None) -> Optional[float]  # :775
async def _emit_failed_call(self, tc, *, client_name: str, model: str, duration_ms: float, exc: Exception) -> None  # :898

# packages/ai-parrot-client-google/src/parrot/clients/google/live.py
class GeminiLiveClient(...):
    async def stream_voice(self, ...)  -> AsyncIterator[LiveVoiceResponse]   # :693
    #   :787 usage = LiveCompletionUsage()      :803 try:
    #   :821 usage.merge_tokens(LiveCompletionUsage.from_gemini_usage(response.usage_metadata))
    #   :957 if getattr(server_content, "turn_complete", False):   :980 usage = LiveCompletionUsage()
    #   :1156 except asyncio.CancelledError:   :1159 except Exception as e:
    async def ask(self, ...)                                                   # :1290 — emission pattern :1324-1470
```

`"gemini-live"` is a known client name (`observability/attributes.py` maps it to `gemini`).

### Does NOT Exist

- ~~A session-level token total in `stream_voice`~~ — `usage` is per turn; this task adds the accumulators.
- ~~Lifecycle emission anywhere in `stream_voice`~~ today.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/live.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/clients/test_live_stream_voice_events.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient.stream_voice",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/live.py#GeminiLiveClient.ask",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_before_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_after_call",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient._emit_failed_call"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `_emit_before_call` captures agent, user, session and (after HOTFIX-otel-attribution-1) tenant from
  ContextVars at construction — call it in the generator body, never in a background task.
- Emit exactly one terminal event per session; an exception raised by the emission must not replace the
  stream's own exception or response.
- `stream_voice` is an async generator: awaiting in its `finally` is allowed; yielding there is not.

## Implementation Blueprint

### Steps (in order)

1. Before-event, timer, error slot and accumulators before `:803`.
2. Fold each finished turn's tokens before the rebinding at `:980`.
3. `_lc_error = e` in `except Exception`.
4. `finally` with the single terminal emission.
5. Tests, following the fake-session approach in `packages/ai-parrot/tests/clients/test_live_usage_metadata.py`.

## Acceptance Criteria

- [ ] A two-turn fake session emits one `BeforeClientCallEvent` and one `AfterClientCallEvent` whose token counts
      are the sum of both turns.
- [ ] A session failing with an exception emits one `ClientCallFailedEvent` and no after event.
- [ ] Cancellation and early `aclose()` each emit one `AfterClientCallEvent`.
- [ ] With `current_agent_name` / `current_tenant` bound, the emitted events carry them.
- [ ] Existing live client tests still pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/clients/test_live_stream_voice_events.py -q`
- `pytest packages/ai-parrot/tests/clients/test_live_usage_metadata.py -q`
- `pytest packages/ai-parrot/tests/clients/test_live_resumption.py -q`
- `pytest packages/ai-parrot/tests/clients/test_live_envelope.py -q`

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_live_stream_voice_events.py
# Capture events by subscribing to the client's event registry (or patch _emit_before_call/_emit_after_call/
# _emit_failed_call with recorders) and drive stream_voice with the fake live session used in
# test_live_usage_metadata.py.
# - test_two_turn_session_emits_one_pair_with_summed_tokens
# - test_session_error_emits_failed_only
# - test_cancelled_session_emits_after
# - test_early_aclose_emits_after
# - test_events_carry_bound_agent_and_tenant
```

## Agent Instructions

1. Work in the brief worktree (`fix-otel-attribution-otel-attribution`), never on `dev`.
2. Read `sdd/briefs/otel-attribution.brief.md` (Assumptions: voice granularity).
3. Verify the anchors above; if one moved, update this file first.
4. Mark this task `in-progress` and commit only the index file.
5. Implement; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src`.
6. Commit only the two files above: `fix(otel-attribution): HOTFIX-otel-attribution-4 — Gemini Live voice session events`.
7. Close with `parrot sdd task close HOTFIX-otel-attribution-4 otel-attribution verified`, fill in the
   Completion Note, commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) with gpt-5.6-luna (codex), 1 attempt
**Date**: 2026-11-12
**Status**: done-with-issues
**Notes**: GeminiLiveClient.stream_voice now emits before/after/failed client lifecycle events with token totals (google/live.py, telemetry in a finally); new tests/clients/test_live_stream_voice_events.py. Commits: merge 9ee9a26403.

Merge-tier validation did NOT settle green: the engine runs ended `timed_out` (second run exit -15/SIGTERM after ~1 min, no pytest summary; the first two runs ended `timed_out` with exit 0). No failure was observed in the tests that did run, and the cause of the stall is unidentified. Accepted by the operator as done-with-issues.

Three failing tests seen in the first validation log are NOT caused by this brief (static diff evidence vs origin/dev, not a baseline run): `test_agent_name_is_not_pii_field` -> issue:ea9f2f8ab334 (`user_id` already declared on AfterClientCallEvent on dev; this brief adds only `tenant`); `test_live_envelope.py::TestCanonicalRole` x2 -> issue:33b76e470d2b (stream_voice role handling untouched by this brief).

**Deviations from spec**: none in scope
**Status promoted to `done` (2026-11-12)** on the user's explicit instruction. The caveats above (unrun merge-tier validation, three known failing tests `issue:ea9f2f8ab334` / `issue:33b76e470d2b`, deferred review findings `issue:4591f0dd1f03` / `issue:6c08bea1a8b2` / `issue:2e7011858c08` / `issue:a694582dbb67`) still apply.
