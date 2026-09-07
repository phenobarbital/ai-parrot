# TASK-2942: Deduplicate tool frames and interrupt replaced avatar turns

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 3h)
**Depends-on**: TASK-2941
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 4 and contributes to AC1, AC8, AC10. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Track streamed tool IDs per turn/session in both _HandlerVoiceSession.build_frames and the direct _send_voice_response path.
- Send final-only calls once and suppress IDs already sent as deltas; preserve full Python completion snapshots. Reset bookkeeping for later turns and session close.
- Keep existing display_data.data, tool_call and response_chunk shapes and STT-only gating; do not deduplicate by tool name or payload.
- When existing start_recording explicitly replaces a voice turn, interrupt any active avatar before start_turn. Keep avatar failures isolated so ordinary WebSocket voice remains usable.
- Retain VoiceBot adapter/memory ownership and existing PCM/interrupt/finish behavior. Do not alter production VoiceAvatarSession.

**NOT in scope**: No new WebSocket event or raw-client protocol merge. Full provider integration is tested in TASK-2946.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Scoped deliverable owned by TASK-2942 |
| `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py` | MODIFY | Scoped deliverable owned by TASK-2942 |
| `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` | MODIFY | Scoped deliverable owned by TASK-2942 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.voice.handler import VoiceChatHandler, WebSocketConnection
from parrot.models.voice import LiveVoiceResponse, LiveToolCall, VoiceStreamOptions
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
from parrot.bots.voice import VoiceBot
```

Imports are verified from local definitions/usage, not an all-package runtime smoke. Browser SDK access is through the existing livekit-client package exposed as LivekitClient UMD; the controller accepts an injected SDK in tests.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/voice.py:89
class VoiceBot

# packages/ai-parrot/src/parrot/bots/voice.py:281
def _create_llm_client(self, config) -> VoiceCapable

# packages/ai-parrot/src/parrot/bots/voice.py:475
async def ask_stream(self, audio_input: Union[bytes, AsyncIterator[bytes]], session_id: Optional[str]=None, user_id: Optional[str]=None, stt_only: bool=False, **kwargs) -> AsyncIterator[LiveVoiceResponse]

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:184
class WebSocketConnection

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:296
class _AskStreamVoiceClient

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:353
class _HandlerVoiceSession

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:370
def build_frames(self, resp, turn_no: int) -> list

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:510
async def _relay(self, resp, turn_no: int) -> None

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1631
async def _run_voice_session(self, connection: WebSocketConnection) -> None

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1688
async def _send_voice_response(self, connection: WebSocketConnection, response: Any) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:55
class VoiceAvatarSession

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:223
async def speak(self, pcm: bytes) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:235
async def finish_turn(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:243
async def interrupt(self) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:252
async def aclose(self) -> None

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

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1274
async def _handle_start_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:208
def viewer_credentials(self) -> dict[str, str]
```

### Task-specific References

- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — display_data.data and tool_call frames at 437–458 and 1749–1778. Avatar request/response at 1150–1214 uses top-level avatar/tenant_id/avatar_id and viewer credentials. start_recording currently invokes start_turn without avatar interruption.
- `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py` — Verified definitions: _capable_mock_client:28, handler:60, connection:75, _sent_types:85, TestHandlerRefactor:89, TestFrameProtocolUnchanged:148.
- `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` — Verified definitions: handler:26, connection:41, test_gemini_audio_to_avatar_end_to_end:56, test_gemini_audio_mid_turn_no_finish:94, test_barge_in_clears_avatar:112, test_pcm_bytes_unchanged_no_resample:131.
- `packages/ai-parrot/src/parrot/models/voice.py` — Verified definitions: AudioFormat:27, VoiceProvider:34, VoiceConfig:55, VoiceStreamOptions:150, VoiceCapabilities:187, LiveCompletionUsage:263.
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` — viewer_credentials returns only livekit_url/client_token/room. speak forwards 24 kHz PCM unchanged. Session teardown method is aclose(), not close().
- `packages/ai-parrot/src/parrot/voice/session.py` — Verified definitions: VoiceSession:36, __init__:65, _preflight_audio_formats:100, _check_capability_notices:125, start_turn:164, push_audio:180.
- `packages/ai-parrot/src/parrot/bots/voice.py` — Verified definitions: VoiceBot:89, create_voice_bot:838, __init__:119, _default_voice_prompt:186, _resolve_llm_config:190, _create_llm_client:281.

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

- [ ] Delta plus final snapshot sends one tool frame; final-only call and next-turn ID reuse work on both relay paths.
- [ ] Concurrent connections do not share dedup state; text, display and STT-only behavior regressions pass.
- [ ] Explicit replacement interrupts avatar before the new turn; avatar exceptions do not stop recording or WebSocket delivery.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_tool_final_only_and_next_turn_id_reuse
- test_explicit_turn_replacement_interrupts_avatar
- test_avatar_failure_preserves_websocket_delivery

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pytest packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py -q
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
