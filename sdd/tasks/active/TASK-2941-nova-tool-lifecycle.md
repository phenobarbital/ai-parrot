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

Pending implementation and verification. No runtime or live acceptance is claimed by task creation.

**Completed by**: unassigned
**Date**: pending
**Notes**: pending
**Deviations from spec**: none recorded
