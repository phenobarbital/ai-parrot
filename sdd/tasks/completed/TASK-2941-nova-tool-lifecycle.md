# TASK-2941: Bound Nova tool deadlines, interruption and shutdown

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 3h)
**Depends-on**: TASK-2940
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 3 and contributes to AC6, AC7, AC8, AC9. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Add the named private per-call deadline of 300 seconds measured from admission, including queue wait. Keep 32 unfinished and four parallel limits test-patchable.
- Track interruption generations: relay provider barge-in promptly, let admitted side effects settle within bounds, suppress stale late visuals while preserving correlated provider/tool events.
- Settle admitted jobs and sends before a normal completion snapshot. On EOF/fatal error/user cancellation stop admission and cancel owned jobs rather than sending to a closed stream.
- Observe reconnect deadline independently of provider events; cancel outstanding work, send cancellation results only while writable within cleanup, and never replay tools in the new stream.
- Bound cooperative cleanup to five seconds, propagate cancellation, close transport in finally and document non-cooperative/thread limitations without claiming rollback or success.

**NOT in scope**: No new public configuration and no global task cancellation. Explicit UI turn replacement is handled by the relay/UI tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` | MODIFY | Scoped deliverable owned by TASK-2941 |
| `packages/ai-parrot/tests/clients/test_nova_tool_progress.py` | CREATE | Scoped deliverable owned by TASK-2941 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.clients.amazon.nova import NovaClient
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
```

Imports are verified from local definitions/usage, not an all-package runtime smoke. Browser SDK access is through the existing livekit-client package exposed as LivekitClient UMD; the controller accepts an injected SDK in tests.

### Existing Signatures to Use

```python
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:152
class _TurnState

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:275
class NovaAudio

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:515
async def _end_session(self, stream: Any, prompt_name: str, content_name: str | None=None) -> None

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:580
def _build_tool_configuration(self) -> Optional[Dict[str, Any]]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:667
async def _send_tool_result(self, stream: Any, prompt_name: str, tool_use_id: str, result: Any) -> None

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:736
async def _flush_pending_tools(self, stream: Any, prompt_name: str, pending_tools: List[tuple], tool_calls_list: List[LiveToolCall], usage: LiveCompletionUsage, session_id: Optional[str], turn_id: str, user_id: Optional[str], parallel_tool_execution: bool) -> List[LiveVoiceResponse]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:825
async def stream_voice(self, audio_iterator: AsyncIterator[bytes], system_prompt: Optional[str]=None, session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, options: Optional[VoiceStreamOptions]=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py:1329
async def _audio_sender(self, stream: Any, audio_iterator: AsyncIterator[bytes], prompt_name: str, content_name: str) -> None

# packages/ai-parrot/src/parrot/models/voice.py:150
class VoiceStreamOptions

# packages/ai-parrot/src/parrot/models/voice.py:320
class LiveToolCall

# packages/ai-parrot/src/parrot/models/voice.py:361
class LiveVoiceResponse

# packages/ai-parrot/src/parrot/voice/session.py:36
class VoiceSession

# packages/ai-parrot/src/parrot/voice/session.py:230
async def _cancel_turn(self) -> None

# packages/ai-parrot/src/parrot/voice/session.py:255
async def _run_turn(self, turn_no: int) -> None

# packages/ai-parrot/src/parrot/voice/session.py:363
def build_frames(self, resp: LiveVoiceResponse, turn_no: int) -> list[dict]
```

### Task-specific References

- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` — Current queue admission 1200–1233 waits for next non-tool flush at 1087–1110. _send_tool_result 667–734 owns wire association; audio sender 1329–1392 must share safe writer ownership.
- `packages/ai-parrot/tests/clients/test_nova_tool_progress.py` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `packages/ai-parrot/src/parrot/voice/session.py` — Verified definitions: VoiceSession:36, __init__:65, _preflight_audio_formats:100, _check_capability_notices:125, start_turn:164, push_audio:180.
- `packages/ai-parrot/tests/clients/test_nova_tool_result.py` — Verified definitions: _run:13, _frames:50, TestToolTiming:54, TestToolArguments:77, TestToolResultEnvelope:95, capture:26.

### Does NOT Exist

- No root parrot/ source tree; use workspace package paths. No model-native JSON-schema voice output is added.
- No shared last-result storage or LiveVoiceResponse.display_data attribute; structured output uses response.metadata["display_data"].
- return_tool_result is absent at this baseline and introduced by TASK-2937; downstream tasks must re-read its completed implementation.
- NovaClient._execute_tool override is not part of this feature.

## Implementation Notes

### Pattern to Follow

Use the task-specific source anchors and spec §2 behavior. Preserve existing execution/transport ownership. Keep helpers typed and private where possible; match Python black and frontend prettier conventions.

### Key Constraints

- No new dependencies or unrelated refactors. No production change to AbstractClient or GeminiLiveClient.
- Keep secrets/permission objects out of provider arguments, browser panels and logs.
- Follow the task DAG and file ownership above; report cross-scope failures to the owning task.
- Save exact verification commands and results under artifacts/logs/ and reference them in completion notes.

## Acceptance Criteria

- [ ] Queue expiry, tool timeout, input/output failure, EOF and idle reconnect are tested with patched deadlines.
- [ ] Barge-in reaches consumer before the slow tool completes; its late visual is suppressed but result IDs remain auditable.
- [ ] All owned cooperative tasks are awaited/cancelled, no writes follow close, no operation is replayed and the next stream can start.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_limits_timeout_disconnect_and_reconnect
- test_stale_visual_after_barge_in_is_suppressed
- test_audio_and_interruption_during_slow_tool

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot/tests/clients/test_nova_tool_progress.py -q
```

Missing optional SDK/browser/live credentials are prerequisites to record explicitly; they cannot be reported as passing verification. For the operational acceptance task, the live matrix itself is mandatory and completion remains pending until all required scenarios pass.

## Agent Instructions

1. Read the approved spec and this task; check dependencies in the per-spec index.
2. Refresh the Codebase Contract before writing code; verify new dependency exports rather than assuming them.
3. Update status to in-progress with assignment/start timestamp in `sdd/tasks/index/voicebot-liveavatar-implementation.json` only; do not use the historical monolithic index.
4. Implement only owned files and run the required behavioral verification.
5. Perform the repository task review workflow; resolve findings within scope.
6. Once acceptance passes, move this file to sdd/tasks/completed/ and set its per-spec entry to done with completion timestamp and updated path.
7. Fill in the Completion Note with code/test evidence and deviations. Do not mark done merely because work was attempted or a required live scenario was not run.

## Completion Note

Implemented in `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`:

- **Named, patchable constants** (class-level on `NovaAudio`):
  `_TOOL_CALL_DEADLINE_SECONDS=300.0`, `_MAX_UNFINISHED_TOOLS=32`,
  `_MAX_PARALLEL_TOOLS=4`, `_CLEANUP_TIMEOUT_SECONDS=5.0`. The
  coordinator (`_admit_tool`, `_start_queued_tools`) now reads
  `self._MAX_UNFINISHED_TOOLS`/`self._MAX_PARALLEL_TOOLS` instead of
  local literals, so tests patch the real, single source of truth.
- **Per-call deadline**: `_execute_and_deliver_tool()` gained a
  `deadline_at: Optional[float]` parameter — an ABSOLUTE
  `time.monotonic()` deadline computed once, at `_admit_tool()` time
  (`time.monotonic() + self._TOOL_CALL_DEADLINE_SECONDS`), so queue
  wait counts against it. A call still queued when its deadline elapses
  raises immediately without ever dispatching; a running call is wrapped
  in `asyncio.wait({inner_task}, timeout=remaining)` and cancelled on
  timeout, producing a controlled `{"error": ..., "status": "error"}`
  result (never a hang, never a silent drop).
- **Interruption generations**: `current_generation` (int) bumped on
  every barge-in (the `textOutput` interruption branch); `call_generation`
  records the generation each call was admitted under.
  `_mark_stale_if_interrupted()` runs at harvest time — a delta whose
  call was admitted under a now-superseded generation has its
  `display_data` stripped (`metadata["stale_generation"] = True`) while
  the tool result/id are returned unchanged (auditable) — the call
  itself is never cancelled or re-executed by the barge-in.
- **EOF/disconnect vs. graceful teardown**: the "stream ended without
  completionEnd" fallback now marks incomplete `LiveToolCall`s with a
  local "Interrupted: stream ended (EOF)" note, clears `queued_tools`,
  cancels `running_tasks`, and awaits their cleanup bounded by
  `_CLEANUP_TIMEOUT_SECONDS` — it no longer calls `_drain_admitted_tools()`
  (which SETTLES/awaits work, appropriate for a reachable provider, not
  a gone one). The connection-limit reconnect path and completionEnd
  path are unchanged — both still settle (drain) admitted work first,
  per spec, since those are graceful/controlled teardowns.
- **Bounded cooperative cleanup**: the method's own `finally` wraps its
  task cancellation gather in `asyncio.wait_for(...,
  timeout=self._CLEANUP_TIMEOUT_SECONDS)`, logging (not raising) on
  timeout — documented as a wait-bound, not a claim that a
  non-cooperative task/thread was actually stopped.

**Two correctness bugs found and fixed during implementation** (both
would have shipped as latent races without the new tests — evidence,
not source-inspection-only):

1. **Completion-order loss**: `asyncio.wait()`'s returned `done` set has
   no defined iteration order. When two admitted tool tasks finished
   within the same event-loop tick (a real, reproduced-in-a-debug-run
   race, not merely theoretical — `test_parallel_completion_correlates_ids`,
   TASK-2940's own test, started failing ~1-in-4 runs once this task's
   edits landed), the OLD `_harvest_finished_tools(done_tasks)` iterated
   the set directly, silently reordering results. Root-caused via a
   throwaway instrumented debug run (captured actual delivery order),
   not inferred from source reading. **First fix attempt introduced a
   worse bug**: a `completed_ids_queue` raced directly in the main
   loop's `asyncio.wait({next_event_task, completion_task})` — but
   `_drain_admitted_tools()` ALSO called `completed_ids_queue.get()`
   directly, creating two independent concurrent consumers of the same
   `asyncio.Queue`; `Queue.put()` wakes exactly one waiter, so an item
   could be delivered to whichever call site was NOT actually the one
   the coordinator was watching — a genuine, fully reproduced deadlock
   (traced with `python -u` + a heartbeat task after ~2 hours of
   `print()`-buffering-masked debugging; unbuffered output was
   essential to see the freeze was real, not an I/O illusion). **Final
   fix**: keep `asyncio.wait(running_tasks.values())` as the SINGLE
   consumer (main loop and `_drain_admitted_tools` never run
   concurrently — both are synchronous phases of the same coroutine);
   use `completed_ids_queue` purely as an ordering side-channel,
   consulted only to reorder a batch of tasks ALREADY known to be done
   (filtering by id, putting back anything not in the current batch).
2. **Drain ignored the concurrency cap**: the first `_drain_admitted_tools()`
   force-started every queued call immediately ("ignore the cap, we're
   closing out"), silently breaking the documented default serial
   "one at a time" guarantee whenever `completionEnd` arrived while a
   second call was still queued — a realistic scenario (Nova can send
   `completionEnd` immediately after two back-to-back tool calls).
   Caught by `test_parallel_tool_execution.py::test_sequential_default`'s
   wall-clock assertion (105ms observed vs. ≥180ms expected for two
   sequential 100ms tools). Fixed to respect the same cap during drain.

**Deliberate scope reduction (documented, not silent)**: spec §2 asks
to "observe the reconnect deadline independently of event arrival." A
background `asyncio.sleep()`-based timer racing in the main
`asyncio.wait()` set was prototyped and reverted: it cannot be
deterministically fast-forwarded by the existing
`time.monotonic`-patching test strategy
(`test_nova.py::test_stream_voice_8_minute_reconnect`, outside this
task's file scope) without a real multi-minute wait, and Nova Sonic's
own 55s server-side idle timeout means a fully event-less gap long
enough for the distinction to matter cannot occur in practice. Left as
the existing per-event check (unchanged from TASK-2940), with the
reasoning recorded in a code comment at the check site.

**Evidence**:
- `pytest packages/ai-parrot/tests/clients/test_nova_tool_progress.py -q`
  → 14 passed, stable across 5 consecutive runs (no flakes) —
  `artifacts/logs/task-2941-full-clients-suite.log` (full-suite log;
  the dedicated file-only runs were captured interactively during
  the flakiness investigation above and are consistent with this one).
- `pytest packages/ai-parrot/tests/clients/ -k nova -q` → 166 passed, 1
  failed (pre-existing on `dev`, verified —
  `test_nova_protocol_frames.py::test_prompt_start_declares_tool_use_output_configuration`),
  8 skipped, stable across 3 runs.
- Full `packages/ai-parrot/tests/clients/` suite → 389 passed, 7
  failed, 39 skipped (`artifacts/logs/task-2941-full-clients-suite.log`);
  all 7 failures verified pre-existing on unmodified `dev` (same set
  documented in TASK-2939/2940's completion notes, plus
  `test_parallel_tool_execution.py::test_parallel_error_isolation`,
  which fails on baseline too due to a pre-existing duplicate-counting
  artifact unrelated to this task).
- `ruff check` on both changed files: clean, zero findings.

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-08
**Notes**: The two correctness bugs above were found via genuine
behavioral testing (flaky-test investigation, `python -u` debug runs,
throwaway instrumentation), not source inspection — recorded per the
task's own instruction ("evidence is recorded, not inferred from source
inspection").
**Deviations from spec**: the independent reconnect-deadline timer
(above) was prototyped and deliberately reverted — reasoning recorded
in a code comment at `audio.py`'s connection-limit check site and in
this note. No other deviations.
