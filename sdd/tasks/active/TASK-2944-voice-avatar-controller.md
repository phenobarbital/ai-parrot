# TASK-2944: Build subscriber lifecycle and single-source audio controller

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 4h)
**Depends-on**: TASK-2942
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run alongside TASK-2943; owns controller and its Vitest tests only.

---

## Context

Implements §3 Module 5 and contributes to AC14, AC15, AC16. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Create an SDK-injectable standalone ES module for one subscriber Room from active session_started.avatar viewer credentials; register listeners before connect and attach/detach remote video/audio tracks.
- Expose a small explicit controller interface for joining, teardown, status, output selection and playback callbacks; document it for the UI task. It is new, not an existing framework API.
- Keep microphone/camera publication absent. Guard deferred joins, track callbacks and reconnects with a generation token; teardown disconnects, removes listeners and detaches media idempotently.
- Implement the single audible source policy: fallback browser audio until avatar track can play; mute remote while clearing/stopping local PCM, suppress subsequent local playback then unmute remote.
- Support Room.startAudio user gesture, audio playback status, browser-output selection and intentional global mute. On failure resume only future local chunks and never override intentional mute.
- Keep tokens only in memory and avoid logging credentials. Failed/expired reconnect requires a new voice session from the owning page, not admin REST session creation.

**NOT in scope**: No HTML wiring or server changes. Reuse SDK lifecycle concepts, not the Svelte component or its REST-owned session. New module exports must be verified by the dependent task.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/static/avatar-viewer.js` | CREATE | Scoped deliverable owned by TASK-2944 |
| `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts` | CREATE | Scoped deliverable owned by TASK-2944 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
from parrot.voice.handler import VoiceChatHandler, WebSocketConnection
```

Imports are verified from local definitions/usage, not an all-package runtime smoke. Browser SDK access is through the existing livekit-client package exposed as LivekitClient UMD; the controller accepts an injected SDK in tests.

### Existing Signatures to Use

```python
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

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1274
async def _handle_start_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:208
def viewer_credentials(self) -> dict[str, str]
```

### Task-specific References

- `examples/clients/voice/static/avatar-viewer.js` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts` — NEW deliverable of this feature; verify dependent task exports before importing.
- `packages/ai-parrot-server/ui/src/lib/components/agents/avatar/AvatarViewer.svelte` — Lines 83–116 register Room listeners before connect; 132–185 detach/stop lifecycle reference. This component creates its own REST avatar session; do not reuse that ownership in the Voice page.
- `packages/ai-parrot-server/ui/package.json` — Existing livekit-client ^2.19.2 at line 45; test script runs vitest run. Use the existing installation, no new package.
- `packages/ai-parrot-server/ui/pnpm-lock.yaml` — Lines 92–94 resolve livekit-client 2.22.1. The installed UMD artifact may be absent; verify prerequisite during implementation.
- `packages/ai-parrot-server/ui/vitest.config.ts` — Existing test environment is jsdom with vitest-setup.ts; no new test runner is needed.
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` — viewer_credentials returns only livekit_url/client_token/room. speak forwards 24 kHz PCM unchanged. Session teardown method is aclose(), not close().
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — display_data.data and tool_call frames at 437–458 and 1749–1778. Avatar request/response at 1150–1214 uses top-level avatar/tenant_id/avatar_id and viewer credentials. start_recording currently invokes start_turn without avatar interruption.

### Does NOT Exist

- No root parrot/ source tree; use workspace package paths. No model-native JSON-schema voice output is added.
- No shared last-result storage or LiveVoiceResponse.display_data attribute; structured output uses response.metadata["display_data"].
- The demo avatar controller and /voice-assets/livekit-client.umd.js route are NEW; no existing exports or route should be assumed.
- The admin Svelte viewer is not importable into standalone HTML. No second REST avatar session or microphone publication is allowed.

## Implementation Notes

### Pattern to Follow

Use the task-specific source anchors and spec §2 behavior. Preserve existing execution/transport ownership. Keep helpers typed and private where possible; match Python black and frontend prettier conventions.

### Key Constraints

- No new dependencies or unrelated refactors. No production change to AbstractClient or GeminiLiveClient.
- Keep secrets/permission objects out of provider arguments, browser panels and logs.
- Follow the task DAG and file ownership above; report cross-scope failures to the owning task.
- Save exact verification commands and results under artifacts/logs/ and reference them in completion notes.

## Acceptance Criteria

- [ ] Mock SDK proves listeners-before-connect, video/audio attach/detach and zero publication calls.
- [ ] Autoplay denied/enable click, playability, explicit mute and fallback transitions never enable two audible sources.
- [ ] Late join/old track events after disable/provider change/teardown cannot revive a room or media.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- test_join_subscribe_only
- test_audio_source_transitions
- test_autoplay_and_explicit_mute
- test_stale_generation_and_idempotent_teardown

Use behavioral fixtures with real tools/manager where that path is under test. Mock only provider/transport boundaries for conformance. Event gates and patched deadlines should replace timing-sensitive sleeps. Browser tests load the actual demo page. No live test runs are required for automated CI.

Commands to run from the feature worktree using its configured environment (capture output in artifacts/logs/):

```bash
pnpm --dir packages/ai-parrot-server/ui test src/lib/utils/voice-demo-avatar.test.ts
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
