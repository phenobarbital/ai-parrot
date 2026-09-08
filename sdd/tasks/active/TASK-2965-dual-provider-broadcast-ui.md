# TASK-2965: Broadcast mode in `dual_provider.html` — roles, raised hands, floor-gated mic, real resampling

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2963, TASK-2964
**Parallel**: false
**Parallelism notes**: Only task editing `dual_provider.html`. Requires the backend config contract (TASK-2963) and the viewer API (TASK-2964).

---

## Context

Spec §2 "Reused HTML example": add a Broadcast mode to the **same** page: authenticated Create/Join, server-assigned roles, share link without secrets, participant list, raised-hand queue, current-speaker indicator; viewers Raise Hand/Cancel/Leave; moderator Grant/Revoke/Reclaim/Stop; speaker push-to-talk + Finish Speaking; mic capture only after grant **and** user gesture; role changes without reload; "Generic `ready_to_speak`, completion or error frames must never override server floor permission"; fix capture resampling (stateful, real browser rate → 16 kHz, never relabel 48 kHz). AC8, AC12–AC14 browser side.

## Scope

- `dual_provider.html`:
  - Mode switch "Single-user | Broadcast" (Broadcast disabled with `__CONFIG__.broadcast.unavailableReason` when unavailable). Broadcast panel: demo participant selector (names only; the bearer token is entered by the user or picked from a **non-persisted** in-memory map seeded from a `?demo_token=` **fragment** — never localStorage, never the share link), **Create** → `POST {apiPrefix}` → share link `location.origin + "/?broadcast=" + broadcast_id`; **Join** (also auto when `?broadcast=` present) → `POST /viewers` → poll `GET /viewers/{lease}/connection` until 200 → `controller.joinBroadcast(creds, public_state)`; open the control WS `wsPath` (protocol `["jwt", token]`), send `{"type":"attach","lease_id"}`, then `start_session` (attaches, no new bot), heartbeat `ping` every 5 s.
  - State rendering from `broadcast_state`/`floor_state` frames and 1 s `GET /{bid}` polling fallback (call `controller.applyBroadcastState`, `markStateFresh`): participant list (lease display IDs), moderator/speaker badges, hand queue in server order, state badge (`avatar`/`audio_only`/…), reason text.
  - Controls by role (server decides): Raise Hand / Cancel (`POST|DELETE hands`), Leave (`DELETE viewers/{lease}` + WS close), moderator: Grant per queue row (`POST floor {lease_id, expected_version}`), Revoke (`lease_id: null`), Reclaim (own lease), Dismiss hand, Stop (`POST stop`); speaker: Talk (push-to-talk) + Finish Speaking (`POST floor/release` or WS `finish_speaking`).
  - Mic gating: `recordBtn` enabled **only if** `floorGranted && canSpeak && floorEpochFresh` (a helper `updateTalkAvailability()` called from every place that currently toggles `recordBtn` — `ready_to_speak` `:1402`, `error` `:1410`, `handleInterrupt` `:1626`, `stopRecordingUI/stopRecording`). `getUserMedia` requested only inside `startRecording()` after a grant. All broadcast `start_recording`/`audio_chunk`/`stop_recording` messages include `floor_epoch`. On `floor_revoked`/`floor_state{granted:false}` ⇒ immediately `stopRecording()` without sending audio; stale state > 3 s ⇒ disable Talk.
  - Resampling fix in `setupAudioProcessing()` (`:1512-1555`): replace per-buffer linear interpolation with a **stateful** resampler (carry fractional phase + last sample across `onaudioprocess` callbacks; or an `AudioWorklet` when available with the ScriptProcessor fallback) producing exactly 16 kHz mono PCM16; log actual `audioContext.sampleRate`. Applies to single-user mode too (bug fix), covered by a unit-testable pure function `resampleTo16k(state, float32, inRate)` exported on `window.__voiceDemo` for tests.
  - Playback: in broadcast mode never enqueue local PCM (`controller.shouldPlayLocalAudio()` already false); everyone hears the room; show autoplay "Enable audio" button via existing `showAvatarEnableAudioButton`.
  - Provider toggle while in a broadcast ⇒ prompt, then Leave first; the broadcast keeps running for others.
  - Actionable UI for 401/403/404/409/410/429 responses.
- Tests: extend `packages/ai-parrot-integrations/tests/voice/test_voice_demo_avatar_browser.py` fakes (add `fetch` fake for the REST prefix and `participant.identity` on fake tracks) **or** create `test_voice_demo_broadcast_browser.py` reusing its `demo_server`/`demo_page` fixtures: ungranted participant never calls `getUserMedia` (spy), `ready_to_speak` does not enable Talk without grant, grant + click ⇒ `start_recording` with `floor_epoch`, revoke ⇒ recording stops and no `audio_chunk` after, share link has no token, resampler produces 16 kHz-length output for 48 kHz input, single-user flows untouched (existing tests green).

**NOT in scope**: server code, README/guide (TASK-2966), multi-browser orchestration (TASK-2968).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/static/dual_provider.html` | MODIFY | Broadcast panel, role controls, floor-gated mic, stateful resampler |
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_broadcast_browser.py` | CREATE | Playwright tests (fake WS/fetch/SDK boundaries) |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (`examples/clients/voice/static/dual_provider.html`)
```js
class VoiceChatClient {                                   // :1059
  constructor(): DOM refs incl. recordBtn :1063, interruptBtn :1076, avatar* :1079-1090, toolEventsPanel :1091; state canSpeak :1101; avatarConfig/avatarController :1109-1113; providers/capabilities from window.__CONFIG__ :1117-1118; config.wsUrl :1123-1127
  handleMessage(message) switch: 'connected' :1378 → startSession(); 'session_started' :1385 → handleAvatarSessionStarted(message.avatar); 'response_chunk' :1391; 'response_complete' :1398; 'ready_to_speak' :1402 (recordBtn.disabled=false!); 'error' :1410 (recordBtn.disabled=false!); 'transcription' :1419; 'display_data' :1427; 'tool_call' :1434
  startSession() :1444 ; async startRecording() :1471 (getUserMedia 16k :1486; setupAudioProcessing :1497)
  async setupAudioProcessing() :1512 (nativeSampleRate/targetSampleRate=16000; ScriptProcessor 4096; per-buffer linear interp :1531-1541 — NOT stateful)
  sendAudioChunk(buffer) :1557 → ws.send({type:'audio_chunk', data:b64})   // handler alias audio_chunk→audio_data (handler.py:987)
  stopRecordingUI() :1568 ; stopRecording() :1590 (sends stop_recording) ; setInterruptEnabled :1621 ; handleInterrupt() :1626 (sends start_recording, re-enables recordBtn) ; stopLocalPlayback() :1647
  ensureAvatarController() :2014 (dynamic import('/static/avatar-viewer.js'), new AvatarViewerController({...callbacks})) ; loadAvatarSdk() :2033 (window.__CONFIG__.avatar.sdkUrl) ; handleAvatarSessionStarted :2051 ; teardownAvatarViewer :2083 ; setAvatarStatus :2107 ; showAvatarEnableAudioButton :2133
  loadSettings()/saveSettings() :2150/:2200 (localStorage key 'voiceChatProviderSwitchSettings' — never store tokens)
}
```
- Backend config (TASK-2963): `window.__CONFIG__.broadcast = {available, apiPrefix, wsPath, agentId, demoParticipants, unavailableReason}`.
- Viewer API (TASK-2964): `new AvatarViewerController({mode:"broadcast", onStale, onDisconnected, ...})`, `joinBroadcast(creds, publicState)`, `applyBroadcastState(state)`, `markStateFresh()`.
- Server WS frames (TASK-2960): `broadcast_state {state}`, `floor_state {granted, floor_epoch}`, `floor_revoked {floor_epoch}`, `error {code}`; client messages carry `floor_epoch`.
- Browser test fixtures: `tests/voice/test_voice_demo_avatar_browser.py` `_FAKE_BOUNDARIES_INIT_SCRIPT :81` (FakeWebSocket with `push()`, FakeRoom/FakeTrack, `window.LivekitClient`), `demo_server :164`, `demo_page :176`, `_push_ws_message :199`, `_sent_ws_messages :203`.

### Does NOT Exist
- ~~Any broadcast UI, `updateTalkAvailability`, stateful resampler, `fetch` usage for broadcast~~ — new.
- ~~A second HTML page~~ — forbidden (AC15).
- ~~Role from URL/selector~~ — roles come only from server state.

## Implementation Notes

- Keep all new JS inside the existing `<script>`/class (or a new `static/broadcast-ui.js` ES module imported by the page — allowed: "shared example page with reusable JS assets").
- `fetch` calls: `credentials: "same-origin"`, `Authorization: Bearer <demo token>`; surface `error` + `state` from 409 bodies.
- Never write tokens to `localStorage`, URL query, or console.

## Acceptance Criteria

- [ ] Ungranted participant: `getUserMedia` spy never called; `ready_to_speak` leaves Talk disabled.
- [ ] Granted participant: Talk click ⇒ `getUserMedia` then `start_recording` with `floor_epoch`; `floor_revoked` ⇒ recording stops, no further `audio_chunk`.
- [ ] Moderator sees Grant/Revoke/Reclaim/Stop; viewer sees Raise Hand/Cancel/Leave; badges update from `broadcast_state` without reload.
- [ ] Share link contains only `?broadcast=<id>`.
- [ ] `resampleTo16k` on 48 kHz input yields length/3 samples with continuity across calls (no click at boundaries: max sample jump bounded in test).
- [ ] Existing `test_voice_demo_avatar_browser.py` green; new suite green; page loads with zero `pageerror`s.

## Test Specification

```python
async def test_ungranted_participant_never_requests_microphone(demo_page): ...
async def test_ready_to_speak_does_not_enable_talk_without_floor(demo_page): ...
async def test_grant_then_talk_sends_floor_epoch(demo_page): ...
async def test_revoke_stops_capture(demo_page): ...
async def test_share_link_has_no_secrets(demo_page): ...
async def test_stateful_resampler_48k_to_16k(demo_page): ...
```

## Agent Instructions
1. Read spec §2 "Reused HTML example and runnable backend" + "Moderation" + "Audio routing". 2. Verify anchors (line numbers drift). 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
