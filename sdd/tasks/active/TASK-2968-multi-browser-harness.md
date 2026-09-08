# TASK-2968: Multi-browser Playwright harness — moderated handoff, ten viewers, degradation and permissions

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2965, TASK-2967
**Parallel**: false
**Parallelism notes**: Test-only; creates one browser suite module plus an opt-in real-vendor variant. Runs after the UI and the two-worker fixtures exist (it reuses both).

---

## Context

Spec §4 Integration Tests rows that need real browsers: "Three-browser combined path", "Moderated handoff", "Moderation races/departure", "Ten-viewer limit", "Startup degradation", "Runtime degradation", "Barge-in and lifecycle", "Browser permissions". Spec §4 fixtures: "Browser test orchestration must create independent browser contexts with unique leases and explicit autoplay gestures. Test output must include decoded video-frame progress and non-zero received audio measurements in each browser; a connected badge or published track alone is insufficient." Module 7 browser half; AC1, AC4, AC5, AC6, AC8, AC12–AC14 browser evidence.

## Scope

- `packages/ai-parrot-integrations/tests/voice/test_voice_demo_multibrowser.py`:
  - Fixture `broadcast_demo_server`: the **actual** `examples/clients/voice/server.py` `build_app()` with env pointing the registry at the in-memory registry (monkeypatch the registry factory) or real Redis when available, fake avatar/publisher factories injected through the service, demo participants `mod,alice,bob,…` (10 names), failure hook enabled.
  - Fixture `contexts(n)`: `n` independent `browser.new_context()` pages (Chromium headless, `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --autoplay-policy=no-user-gesture-required` only where the test is not about autoplay), each with the init script from `test_voice_demo_avatar_browser.py:81` extended so `FakeRoom` supports **multiple participants with identities** and per-page counters of decoded video frames / received audio samples (fake `track.attach` starts a timer incrementing `window.__videoFrames`/`window.__audioSamples` while the source is "speaking"), plus a `fetch` passthrough (REST is real).
  - Scenarios (each writes a per-browser measurement table to `artifacts/logs/feat-537-browser-<scenario>-<date>.json`):
    1. **Three-browser combined path**: mod creates, alice+bob join via share link; two spoken turns (fake mic WAV → real `audio_chunk` frames to the real WS route → fake Nova bot factory returns transcript+tool_call+PCM) + one tool-enabled turn; all three pages show the same transcript/tool event and non-zero audio/video counters; bob leaves ⇒ mod/alice unaffected; late joiner carol attaches existing media.
    2. **Moderated handoff**: alice+bob raise hands; mod grants alice → alice talks → responses reach all; mod grants bob (alice revoked mid-turn ⇒ her `audio_chunk` after revoke rejected — assert server counter via a debug endpoint or logs); mod reclaims; only one lease's frames ever reach the fake bot; one conversation/session id throughout.
    3. **Races/departure**: two tabs join simultaneously ⇒ one moderator; conflicting grants ⇒ one wins; duplicate speaker socket ⇒ 409 error shown; moderator closes tab ⇒ successor badge everywhere; speaker disconnect ⇒ floor returns.
    4. **Ten-viewer limit**: mod + 9 participants live (10 pages); 11th shows `viewer_limit_reached`; assert one producer start and one avatar session.
    5. **Startup degradation**: avatar factory raises ⇒ all pages show `audio_only`, direct track attached, audio counters non-zero.
    6. **Runtime degradation**: inject `avatar_control_close` during speech, then in a second run `avatar_track_lost`; each healthy page switches within 3 s of the server transition (compare page `performance.now()` deltas vs server timestamp from `GET`), single source, subsequent speech heard, late avatar reappearance rejected; late join after fallback correct.
    7. **Barge-in and lifecycle**: interrupt in both modes ⇒ page-side "old audio stopped" ≤ 1 s; mod Stop ⇒ all pages ended; owner death via hook ⇒ fenced (watch `GET` state).
    8. **Browser permissions**: ungranted page never calls `getUserMedia` (spy); granted requests only on Talk; blocked autoplay shows the Enable-audio button and recovers; 401/403/404/409/410 UI states render; tokens absent from `location.href`, `localStorage`, console logs.
- Opt-in real-vendor variant: `test_voice_demo_multibrowser_live.py` gated by `PARROT_LIVE_BROADCAST_GATE=1` + credentials (marker `live_vendor` from TASK-2950) running scenarios 1, 2, 4 against real Nova/LITE/LiveKit with the real `livekit-client` UMD (no fake SDK), capturing a 10 s synchronized A/V sample per page to `artifacts/logs/` for the human lip-sync assessment (TASK-2969). Skips report "NOT VERIFIED".

**NOT in scope**: fixing product bugs found (open follow-up notes), final acceptance sign-off (TASK-2969).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_multibrowser.py` | CREATE | Deterministic multi-context Playwright suite |
| `packages/ai-parrot-integrations/tests/voice/test_voice_demo_multibrowser_live.py` | CREATE | Opt-in real-vendor variant |
| `packages/ai-parrot-integrations/tests/voice/_broadcast_browser_fakes.py` | CREATE | Shared init scripts/fixtures (multi-participant FakeRoom, counters) |

## Codebase Contract (Anti-Hallucination)

### Verified Imports / patterns
```python
from playwright.async_api import async_playwright          # test_voice_demo_avatar_browser.py:41 (playwright 1.52.0)
from aiohttp.test_utils import TestServer                  # :40
import uvloop; asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())  # :39, :55 (existing suite does this — keep consistent)
_load_server_module()                                      # :61 (imports examples/clients/voice/server.py by path)
_FAKE_BOUNDARIES_INIT_SCRIPT                               # :81 (FakeWebSocket.push, FakeTrack.attach counters, FakeRoom.emit, window.LivekitClient {Room, RoomEvent{TrackSubscribed,...}, Track.Kind})
demo_server / demo_page fixtures                           # :164 / :176 ; helpers _push_ws_message :199, _sent_ws_messages :203, _emit_track :246
```
- Backend contract: TASK-2963 (`__CONFIG__.broadcast`, demo bearer tokens, failure hook `POST /__demo__/broadcasts/{bid}/inject`).
- UI contract: TASK-2965 (element ids/roles — read the landed HTML for exact ids before writing selectors).
- Viewer contract: TASK-2964 (`participant.identity` filtering ⇒ fakes must pass `(track, publication, participant)` to `TrackSubscribed`).

### Does NOT Exist
- ~~Multi-participant FakeRoom / frame counters~~ — you add them in `_broadcast_browser_fakes.py`.
- ~~A "connected badge" as proof of media~~ — insufficient by spec; measure counters.
- ~~Real audio decoding in the deterministic suite~~ — counters come from the fake SDK; the live variant captures real media.

## Implementation Notes

- Use one Playwright browser, many contexts; give each page a `pageerror` collector and assert empty at the end.
- Keep each scenario < 60 s wall clock; use `page.wait_for_function` on counters, never fixed sleeps > 1 s.
- Write the measurement JSON even on failure (fixture finaliser) so evidence survives.

## Acceptance Criteria

- [ ] All 8 deterministic scenarios pass headless; each writes a measurement file with per-page audio/video counters and timings.
- [ ] Scenario 4 proves one producer/avatar start for 10 pages and `viewer_limit_reached` for the 11th.
- [ ] Scenario 6 reports per-page switch latency and asserts ≤ 3 s after the server transition; scenario 7 asserts ≤ 1 s stop-of-stale-audio.
- [ ] Scenario 8 proves no `getUserMedia` before grant and no token in URL/localStorage/console.
- [ ] Live variant skips with "NOT VERIFIED" by default; with credentials it records A/V samples.
- [ ] `ruff check` clean; existing browser suite still green.

## Test Specification

```python
@pytest.mark.asyncio
async def test_three_browsers_share_one_broadcast(broadcast_demo_server, contexts): ...
async def test_moderated_handoff_single_mic_source(...): ...
async def test_races_and_moderator_departure(...): ...
async def test_ten_viewers_eleventh_rejected(...): ...
async def test_startup_degradation_everyone_hears_direct_audio(...): ...
@pytest.mark.parametrize("kind", ["avatar_control_close", "avatar_track_lost"])
async def test_runtime_degradation_switches_within_three_seconds(kind, ...): ...
async def test_bargein_stop_and_owner_death(...): ...
async def test_browser_permissions_and_no_secret_leaks(...): ...
```

## Agent Instructions
1. Read spec §4 Integration Tests + "Test Data / Fixtures". 2. Read the landed HTML/JS/backends for selectors and hooks. 3. Index → `in-progress`. 4. Implement; run headless. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
