# TASK-2964: `avatar-viewer.js` broadcast policy — descriptor-driven source selection, epoch fencing, no single-user fallback

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2951
**Parallel**: true
**Parallelism notes**: Touches only `examples/clients/voice/static/avatar-viewer.js` and the vitest file that imports it. Depends on TASK-2951 only for the `BroadcastPublicState` wire shape (field names). TASK-2965 consumes this API.

---

## Context

Spec §2: "`examples/clients/voice/static/avatar-viewer.js` (introduced by FEAT-536): reuse its SDK injection, attachment, autoplay and generation-safe cleanup. Add an explicit broadcast policy/context so room credentials come from the scoped admission API and selected publisher/epoch comes from broadcast state. In broadcast mode, disable its single-user WebSocket-audio fallback and session-restart reconnect behavior … Ordinary single-user behavior remains unchanged." And "Audio routing": each browser keeps exactly one audible source selected by the latest descriptor; mutes/detaches avatar audio+video before selecting direct audio; rejects old epoch events and late avatar tracks; status older than 3 s mutes output; `audio_only` sticky; late joins attach already-published tracks.

## Scope

- Add to `AvatarViewerController` (ES module, framework-free, SDK-injected as today):
  - constructor option `mode: "single" | "broadcast"` (default `"single"` — every existing behaviour and test unchanged).
  - `joinBroadcast({livekit_url, client_token, room}, publicState)` — same connect path as `join()` but stores `this._broadcast = { outputEpoch, state, avatarIdentity, directIdentity, version, lastStateAt }` from `publicState` (field names from `BroadcastPublicState`: `output_epoch`, `state`, `avatar_identity`, `direct_identity`, `version`).
  - `applyBroadcastState(publicState)` — ignore if `version`/`output_epoch` is not monotonically ≥ current; on `state === "audio_only"` (sticky): detach/mute avatar video+audio, select tracks whose participant identity === `direct_identity`; on `"avatar"`: select tracks from `avatar_identity`. Tracks from any other identity (or an avatar identity after cutover) are ignored/detached (`_handleTrackSubscribed` must consult identity via `participant.identity` — check the fake in tests exposes it).
  - Freshness: `markStateFresh()` on each poll/notification; if `Date.now() - lastStateAt > 3000` ⇒ mute output and fire `onStale(true)`; unmute on refresh.
  - In broadcast mode: `shouldPlayLocalAudio()` **always returns false** (no WS-PCM fallback), `_handleDisconnected` does **not** trigger any session restart callback — it only fires `onDisconnected()` so the page can re-admit via the API.
  - Late join: after `connect`, iterate `room.remoteParticipants` (verify the exact property on livekit-client 2.22.1 UMD: `room.remoteParticipants` Map) and attach already-published/subscribed tracks matching the selected identity.
  - Keep `enableAudio()`, `setMuted()`, `teardown()` generation guard behaviour.
- Tests: extend `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts` (vitest, imports the JS by relative path, line 18) with a fake SDK exposing `participant.identity` and `remoteParticipants`: descriptor cutover switches source once, stale/older epoch ignored, late avatar track after cutover rejected, freshness mute, `shouldPlayLocalAudio()===false` in broadcast, single mode unchanged.

**NOT in scope**: HTML page changes (TASK-2965), server, Python tests.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/voice/static/avatar-viewer.js` | MODIFY | Broadcast mode API + policy |
| `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts` | MODIFY | Add broadcast-mode tests |

## Codebase Contract (Anti-Hallucination)

### Verified anchors
```js
// examples/clients/voice/static/avatar-viewer.js
export const AvatarStatus = {IDLE, CONNECTING, LIVE, ERROR}            // :27
export const AudioSource  = {BROWSER: "browser", AVATAR: "avatar"}     // :34
export class AvatarViewerController {                                  // :62
  constructor({ sdk, videoEl, audioEl, onStatusChange, onAudioSourceChange, onStopLocalPlayback, onAudioPlaybackBlocked, onError, logger })  // :97-108 ; requires sdk.Room/RoomEvent/Track
  this._generation; this._room; this._audioTrack; this._videoTrack; this._status; this._audioSource; this._preferredSource; this._userMuted; this._canPlayAvatarAudio  // :129-149
  shouldPlayLocalAudio() { return !this._userMuted && this._audioSource === AudioSource.BROWSER; }  // :167
  async join(credentials /* {livekit_url, client_token, room} */)      // :188 (teardown → generation++ → new Room → listeners → connect)
  async enableAudio(); setPreferredAudioSource(source); setMuted(muted); async teardown()  // :250 / :275 / :298 / :316
  _handleTrackSubscribed(track, Track, generation); _handleTrackUnsubscribed; _handleDisconnected(generation); _handleAudioPlaybackStatusChanged  // :372 / :393 / :414 / :423
}
```
- Vitest file: `packages/ai-parrot-server/ui/src/lib/utils/voice-demo-avatar.test.ts` imports `{ AvatarViewerController, AvatarStatus, AudioSource }` from `../../../../../../examples/clients/voice/static/avatar-viewer.js` (:13-18). Run with `pnpm --dir packages/ai-parrot-server/ui test -- voice-demo-avatar` (verify the script name in `ui/package.json`).
- Wire shape (TASK-2951 `BroadcastPublicState`): `state`, `version`, `output_epoch`, `avatar_identity`, `direct_identity`, `selected_audio_track_id`, `selected_video_track_id`, `media_ready`, `floor_state`, `floor_epoch`, `moderator_lease_id`, `speaker_lease_id`, `hand_requests`, `viewer_count`, `max_viewers`, `reason`.

### Does NOT Exist
- ~~`AvatarViewerController.mode` / `joinBroadcast` / `applyBroadcastState` / `onStale` / `onDisconnected`~~ — you add them.
- ~~Identity filtering in `_handleTrackSubscribed`~~ — today it attaches any subscribed track of the kind.
- ~~`AvatarViewer.svelte` reuse~~ — spec: do not reuse it as a spectator.

## Implementation Notes

- livekit-client 2.22.1: `RoomEvent.TrackSubscribed` handler signature is `(track, publication, participant)`; use `participant.identity`. Verify in `packages/ai-parrot-server/ui/node_modules/livekit-client/dist/livekit-client.umd.js` or its `.d.ts` if installed.
- Keep the module dependency-free and importable under vitest (no DOM globals at import time).
- Document the two modes in the file header comment.

## Acceptance Criteria

- [ ] Existing vitest cases pass unchanged.
- [ ] Broadcast mode: cutover state ⇒ avatar tracks detached/muted, direct track attached once; older `output_epoch` state ignored; late avatar track after cutover not attached; `shouldPlayLocalAudio()` is `false`.
- [ ] No state refresh for > 3 s ⇒ muted + `onStale(true)`; refresh ⇒ unmuted.
- [ ] Late join attaches existing remote tracks of the selected identity.
- [ ] `pnpm --dir packages/ai-parrot-server/ui test` (vitest) green for this file; no ESLint errors introduced.

## Test Specification

```ts
describe("AvatarViewerController broadcast mode", () => {
  it("switches to direct audio once on audio_only and rejects late avatar tracks", async () => { ... });
  it("ignores states with older output_epoch", async () => { ... });
  it("mutes when state is stale for more than 3 seconds", async () => { vi.useFakeTimers(); ... });
  it("never plays local WebSocket audio in broadcast mode", () => { ... });
  it("attaches already-published tracks on late join", async () => { ... });
});
```

## Agent Instructions
1. Read spec §2 "Audio routing" + viewer bullet in "Reused HTML example". 2. Verify anchors + livekit-client event signatures. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
