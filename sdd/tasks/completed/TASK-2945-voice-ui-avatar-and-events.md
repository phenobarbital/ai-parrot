# TASK-2945: Integrate avatar, tool panels and interruption in the Voice UI

**Feature**: FEAT-536 - VoiceBot — Nova dual output and LiveAvatar in the Voice UI
**Spec**: `sdd/specs/voicebot-liveavatar-implementation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; target 4h)
**Depends-on**: TASK-2943, TASK-2944
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial dependency boundary. Shared production/test files must not be edited concurrently; complete listed prerequisites first.

---

## Context

Implements §3 Module 5 and contributes to AC1, AC12, AC14, AC15, AC16. The approved spec remains authoritative for cross-task behavior. This task is one bounded deliverable in the single FEAT-536 worktree.

## Scope

- Extend the actual dual_provider.html with Avatar default-off toggle, tenant/optional avatar IDs, video state card, remote audio element, output selection/mute and enable-audio action.
- Lazy-load the same-origin configured SDK only for avatar use and wire the new controller. Missing SDK/credentials/inactive avatar leaves ordinary voice functional.
- Send avatar/tenant_id/avatar_id at the top level of existing start_session. Consume current session_started.avatar only; keep the chosen Gemini/Nova route and PCM microphone WebSocket path.
- Handle display_data and tool_call in shared panels with textContent/JSON fallback, never raw tool HTML. Keep text/events flowing regardless of audio source.
- Wire the one-source controller callbacks to stop/clear active and queued local PCM, suppress incoming local playback as appropriate and preserve explicit mute.
- Provider/session changes, avatar disable and page teardown invalidate callbacks and clean media; avatar setting changes also close/restart the server voice session so no billable orphan remains.
- Add Interrupt / speak-again action using existing start_recording; stop local playback and start fresh recording even while awaiting a response. Do not introduce a new protocol message.

**NOT in scope**: No replacement page, raw-client app changes, SDK dependency change or demo tool implementation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/static/dual_provider.html` | MODIFY | Scoped deliverable owned by TASK-2945 |

Only the files above belong to this task, plus its task state and per-spec index. You are not alone in this codebase: preserve others' edits and adapt to completed dependencies. Read-only references below do not grant edit ownership.

## Codebase Contract (Anti-Hallucination)

Re-read and verified on 2026-09-07 against dev `77bd1a50c1282694444e05b4f41ad4138c880ff2`. These are baseline definitions, not invented future APIs. Dependencies may change their lines/signatures: refresh them before implementation.

### Verified Imports

```python
from aiohttp import web
from parrot.voice.handler import VoiceChatHandler, WebSocketConnection
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
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

# examples/clients/voice/server.py:116
def get_weather(location: str) -> str

# examples/clients/voice/server.py:155
def make_gemini_bot() -> VoiceBot

# examples/clients/voice/server.py:165
def make_nova_bot() -> VoiceBot

# examples/clients/voice/server.py:239
async def index_handler(request: web.Request) -> web.Response

# examples/clients/voice/server.py:276
def build_app() -> web.Application

# packages/ai-parrot-integrations/src/parrot/voice/handler.py:1274
async def _handle_start_recording(self, connection: WebSocketConnection, message: Dict[str, Any]) -> None

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py:208
def viewer_credentials(self) -> dict[str, str]
```

### Task-specific References

- `examples/clients/voice/static/dual_provider.html` — handleMessage 1112–1158 lacks display_data/tool_call/avatar handling. startSession 1161–1173 sends config only. queueAudioChunk/playStreamingAudio at 1368 onward drive local PCM. Existing startRecording rejects !canSpeak.
- `examples/clients/voice/static/avatar-viewer.js` — NEW deliverable of this feature; verify dependent task exports before importing.
- `examples/clients/voice/server.py` — index_handler injects window.__CONFIG__ once; build_app mounts /ws/gemini, /ws/nova and /static/. Existing get_weather returns a plain string; factories copy a shared tool list.
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — display_data.data and tool_call frames at 437–458 and 1749–1778. Avatar request/response at 1150–1214 uses top-level avatar/tenant_id/avatar_id and viewer credentials. start_recording currently invokes start_turn without avatar interruption.
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` — viewer_credentials returns only livekit_url/client_token/room. speak forwards 24 kHz PCM unchanged. Session teardown method is aclose(), not close().

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

- [ ] Both provider choices use the same avatar/event code with correct top-level request fields.
- [ ] The page renders avatar video and tools/structured JSON together and avoids stale session updates.
- [ ] Interrupt is reachable while a response is active; provider/Avatar toggles close the old session and cleanup before reuse.
- [ ] Focused controller tests pass; served-page automated scenarios are delivered by TASK-2947.
- [ ] Scoped tests and relevant regressions pass; evidence is recorded, not inferred from source inspection.

## Test Specification

- Manual local fake-transport smoke of the served HTML and controller integration; record observations without claiming a real-live pass.

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

Extended `examples/clients/voice/static/dual_provider.html` only (no
replacement page, no raw-client `app.js`/`index.html` changes, no SDK
dependency change, no demo-tool implementation — all out of scope per the
task).

Added markup: a floating, off-by-default avatar card (`#avatarCard`) with
a muted `<video>` for the subscribe-only track and a dedicated `<audio>`
element for the one-source policy, a status dot/text, an "Enable avatar
audio" button, an audio-source `<select>` and a mute toggle; a settings-
panel group (`#avatarEnabledCheckbox`, `#avatarTenantId`, `#avatarAvatarId`)
next to the existing language/system-prompt settings; a shared
`#toolEventsPanel`/`#toolEventsList` for `display_data`/`tool_call`
frames; and `#interruptBtn` next to the existing clear-chat control.

Wired the JS `VoiceChatClient` class: `initAvatarUI()` binds all avatar
controls; `ensureAvatarController()`/`loadAvatarSdk()` lazy-load
`avatar-viewer.js` (via `import('/static/avatar-viewer.js')`, served
through the existing `/static/` mount) and the locked SDK's UMD build
(via a dynamically-created `<script src>` pointed at
`window.__CONFIG__.avatar.sdkUrl` from TASK-2943, resolving
`window.LivekitClient`) only once avatar is enabled;
`handleAvatarSessionStarted()` consumes `session_started.avatar` from the
CURRENT session only and calls `controller.join({livekit_url,
client_token, room})` — the exact wire shape, no translation layer;
`startSession()` now sends `avatar`/`tenant_id`/`avatar_id` at the
top level (never nested under `config`); `onAvatarSettingChanged()`
tears down the prior viewer and calls the existing `reconnect()` (fresh
session, old socket closed — no billable orphan) whenever an avatar
setting changes while connected. `queueAudioChunk()`/
`playStreamingAudio()` gate on `avatarController.shouldPlayLocalAudio()`
both at enqueue time and defensively mid-drain (a switch can land after
several chunks are already queued); `stopLocalPlayback()` (the
controller's `onStopLocalPlayback` callback) clears the queue and stops
any in-flight `AudioBufferSourceNode`. `ws.onclose` and `beforeunload`
both call `teardownAvatarViewer()` so a superseded generation's room is
always disconnected (spec "Lifecycle/races") without a second live room
or a new protocol message. `handleMessage()` gained `display_data`/
`tool_call` cases rendering into the shared panel via `textContent` +
`JSON.stringify` fallback (`renderToolEvent()`/`formatToolEventData()`)
— never raw tool HTML; `clearChat()` now also clears/hides that panel on
provider/session switch. The Interrupt control
(`handleInterrupt()`) stops local playback, sends the EXISTING
`start_recording` wire message (this page never previously sent it —
it is also what triggers TASK-2942's server-side avatar interrupt in
`_handle_start_recording`), then bypasses the `canSpeak` gate and calls
the existing `startRecording()` — no new WebSocket message was added.
`avatarConfig` (enabled/tenantId/avatarId — no credentials) persists via
the existing `loadSettings()`/`saveSettings()` localStorage round-trip
alongside language/system-prompt/activeProvider.

Verification:
- `pnpm --dir packages/ai-parrot-server/ui test
  src/lib/utils/voice-demo-avatar.test.ts` — 11 passed, re-run after this
  HTML-only change to confirm no regression
  (`artifacts/logs/TASK-2944-vitest.log`).
- A manual local fake-transport smoke
  (`artifacts/logs/TASK-2945-smoke.log`) built an `aiohttp` `TestClient`
  against `server.py`'s real `build_app()`/`index_handler()` and
  confirmed: the rendered page contains every new element id
  (avatarCard, interruptBtn, toolEventsPanel, avatarEnabledCheckbox,
  avatarVideo, avatarAudio) and the string `AvatarViewerController`;
  `/static/avatar-viewer.js` serves 200 and exports
  `AvatarViewerController`; `/voice-assets/livekit-client.umd.js`
  resolved 200 (this sandbox actually has the locked 2.22.1 UMD artifact
  installed from TASK-2944's `pnpm install --frozen-lockfile
  --prefer-offline`, run against the real `pnpm-lock.yaml`); and
  `/ws/gemini`/`/ws/nova` remain mounted.
- `node --check` on the page's extracted inline `<script>` block confirms
  valid JS syntax; a rough HTML tag-balance check (div/script/button/
  video/audio/select/aside open vs. close counts) confirms no unclosed
  markup was introduced.

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-07
**Notes**: No real-live browser pass (a user actually seeing avatar
video/hearing avatar audio, exercising autoplay-block/enable-audio in a
real browser, or a real LiveAvatar backend) is claimed — that is
TASK-2947's Playwright scope and TASK-2949's operational acceptance
scope, exactly as this task's own Test Specification states ("served-page
automated scenarios are delivered by TASK-2947"). Also worth recording:
running `node` against the real installed `livekit-client.umd.js` outside
a browser/jsdom context fails at UMD-init time (it expects browser
globals like `navigator.mediaDevices`/`AudioContext` well beyond what a
bare Node global shim provides) — expected and not a defect in this
task's code; it is exactly why TASK-2947 uses Playwright's real browser
context rather than a Node-only smoke for that layer.
**Deviations from spec**: none recorded
