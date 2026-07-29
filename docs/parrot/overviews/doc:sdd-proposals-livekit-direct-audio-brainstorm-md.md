---
type: Wiki Overview
title: 'Brainstorm: LiveKit Direct Audio (avatar-optional livekit voice)'
id: doc:sdd-proposals-livekit-direct-audio-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `livekit` voice transport (LITE, FEAT-173) depends **entirely** on LiveAvatar
relates_to:
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: LiveKit Direct Audio (avatar-optional livekit voice)

**Date**: 2026-06-23
**Author**: Juanfran
**Status**: exploration
**Recommended Option**: C — two-mode hybrid (uses Option A's headless publisher for the avatar-OFF path)

---

## Problem Statement

The `livekit` voice transport (LITE, FEAT-173) depends **entirely** on LiveAvatar
for audio. The bot's speech is synthesized by ai-parrot (Supertonic) but the PCM
is routed to LiveAvatar's `agent.speak` WebSocket, where LiveAvatar lip-syncs it
and publishes **audio + video** into the LiveKit room. So when the LiveAvatar
account has **no credits** (`403 code 4033`), `start_session` fails, the room
never gets an audio publisher, and livekit voice is unusable — today it just
surfaces a clean `402` banner (the no-credits handler we just shipped), but there
is **no voice**.

We want **livekit voice to work without LiveAvatar**: ai-parrot should publish its
own audio track directly into the room it already owns, making the avatar an
**optional video overlay**. This "repairs" livekit for the zero-credits case and
is the foundation for the future multi-driver feature.

**Scope note (explicit):** this brainstorm covers **only the audio-output
decoupling** (Capability 1). The **multi-driver / push-to-talk + STT** capability
is deliberately **deferred to a separate feature** — its STT engine choice is an
open decision pending the team lead. Host input here stays **text** (`/agents/chat`),
exactly as livekit LITE works today.

Affected: end users on the `livekit` transport (voice works without credits),
and ops/billing (LiveAvatar minutes only spent when the avatar overlay is on).

## Constraints & Requirements

- **No STT / no mic input in this phase.** Host drives by text (`/agents/chat`).
  Multi-driver PTT+STT is a separate, later feature.
- **Two-mode audio** (LiveAvatar LITE has **no** video-only / audio-mute option —
  confirmed, see Q1): **avatar-ON + credits →** today's path (LiveAvatar publishes
  audio+video, lip-synced from our PCM); **avatar-OFF / no-credits →** ai-parrot
  publishes the audio track directly via a headless room participant. Exactly one
  audio source per mode (no double audio).
- **Auto-fallback to voice-only with a notice** when the avatar is requested but
  LiveAvatar returns `402` (no credits) — the session must NOT fail; it drops to
  the avatar-OFF (ai-parrot direct audio) mode.
- **Frontend ≈ unchanged.** `_startLiveKit` already subscribes to remote
  video + audio generically (`TrackSubscribed`), so the browser does not care who
  publishes the audio. Only a small "avatar unavailable, continuing with voice"
  notice is added.
- **Multi-viewer (FEAT-173) keeps working** — viewers subscribe-only to whatever
  audio/video is in the room; in avatar-OFF mode they hear ai-parrot's audio even
  with zero LiveAvatar credits.
- Reuse the existing room ownership (`mint_room_tokens`) and the Supertonic TTS
  pipeline. Do not regress fullmode (Mode B) or ws-pcm (Mode D).

---

## Options Explored

### Option A: `livekit-rtc` headless audio participant (building block)

ai-parrot joins the LiveKit room it already owns (using the publish-capable
`agent_token` from `mint_room_tokens`) via the **livekit realtime Python SDK**
(`livekit`, a.k.a. livekit-rtc), creates an `AudioSource` + `LocalAudioTrack`, and
pushes the Supertonic PCM frames to it. This is the mechanism that makes voice
work **without LiveAvatar**. (In the chosen design — Option C — this runs for the
avatar-OFF / no-credits mode.)

✅ **Pros:**
- Decouples voice from LiveAvatar → works with zero credits.
- Low-latency: PCM frames pushed straight to the room.
- Frontend essentially unchanged (already subscribes to room audio generically).
- Multi-viewer "just works" in this mode — viewers hear ai-parrot's audio.

❌ **Cons:**
- New dependency: the `livekit` realtime SDK (distinct from the `livekit-api`
  already vendored, which only mints tokens / calls room service).
- New "headless publisher" component to build + lifecycle-manage (join, publish,
  flush on interrupt, teardown alongside the avatar session store).
- As a *standalone always-on audio source* it cannot coexist with the avatar-ON
  path without double audio, because **LiveAvatar LITE cannot publish video-only**
  (confirmed, Q1). Hence it is used as the avatar-OFF mode inside Option C, not as
  a single unified source.

📊 **Effort:** Medium (backend-heavy; frontend trivial)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `livekit` (livekit-rtc) | Realtime SDK: join room, publish `AudioSource`/`LocalAudioTrack` | **NEW dep**, v1.1.10 (May 2026); 1.x line pairs with `livekit-api` 1.x (same repo `livekit/python-sdks`) → compatible (Q2 resolved) |
| `livekit-api>=1.0` | Mint room tokens (already used) | Present in `ai-parrot-integrations/pyproject.toml:72` |
| Supertonic (`parrot.voice.tts.supertonic_inference`) | TTS PCM (24 kHz mono 16-bit) | Already used via `AvatarVoiceProvider` |

🔗 **Existing Code to Reuse:**
- `liveavatar/room_manager.py` — `mint_room_tokens` (room + agent_token + client_token).
- `liveavatar/voice_provider.py` — `AvatarVoiceProvider` (lazy Supertonic pipeline).
- `liveavatar/speaker.py` — `AvatarTurnSpeaker` per-turn synth queue pattern (adapt the sink: feed a room AudioSource instead of the LiveAvatar WS in the avatar-OFF mode).
- `handlers/avatar.py` — `_start_avatar_session`, `AVATAR_SESSIONS_KEY` store, `avatar_upstream_error_response` (the 402 helper just added → wire the auto-fallback here).

---

### Option B: LiveKit Ingress (WHIP / URL push)

Instead of joining as a realtime participant, push the TTS audio into the room
via **LiveKit Ingress** (server-side), using the LiveKit server API
(`livekit-api`, already vendored) — no new realtime SDK.

✅ **Pros:**
- No new realtime dependency; uses the `livekit-api` already present.

❌ **Cons:**
- Ingress is designed for **continuous external streams** (RTMP/WHIP/HLS), not
  chunked per-sentence TTS — awkward fit and added setup.
- Higher/again-variable latency vs. pushing PCM frames directly.
- Still need a PCM→stream bridge; more moving parts than Option A.
- Ingress sessions may also incur their own infra cost.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `livekit-api>=1.0` | Create/manage Ingress | Already present |

🔗 **Existing Code to Reuse:**
- `liveavatar/room_manager.py` — token/room plumbing.

---

### Option C: Two-mode hybrid (RECOMMENDED)

Keep today's path when the avatar is **ON** (LiveAvatar publishes audio+video,
lip-synced from our PCM), and have ai-parrot publish the audio directly (Option A's
headless publisher) when the avatar is **OFF / no credits**. Each mode has exactly
one audio source.

✅ **Pros:**
- Does **not** require LiveAvatar video-only (which does not exist — Q1) → no
  double-audio problem.
- Smallest change to the proven avatar-ON path (it stays exactly as it is today).
- Still fully achieves the goal: **livekit voice without LiveAvatar** (avatar-OFF
  mode) + auto-fallback on no-credits.

❌ **Cons:**
- Two audio code paths to maintain and test (avatar-ON vs avatar-OFF).
- Avatar-ON still depends on LiveAvatar credits (no resilience in that mode — but
  it auto-falls back to avatar-OFF on `402`, so the user is never stuck).

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A (needs `livekit` realtime SDK for the
avatar-OFF path).

🔗 **Existing Code to Reuse:** same as Option A, plus the existing avatar-ON path
(`speaker.py` → `avatar_ws.py` → LiveAvatar) left untouched.

---

## Recommendation

**Option C (two-mode hybrid)** is recommended, built on **Option A's** headless
`livekit-rtc` publisher for the avatar-OFF path.

Research resolved the question that drove this: **LiveAvatar LITE cannot publish
video-only and offers no way to suppress its own audio** (confirmed against the
LITE docs and the `create_session_token` payload — only `video_settings`
quality/encoding, no audio flag). So the originally-considered "unified, ai-parrot
always the audio" form is not cleanly possible — with the avatar ON it would
double the audio. The pragmatic, robust answer is two modes, each with a single
audio source: keep the working LiveAvatar path when the avatar is on, and use
ai-parrot's direct publisher when it is off / out of credits. This still delivers
the actual goal (livekit voice without LiveAvatar) and the auto-fallback, while
leaving the proven avatar-ON path untouched. The trade-off — two audio paths — is
small and forced by LiveAvatar's design.

---

## Feature Description

### User-Facing Behavior
- In `livekit` mode, **voice works regardless of the avatar** — even with zero
  LiveAvatar credits. The host types; the bot speaks (audio in the room).
- The **avatar toggle** becomes a true optional **video overlay**: ON (and credits
  available) → avatar face + voice (LiveAvatar); OFF → voice-only (ai-parrot).
- If the avatar is requested but LiveAvatar has no credits, the session **auto-
  falls back to the voice-only mode** and shows a small notice ("Avatar
  unavailable — continuing with voice."). The conversation never breaks.
- **Multi-viewer** keeps working: shared viewers hear the bot's voice (and see the
  avatar when present).

### Internal Behavior
1. `/start` mints room tokens (`mint_room_tokens`) as today — the room is ours.
2. **Mode select** by the avatar toggle + credit availability:
   - **avatar-ON + credits →** today's path: LiveAvatar joins and publishes
     audio+video; ai-parrot feeds it PCM via the `agent.speak` WS (unchanged).
   - **avatar-OFF / no-credits →** ai-parrot joins the room as a headless
     participant (`agent_token`) and publishes an `AudioSource`/`LocalAudioTrack`.
3. On each `/agents/chat` turn, Supertonic synthesizes PCM (reusing the
   `AvatarTurnSpeaker` queue pattern); the PCM is routed to the active sink —
   the LiveAvatar WS (avatar-ON) or the room AudioSource (avatar-OFF).
4. On a `402` while attempting avatar-ON: skip LiveAvatar, switch to the
   ai-parrot direct-audio mode, emit the fallback notice.
5. `/stop` (and shutdown) tears down whichever publisher is active (ai-parrot room
   participant and/or the LiveAvatar session) cleanly.

### Edge Cases & Error Handling
- **No credits (402):** auto-fallback to the voice-only mode (do not fail). Wire
  via the existing `avatar_upstream_error_response` / no-credits detection.
- **Barge-in / interrupt:** flush the active sink — the room `AudioSource` buffer
  (avatar-OFF) or the existing `interrupt()` (avatar-ON).
- **ai-parrot participant disconnect / reconnect (avatar-OFF):** re-join +
  re-publish, or fail the turn gracefully (text still streams).
- **Teardown ordering:** close the room participant before/with the avatar session
  to avoid orphaned LiveKit minutes.

---

## Capabilities

### New Capabilities
- `livekit-direct-audio`: ai-parrot publishes its own TTS audio track into the
  LiveKit room (avatar-OFF mode); avatar becomes an optional video overlay;
  auto-fallback to voice-only on no-credits.

### Modified Capabilities
- `livekit-lite-multiviewer` (FEAT-173): in the avatar-OFF mode the room's audio
  publisher is ai-parrot (not LiveAvatar); viewers subscribe to ai-parrot's audio.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ai-parrot-integrations/.../liveavatar/` (new audio-publisher module) | adds | Headless room participant + `AudioSource`/`LocalAudioTrack` from Supertonic PCM (avatar-OFF mode) |
| `liveavatar/speaker.py` | modifies | Sink is mode-aware: room audio track (avatar-OFF) or the LiveAvatar `agent.speak` WS (avatar-ON) |
| `liveavatar/avatar_ws.py` | depends on | Unchanged; used only in the avatar-ON mode |
| `handlers/avatar.py` (`_start_avatar_session`) | modifies | Mode select (avatar on/off + credits); join room as audio publisher in avatar-OFF; wire 402 auto-fallback |
| `liveavatar/room_manager.py` | depends on | Reuse `mint_room_tokens` (agent_token for ai-parrot to publish) |
| `pyproject.toml` (ai-parrot-integrations) | adds | New `livekit` (realtime SDK) dependency (~1.1.x) |
| Frontend `AgentVoiceChat.svelte` / `voice-session.svelte.ts` | modifies (small) | Auto-fallback notice; avatar toggle already drives the request; `TrackSubscribed` already generic |

**Breaking changes:** none for ws-pcm/fullmode. In avatar-OFF mode the livekit
audio source changes (LiveAvatar → ai-parrot) but the client contract (`/start` →
`{livekit_url, client_token, session_id}`, subscribe-only) is unchanged.

---

## Code Context

### Verified Codebase References

#### Backend (ai-parrot) — verified 2026-06-23
```python
# liveavatar/room_manager.py — "Mints a LiveKit Cloud room plus client/agent JWT
#   tokens" (LIVEKIT_URL=wss://<project>.livekit.cloud, LIVEKIT_API_KEY/SECRET).
#   lazy: from livekit import api as livekit_api  (room_manager.py:37)
#   mint_room_tokens(session_id, agent_id) -> LiveKitRoomTokens(livekit_url, room,
#     client_token [subscribe-only], agent_token [publish, server-side only])
#   used at handlers/avatar.py:204

# liveavatar/models.py — LiveAvatarConfig has video_settings (quality/encoding,
#   both TODO-unconfirmed), is_sandbox, max_session_duration. NO audio flag.
#   client.create_session_token payload: livekit_config, video_settings,
#   max_session_duration, is_sandbox — NO audio/video-only option (Q1 evidence).

# liveavatar/voice_session.py — VoiceAvatarSession (FEAT-245): connects a realtime
#   PCM source to the LiveAvatar mouth (AvatarWebSocket). TODAY'S path; routes
#   audio THROUGH LiveAvatar (NOT a direct room publisher).

# liveavatar/speaker.py — AvatarTurnSpeaker(handle, synth_pcm_fn): async ctx mgr,
#   .feed(text) (non-blocking) + .finish(); background synth→send queue (FEAT-242).

# liveavatar/avatar_ws.py — AvatarWebSocket: sends PCM base64 inside
#   {"type":"agent.speak"} to the LiveAvatar LITE WS (ws_url from /v1/sessions/start).

# liveavatar/voice_provider.py — AvatarVoiceProvider: lazy shared Supertonic pipeline;
#   from parrot.voice.tts.supertonic_inference import SupertonicPipeline (24 kHz mono 16-bit).

# handlers/avatar.py:_start_avatar_session (LITE start) — mints tokens, opens
#   LiveAvatarClient, start_session; AVATAR_SESSIONS_KEY store; on failure now
#   returns avatar_upstream_error_response(exc) -> 402 (no credits) / 502.
```

#### livekit realtime SDK (Q2 — verified via PyPI / livekit/python-sdks)
```
package: livekit  (the realtime SDK; "livekit-rtc" is the legacy name)
version: 1.1.10 (released 2026-05-21); 1.x pairs with livekit-api 1.x.
API:  rtc.AudioSource(sample_rate, num_channels)
      rtc.LocalAudioTrack.create_audio_track(name, source)
      room.local_participant.publish_track(track, options)
      await source.capture_frame(frame)   # push PCM
```

### Does NOT Exist (Anti-Hallucination)
- ~~LiveAvatar LITE "video-only" / audio-mute / publish-audio:false option~~ —
  **confirmed does NOT exist** (LITE docs + `create_session_token` payload). The
  avatar always publishes audio+video. This is why the design is two-mode.
- ~~A direct LiveKit room **audio publisher** in ai-parrot~~ — today only
  `livekit.api` (tokens) is used; no `rtc.Room`/`AudioSource`/`LocalAudioTrack`
  usage. Must be built.
- ~~`livekit` realtime SDK as a dependency~~ — NOT present; only `livekit-api` is.
  New dependency required (`livekit` ~1.1.x).

---

## Parallelism Assessment

- **Internal parallelism**: Low. The headless audio-publisher component, the
  `_start_avatar_session` mode-select wiring, and the speaker sink are tightly
  coupled (one audio path). Best done sequentially in one worktree.
- **Cross-feature independence**: Shares `handlers/avatar.py` + `liveavatar/` with
  FEAT-173 — but FEAT-173 is **merged** (PR #131), so no in-flight conflict. The
  future multi-driver/STT feature will build on top of this one.
- **Recommended isolation**: `per-spec`.
- **Rationale**: single coherent backend change with a thin frontend touch; the
  pieces are interdependent and small enough for one worktree.

---

## Open Questions

### Resolved by research (2026-06-23)
- [x] **Q1 — LiveAvatar video-only?** — *Owner: us (research)*: **NO.** LiveAvatar LITE has no session-creation parameter, `video_settings`/audio flag, or event to suppress its audio or publish video-only; `agent.speak` always yields lip-synced **audio+video** (confirmed against `docs.liveavatar.com/docs/lite-mode/events` and the `create_session_token` payload, which only carries `video_settings` quality/encoding + `livekit_config` + `max_session_duration`). → Drives the **two-mode** design (Option C): keep LiveAvatar audio when avatar-ON; ai-parrot direct audio when avatar-OFF.
- [x] **Q2 — livekit realtime SDK + compatibility?** — *Owner: us (research)*: Package is **`livekit` v1.1.10** (2026-05-21); exposes exactly what we need — `rtc.AudioSource` → `LocalAudioTrack.create_audio_track()` → `local_participant.publish_track()` → `source.capture_frame()`. The 1.x realtime SDK is published from the same repo (`livekit/python-sdks`) as `livekit-api` 1.x and is designed to pair with it → compatible with the existing `livekit-api>=1.0`. New dep, clean.
- [x] **Q3 — LiveKit Cloud cost of a headless participant?** — *Owner: us (research)*: **Negligible.** It is LiveKit **Cloud** (`wss://<project>.livekit.cloud`), billed by connection-minutes = participants × minutes × rate (Build: 5,000 min free; Ship: $0.0005/min; Scale: $0.0004/min). ai-parrot = **+1 participant** → ≈ **$0.005 per 10-min session**. In avatar-OFF mode there are *fewer* participants than avatar-ON (no LiveAvatar joins), and it is far cheaper than LiveAvatar credits. Acceptable. (Sources: livekit.com/pricing, pypi.org/project/livekit, docs.liveavatar.com.)

### Deferred (separate feature — NOT this one)
- [ ] **Q4 — Multi-driver STT engine** (LiveKit Agents vs. Gemini Live vs. Whisper). Out of scope here; belongs to the future multi-driver / push-to-talk feature and its own brainstorm. — *Owner: team lead (separate decision)*
