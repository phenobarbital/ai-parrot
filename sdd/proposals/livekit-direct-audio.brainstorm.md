---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: LiveKit Direct Audio (avatar-optional livekit voice)

**Date**: 2026-06-23
**Author**: Juanfran
**Status**: exploration
**Recommended Option**: A

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
- **Single audio source at all times** (no double audio): ai-parrot **always**
  publishes the audio track; when the avatar is enabled + has credits, LiveAvatar
  joins **video-only** for lip-sync overlay.
- **Auto-fallback to voice-only with a notice** when the avatar is requested but
  LiveAvatar returns `402` (no credits) — the session must NOT fail.
- **Frontend ≈ unchanged.** `_startLiveKit` already subscribes to remote
  video + audio generically (`TrackSubscribed`), so the browser does not care who
  publishes the audio. Only a small "avatar unavailable, continuing with voice"
  notice is added.
- **Multi-viewer (FEAT-173) keeps working** — viewers subscribe-only to whatever
  audio/video is in the room; with ai-parrot publishing audio, viewers hear it
  even with zero LiveAvatar credits.
- Reuse the existing room ownership (`mint_room_tokens`) and the Supertonic TTS
  pipeline. Do not regress fullmode (Mode B) or ws-pcm (Mode D).

---

## Options Explored

### Option A: `livekit-rtc` headless audio participant (RECOMMENDED)

ai-parrot joins the LiveKit room it already owns (using the publish-capable
`agent_token` from `mint_room_tokens`) via the **livekit realtime Python SDK**,
creates an `AudioSource` + `LocalAudioTrack`, and pushes the Supertonic PCM frames
to it. The room now always has an ai-parrot audio publisher. When the avatar is
enabled and credits exist, LiveAvatar additionally joins **video-only** (still fed
the same PCM for lip-sync, but not publishing audio). The browser subscribes to
the audio track (ai-parrot) and, when present, the video track (LiveAvatar).

✅ **Pros:**
- Matches the locked decision: single audio source always = ai-parrot.
- Decouples voice from LiveAvatar cleanly → works with zero credits.
- Low-latency: PCM frames pushed straight to the room (same path ws-pcm proves).
- Frontend essentially unchanged (already subscribes to room audio generically).
- Multi-viewer "just works" — viewers hear ai-parrot's audio.

❌ **Cons:**
- New dependency: the `livekit` realtime SDK (`livekit-rtc`), distinct from the
  `livekit-api` already vendored (which only mints tokens / calls room service).
- New "headless publisher" component to build + lifecycle-manage (join, publish,
  flush on interrupt, teardown alongside the avatar session store).
- Depends on confirming LiveAvatar LITE can publish **video-only** (see Open
  Questions) — otherwise the avatar-ON case would double the audio.

📊 **Effort:** Medium (backend-heavy; frontend trivial)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `livekit` (livekit-rtc) | Realtime SDK: join room, publish `AudioSource`/`LocalAudioTrack` | **NEW dep**; check version compat with `livekit-api>=1.0` and the `livekit-agents~=1.5/1.6` otel pins already in `pyproject.toml` |
| `livekit-api>=1.0` | Mint room tokens (already used) | Present in `ai-parrot-integrations/pyproject.toml:72` |
| Supertonic (`parrot.voice.tts.supertonic_inference`) | TTS PCM (24 kHz mono 16-bit) | Already used via `AvatarVoiceProvider` |

🔗 **Existing Code to Reuse:**
- `liveavatar/room_manager.py` — `mint_room_tokens` (room + agent_token + client_token).
- `liveavatar/voice_provider.py` — `AvatarVoiceProvider` (lazy Supertonic pipeline).
- `liveavatar/speaker.py` — `AvatarTurnSpeaker` per-turn synth queue pattern (adapt the sink: feed a room AudioSource instead of / in addition to the LiveAvatar WS).
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

### Option C: Two-mode hybrid (conservative fallback)

Keep today's path when the avatar is ON (LiveAvatar publishes audio+video), and
only have ai-parrot publish audio directly when the avatar is OFF / no credits.

✅ **Pros:**
- Does **not** require LiveAvatar to support video-only → no dependency on the
  critical open question.
- Smallest change to the proven avatar-ON path.

❌ **Cons:**
- Contradicts the locked "unified audio" decision — two audio code paths to
  maintain, two behaviors to test.
- Avatar-ON still fully depends on LiveAvatar credits (no resilience there).
- Audio source/identity differs by mode → viewer/transcript handling diverges.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A (still needs `livekit-rtc` for the
avatar-OFF path).

🔗 **Existing Code to Reuse:** same as Option A.

> Keep Option C in reserve: if the Open Question below resolves "LiveAvatar
> cannot publish video-only", the avatar-ON case falls back to Option C while
> avatar-OFF uses Option A.

---

## Recommendation

**Option A** is recommended. It directly realizes the two decisions already made
with the user — *audio-direct, avatar optional* and *unified single audio source* —
and gives the cleanest, lowest-latency result with an essentially unchanged
frontend. The cost is a new realtime dependency (`livekit-rtc`) and one new
backend component, both well-scoped.

The honest trade-off: Option A's "unified" form (ai-parrot audio + LiveAvatar
**video-only**) hinges on LiveAvatar LITE being able to render the mouth **without
publishing its own audio**. That is the one unknown. If it cannot, we do **not**
lose the feature — the avatar-OFF / no-credits path (the actual goal: "livekit
without LiveAvatar") still works via Option A, and the avatar-ON path degrades to
Option C. So Option A is safe to start even before the open question is resolved.

---

## Feature Description

### User-Facing Behavior
- In `livekit` mode, **voice works regardless of the avatar** — even with zero
  LiveAvatar credits. The host types; the bot speaks (audio in the room).
- The **avatar toggle** becomes a true optional **video overlay**: ON (and credits
  available) → avatar face appears over the same voice; OFF → voice-only.
- If the avatar is requested but LiveAvatar has no credits, the session **auto-
  falls back to voice-only** and shows a small notice ("Avatar unavailable —
  continuing with voice."). The conversation never breaks.
- **Multi-viewer** keeps working: shared viewers hear the bot's voice (and see the
  avatar when present).

### Internal Behavior
1. `/start` mints room tokens (`mint_room_tokens`) as today — the room is ours.
2. ai-parrot **joins the room** as a headless participant (`agent_token`) and
   publishes an `AudioSource`/`LocalAudioTrack`.
3. On each `/agents/chat` turn: Supertonic synthesizes PCM → pushed to the room
   audio track (per-sentence, reusing the `AvatarTurnSpeaker` queue pattern).
4. If the avatar is enabled **and** credits exist: LiveAvatar joins **video-only**
   and is fed the same PCM for lip-sync (it does not publish audio).
5. If the avatar is requested but `402`: skip LiveAvatar, continue audio-only,
   emit the fallback notice.
6. `/stop` (and shutdown) tears down ai-parrot's room participant + audio track
   alongside the existing avatar-session teardown.

### Edge Cases & Error Handling
- **No credits (402):** auto-fallback to voice-only (do not fail). Wire via the
  existing `avatar_upstream_error_response`/no-credits detection.
- **LiveAvatar can't go video-only:** fall back to Option C for avatar-ON; avatar-
  OFF unaffected (see Open Questions).
- **Barge-in / interrupt:** flush the room `AudioSource` buffer (mirror the
  existing `interrupt()`/flush semantics).
- **ai-parrot participant disconnect / reconnect:** re-join + re-publish, or fail
  the turn gracefully (text still streams).
- **Teardown ordering:** ensure the room participant closes before/with the avatar
  session to avoid orphaned LiveKit minutes.

---

## Capabilities

### New Capabilities
- `livekit-direct-audio`: ai-parrot publishes its own TTS audio track into the
  LiveKit room; avatar becomes an optional video overlay; auto-fallback to
  voice-only on no-credits.

### Modified Capabilities
- `livekit-lite-multiviewer` (FEAT-173): the room's audio publisher changes from
  LiveAvatar to ai-parrot; viewers subscribe to ai-parrot's audio.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ai-parrot-integrations/.../liveavatar/` (new audio-publisher module) | adds | Headless room participant + `AudioSource`/`LocalAudioTrack` from Supertonic PCM |
| `liveavatar/speaker.py` | modifies | Sink feeds the room audio track (instead of / alongside the LiveAvatar `agent.speak` WS) |
| `liveavatar/avatar_ws.py` | depends on | Only used when avatar overlay is ON (video-only) |
| `handlers/avatar.py` (`_start_avatar_session`) | modifies | Join room as audio publisher; make LiveAvatar optional; wire 402 auto-fallback |
| `liveavatar/room_manager.py` | depends on | Reuse `mint_room_tokens` (agent_token for ai-parrot to publish) |
| `pyproject.toml` (ai-parrot-integrations) | adds | New `livekit` (livekit-rtc) realtime dependency |
| Frontend `AgentVoiceChat.svelte` / `voice-session.svelte.ts` | modifies (small) | Auto-fallback notice; avatar toggle already drives the request; `TrackSubscribed` already generic |

**Breaking changes:** none for ws-pcm/fullmode. The livekit audio source changes
(LiveAvatar → ai-parrot) but the client contract (`/start` → `{livekit_url,
client_token, session_id}`, subscribe-only) is unchanged.

---

## Code Context

### Verified Codebase References

#### Backend (ai-parrot) — verified 2026-06-23
```python
# liveavatar/room_manager.py:37 — tokens come from livekit.api (server SDK)
from livekit import api as livekit_api   # lazy import inside the manager
# mint_room_tokens(session_id, agent_id) -> tokens(livekit_url, room, agent_token, client_token)
#   used at handlers/avatar.py:204

# liveavatar/voice_session.py — VoiceAvatarSession (FEAT-245): connects a realtime
#   PCM source to the LiveAvatar mouth (AvatarWebSocket). TODAY'S path; still routes
#   audio THROUGH LiveAvatar (NOT a direct room publisher).
#   .start(agent_id, session_id, tenant_id?, avatar_id?) / .speak(pcm) / .finish_turn() / .interrupt() / .aclose()

# liveavatar/speaker.py — AvatarTurnSpeaker(handle, synth_pcm_fn): async ctx mgr,
#   .feed(text) (non-blocking) + .finish(); background synth→send queue (FEAT-242).

# liveavatar/avatar_ws.py — AvatarWebSocket: sends PCM as base64 inside
#   {"type":"agent.speak"} to the LiveAvatar LITE WS (ws_url from /v1/sessions/start).

# liveavatar/voice_provider.py — AvatarVoiceProvider: lazy shared Supertonic pipeline;
#   from parrot.voice.tts.supertonic_inference import SupertonicPipeline
#   (env SUPERTONIC_MODEL_PATH; native rate → 24 kHz mono 16-bit).

# handlers/avatar.py:_start_avatar_session (LITE start) — mints tokens, opens
#   LiveAvatarClient, start_session; AVATAR_SESSIONS_KEY store; on failure now
#   returns avatar_upstream_error_response(exc) -> 402 (no credits) / 502 (this session).
```

#### Verified deps (pyproject.toml)
```
ai-parrot-integrations/pyproject.toml:72   "livekit-api>=1.0"      # token / room service ONLY
pyproject.toml (root)                      livekit-agents ~=1.5/1.6 referenced (otel pin notes)
```

### Does NOT Exist (Anti-Hallucination)
- ~~A direct LiveKit room **audio publisher** in ai-parrot~~ — today only
  `livekit.api` (tokens) is used; there is **no** `rtc.Room` / `AudioSource` /
  `LocalAudioTrack` / `room.connect()` usage. Must be built (Option A).
- ~~`livekit` / `livekit-rtc` realtime SDK as a dependency~~ — NOT present; only
  `livekit-api` is. New dependency required.
- ~~A "publish audio to room" mode in `VoiceAvatarSession`/`speaker.py`~~ — they
  feed the **LiveAvatar WS**, not the room.

---

## Parallelism Assessment

- **Internal parallelism**: Low. The headless audio-publisher component, the
  `_start_avatar_session` wiring, and the speaker sink are tightly coupled (one
  audio path). Best done sequentially in one worktree.
- **Cross-feature independence**: Shares `handlers/avatar.py` + `liveavatar/` with
  FEAT-173 — but FEAT-173 is **merged** (PR #131), so no in-flight conflict. The
  future multi-driver/STT feature will build on top of this one.
- **Recommended isolation**: `per-spec`.
- **Rationale**: single coherent backend change with a thin frontend touch; the
  pieces are interdependent and small enough for one worktree.

---

## Open Questions
- [ ] Can LiveAvatar LITE publish **video-only** (suppress its own audio track) while still lip-syncing from the PCM we feed it? — *Owner: Jesus (boss)* — CRITICAL: decides whether the unified-audio (avatar-ON) form is achievable, or the avatar-ON case falls back to Option C. Does NOT block the avatar-OFF / no-credits goal.
- [ ] `livekit` (livekit-rtc) realtime SDK version + compatibility with the existing `livekit-api>=1.0` and `livekit-agents` otel pins in `pyproject.toml`. — *Owner: implementer*
- [ ] Does ai-parrot joining our own LiveKit room as a participant consume LiveKit minutes/cost, and is that acceptable vs. the saved LiveAvatar credits? — *Owner: Jesus (boss)*
- [ ] STT engine for the FUTURE multi-driver feature (LiveKit Agents vs. Gemini Live vs. Whisper) — deferred to a separate brainstorm, pending the team lead. — *Owner: Jesus (boss)*
