---
type: Wiki Overview
title: 'Feature Specification: LiveKit Direct Audio (avatar-optional livekit voice)'
id: doc:sdd-specs-livekit-direct-audio-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `livekit` voice transport (LITE, FEAT-173 on the frontend) depends **entirely**
relates_to:
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LiveKit Direct Audio (avatar-optional livekit voice)

**Feature ID**: FEAT-256
**Date**: 2026-06-23
**Author**: Juanfran
**Status**: approved
**Target version**: next

> Source brainstorm: `sdd/proposals/livekit-direct-audio.brainstorm.md`
> (research-complete: Q1–Q3 resolved; design = two-mode hybrid).

---

## 1. Motivation & Business Requirements

### Problem Statement
The `livekit` voice transport (LITE, FEAT-173 on the frontend) depends **entirely**
on LiveAvatar for audio. ai-parrot synthesizes the bot's speech (Supertonic PCM)
but routes it to LiveAvatar's `agent.speak` WebSocket; LiveAvatar lip-syncs it and
publishes **audio + video** into the LiveKit room. When the LiveAvatar account has
**no credits** (`403 code 4033`), `start_session` fails, the room never gets an
audio publisher, and livekit voice is unusable (the frontend now shows a clean
`402` banner — but there is no voice).

We want **livekit voice to work without LiveAvatar**, with the avatar reduced to an
**optional video overlay**. Research confirmed LiveAvatar LITE has **no video-only
/ audio-mute option** (Q1), so the design is **two-mode**: keep the LiveAvatar path
when the avatar is ON; when it is OFF or out of credits, ai-parrot publishes its
own audio track directly into the room it already owns (`mint_room_tokens`).

### Goals
- ai-parrot can publish a **direct audio track** (Supertonic TTS) into the LiveKit
  room as a headless participant, with **zero** LiveAvatar dependency.
- `livekit` voice works with the avatar **OFF** and when LiveAvatar has **no credits**.
- **Auto-fallback**: requesting the avatar but hitting `402` drops to the
  avatar-OFF (direct-audio) mode instead of failing.
- The avatar-**ON** path (LiveAvatar audio+video) is unchanged.
- Multi-viewer (FEAT-173) keeps working in the avatar-OFF mode (viewers hear the
  ai-parrot audio track).

### Non-Goals (explicitly out of scope)
- **Multi-driver / push-to-talk + STT** (any participant talking to the bot) — a
  separate future feature; its STT engine is undecided (deferred).
- No real-time mic input here; host input stays **text** (`/agents/chat`).
- No changes to ws-pcm (Gemini) or fullmode.
- No "unified single audio source" (LiveAvatar can't go video-only — Q1).

---

## 2. Architectural Design

### Overview
Add a **headless audio publisher**: ai-parrot joins the LiveKit room using the
publish-capable `agent_token` (from `mint_room_tokens`) via the `livekit` realtime
SDK, creates an `AudioSource` + `LocalAudioTrack`, and pushes Supertonic PCM frames.
The per-turn speaker becomes **mode-aware**: it routes PCM to the LiveAvatar
`agent.speak` WS (avatar-ON) or to the room `AudioSource` (avatar-OFF). The session
start handler selects the mode from the request's avatar flag + credit availability,
and on a LiveAvatar `402` auto-falls back to the avatar-OFF publisher.

### Component Diagram
```
/agents/avatar/{id}/start (avatar flag)
        │
        ▼
_start_avatar_session ──► mint_room_tokens (our LiveKit Cloud room)
        │
        ├─ avatar ON + credits ──► LiveAvatarClient.start_session ──► LiveAvatar joins
        │                              ▲                              (publishes audio+video)
        │        AvatarTurnSpeaker ─────┘  (PCM → agent.speak WS)   [unchanged path]
        │
        └─ avatar OFF / 402 ──► RoomAudioPublisher (NEW) ──► ai-parrot joins room
                                   ▲                          (publishes audio track)
                 AvatarTurnSpeaker ─┘  (PCM → AudioSource.capture_frame)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `liveavatar/room_manager.py` `mint_room_tokens` | uses | room + `agent_token` (publish) for ai-parrot to join |
| `liveavatar/voice_provider.py` `AvatarVoiceProvider` | uses | Supertonic PCM (24 kHz mono 16-bit) |
| `liveavatar/speaker.py` `AvatarTurnSpeaker` | modifies | mode-aware sink (LiveAvatar WS vs room AudioSource) |
| `liveavatar/avatar_ws.py` `AvatarWebSocket` | unchanged | used only in avatar-ON mode |
| `handlers/avatar.py` `_start_avatar_session` | modifies | mode select + `402` auto-fallback + teardown |
| `handlers/avatar.py` `avatar_upstream_error_response` | uses | already maps `402` no-credits (the trigger for fallback) |
| Frontend (separate repo `navigator-frontend-next`) | depends on | `/start` sends an `avatar` flag; small auto-fallback notice; `_startLiveKit` already subscribes to room audio generically |

### Data Models
```python
# Request: POST /api/v1/agents/avatar/{id}/start
#   body adds an optional avatar flag (default True for back-compat):
#   { "session_id": str, "tenant_id"?: str, "avatar"?: bool }
# Response unchanged: { livekit_url, client_token, session_id }

# New runtime handle for the direct-audio publisher (avatar-OFF mode):
class RoomAudioPublisher:
    room: "rtc.Room"
    source: "rtc.AudioSource"
    track: "rtc.LocalAudioTrack"
```

### New Public Interfaces
```python
# liveavatar/room_audio_publisher.py (NEW)
class RoomAudioPublisher:
    @classmethod
    async def start(cls, tokens: LiveKitRoomTokens, *, sample_rate: int = 24000,
                    num_channels: int = 1) -> "RoomAudioPublisher": ...
    async def capture_pcm(self, pcm: bytes) -> None: ...   # push 24 kHz mono 16-bit
    async def flush(self) -> None: ...                     # barge-in / interrupt
    async def aclose(self) -> None: ...                    # idempotent teardown
```

---

## 3. Module Breakdown

### Module 1: `RoomAudioPublisher` (headless room audio)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_audio_publisher.py`
- **Responsibility**: join the LiveKit room with `agent_token` via the `livekit`
  realtime SDK; create `AudioSource` + `LocalAudioTrack`; `publish_track`; push PCM
  via `capture_frame`; flush on interrupt; idempotent `aclose`.
- **Depends on**: `room_manager.mint_room_tokens` (tokens), new `livekit` dep.

### Module 2: Mode-aware speaker sink
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speaker.py`
- **Responsibility**: extend `AvatarTurnSpeaker` so its synth→send consumer routes
  the Supertonic PCM to the active sink — the LiveAvatar `agent.speak` WS (avatar-ON)
  or `RoomAudioPublisher.capture_pcm` (avatar-OFF). Keep the non-blocking queue +
  graceful-degradation behavior.
- **Depends on**: Module 1, `voice_provider` (Supertonic).

### Module 3: Session-start mode select + auto-fallback
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/avatar.py` (`_start_avatar_session`)
- **Responsibility**: read the `avatar` flag (default True); avatar-ON + credits →
  today's LiveAvatar path; avatar-OFF → start `RoomAudioPublisher`; on a LiveAvatar
  `ClientResponseError` that maps to no-credits (`402`), **auto-fallback** to the
  avatar-OFF publisher instead of returning the error. Register the active publisher
  in `AVATAR_SESSIONS_KEY`; tear it down in `_stop_avatar_session`.
- **Depends on**: Modules 1–2, existing `avatar_upstream_error_response`.

### Module 4: Dependency + config
- **Path**: `packages/ai-parrot-integrations/pyproject.toml` (+ any env)
- **Responsibility**: add `livekit` (realtime SDK, ~1.1.x) to the extra that already
  carries `livekit-api`; confirm version resolution with existing pins.
- **Depends on**: none.

> Frontend follow-up (separate repo, NOT an ai-parrot module): `AgentVoiceChat`
> sends `avatar: avatarEnabled` to `/start` and shows the auto-fallback notice.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_room_audio_publisher_start_publishes_track` | M1 | join + `publish_track` called with an audio track (livekit SDK mocked) |
| `test_room_audio_publisher_capture_pcm` | M1 | `capture_pcm` forwards frames to `AudioSource.capture_frame` |
| `test_room_audio_publisher_aclose_idempotent` | M1 | double `aclose` never raises; disconnects room |
| `test_speaker_routes_to_room_when_avatar_off` | M2 | PCM goes to `RoomAudioPublisher`, NOT the LiveAvatar WS |
| `test_speaker_routes_to_liveavatar_when_avatar_on` | M2 | unchanged avatar-ON path still used |
| `test_start_avatar_off_uses_publisher` | M3 | `avatar=false` → no LiveAvatar `start_session`; publisher started |
| `test_start_402_autofalls_back` | M3 | LiveAvatar `402` → avatar-OFF publisher started; 200 response (not 402) |
| `test_start_avatar_on_unchanged` | M3 | `avatar=true` + credits → today's LiveAvatar path |

### Integration Tests
| Test | Description |
|---|---|
| `test_livekit_direct_audio_end_to_end_mock` | mocked room: `/start` (avatar off) → a turn → PCM frames captured to the room track; `/stop` tears down |
| `test_autofallback_end_to_end_mock` | `/start` (avatar on) with LiveAvatar `402` → falls back to publisher → turn audio still flows |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_room_tokens():
    return LiveKitRoomTokens(livekit_url="wss://x.livekit.cloud", room="r",
                             client_token="c", agent_token="a")
# livekit rtc Room/AudioSource/LocalAudioTrack mocked (no real network).
```

---

## 5. Acceptance Criteria

- [ ] `avatar=false` (or no credits) → ai-parrot publishes a direct audio track; the
      browser hears the bot with **zero** LiveAvatar usage.
- [ ] `avatar=true` + credits → unchanged LiveAvatar audio+video path.
- [ ] LiveAvatar `402` (no credits) on start → **auto-fallback** to the direct-audio
      mode (session starts, does NOT return an error).
- [ ] Barge-in/interrupt flushes the active sink (room `AudioSource` or LiveAvatar).
- [ ] `_stop_avatar_session` cleanly tears down whichever publisher is active (no
      orphaned LiveKit participant / minutes).
- [ ] ws-pcm and fullmode are unchanged; no breaking change to the `/start` response
      contract (`avatar` flag defaults True).
- [ ] All unit + integration tests pass (`pytest packages/ -v`).
- [ ] `livekit` realtime dep resolves alongside `livekit-api` with no conflict.

---

## 6. Codebase Contract

> Verified against ai-parrot `dev` on 2026-06-23.

### Verified Imports
```python
# Token minting (server SDK) — already present
from livekit import api as livekit_api        # liveavatar/room_manager.py:37 (lazy)

# Realtime SDK — NEW dependency (livekit ~1.1.x); publish-side API:
#   rtc.Room(); await room.connect(url, token)
#   src = rtc.AudioSource(sample_rate, num_channels)
#   track = rtc.LocalAudioTrack.create_audio_track("agent-voice", src)
#   await room.local_participant.publish_track(track, rtc.TrackPublishOptions(...))
#   await src.capture_frame(rtc.AudioFrame(...))
```

### Existing Class Signatures
```python
# liveavatar/room_manager.py
#   mint_room_tokens(session_id: str, agent_id: str) -> LiveKitRoomTokens
#     LiveKitRoomTokens(livekit_url, room, client_token [subscribe-only],
#                       agent_token [publish, server-side only])   # models.py:58

# liveavatar/speaker.py
class AvatarTurnSpeaker:                                  # async context manager
    def __init__(self, handle, synth_pcm_fn): ...
    def feed(self, text: str) -> None: ...                # non-blocking
    async def finish(self) -> None: ...

# liveavatar/avatar_ws.py — AvatarWebSocket: sends {"type":"agent.speak","audio":b64}
#   (24 kHz mono 16-bit PCM) to the LiveAvatar LITE WS (avatar-ON only).

# liveavatar/voice_provider.py — AvatarVoiceProvider: lazy Supertonic pipeline
#   (24 kHz mono 16-bit). from parrot.voice.tts.supertonic_inference import SupertonicPipeline

# handlers/avatar.py
#   _start_avatar_session(request) -> web.Response   # mints tokens, opens LiveAvatarClient
#   AVATAR_SESSIONS_KEY                               # app store of live sessions
#   avatar_upstream_error_response(exc: ClientResponseError) -> web.Response
#       # 402 {error: avatar_no_credits} | 502 ; lands the no-credits trigger
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RoomAudioPublisher` | `mint_room_tokens` | uses `agent_token` | `room_manager.py` |
| `AvatarTurnSpeaker` (mode-aware) | `RoomAudioPublisher.capture_pcm` | sink swap | `speaker.py` |
| `_start_avatar_session` | `RoomAudioPublisher.start` / `avatar_upstream_error_response` | mode select + fallback | `handlers/avatar.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~LiveAvatar LITE "video-only" / audio-mute / `publish_audio:false`~~ — confirmed
  does NOT exist (LITE docs + `create_session_token` payload). Hence two-mode.
- ~~A direct LiveKit room audio publisher in ai-parrot~~ — no `rtc.Room`/`AudioSource`/
  `LocalAudioTrack` usage today; only `livekit.api` (tokens). Build it (M1).
- ~~`livekit` realtime SDK dependency~~ — NOT present; only `livekit-api`. Add it (M4).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; keep the existing keep-alive / "do not `async with` the session"
  caveat (avatar.py:157-176) for any long-lived participant.
- Reuse the `AvatarTurnSpeaker` non-blocking synth queue; do not block the text stream.
- Idempotent `aclose` on the publisher; never raise on teardown.
- Register/teardown the publisher in `AVATAR_SESSIONS_KEY` exactly like the LiveAvatar
  session, so `/stop` and shutdown reach it.

### Known Risks / Gotchas
- **Double audio**: never run the LiveAvatar audio path and the direct publisher at
  the same time — the mode is exclusive per session (avatar-ON XOR avatar-OFF).
- **Dep resolution**: `livekit` (rtc) must coexist with `livekit-api>=1.0` (same 1.x
  line — low risk) and any `livekit-agents` otel pins; verify on install (M4).
- **Teardown ordering**: disconnect the room participant before/with the session to
  avoid orphaned LiveKit Cloud connection-minutes.
- **Sample format**: Supertonic emits 24 kHz mono 16-bit; `AudioSource` must be
  created with matching sample_rate/channels (no resampling).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `livekit` (realtime SDK) | `~=1.1` (1.1.10, 2026-05-21) | join room + publish audio track; pairs with `livekit-api` 1.x |

---

## 8. Open Questions

> Q1–Q3 from the brainstorm were RESOLVED by research (see the brainstorm). The only
> remaining item is out of scope for this spec:

- [ ] **Multi-driver STT engine** (LiveKit Agents vs Gemini Live vs Whisper) — belongs
      to the future multi-driver / push-to-talk feature, not this one. — *Owner: team lead*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-23 | Juanfran | Initial draft from the research-complete brainstorm; two-mode design (avatar-ON keeps LiveAvatar; avatar-OFF/no-credits → ai-parrot direct audio); FEAT-256 provisional. |
