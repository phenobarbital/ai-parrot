---
type: Wiki Overview
title: 'Brainstorm: LiveKit Gemini Voice Input (host PTT → Gemini STT → agent)'
id: doc:sdd-proposals-livekit-gemini-voice-input-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After FEAT-256, the `livekit` transport has voice **output** (the ai-parrot
  agent
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: LiveKit Gemini Voice Input (host PTT → Gemini STT → agent)

**Date**: 2026-06-24
**Author**: Juanfran
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

After FEAT-256, the `livekit` transport has voice **output** (the ai-parrot agent
speaks into the shared LiveKit room via Supertonic; avatar optional) but its
**input is text-only** — the Push-to-Talk button is intentionally disabled. So you
cannot *talk* to the bot in livekit; you type. ws-pcm lets you talk, but it is a
private 1:1 stream — it cannot broadcast to a shared room (no multi-viewer, no
in-room avatar). The whole point of livekit is the **shared room**.

We want **voice input for the host in livekit**: the host pushes to talk, their
speech is transcribed, the **ai-parrot agent** answers (its real tools/RAG), and
the answer is **spoken into the room** (FEAT-256 output) so viewers hear it.

### Decisions locked (with the user)
- **Brain = the ai-parrot agent** (`/agents/chat`), NOT Gemini. Gemini is used
  **only for STT** (transcribe the host's mic). The response audio is Supertonic
  → the room (FEAT-256), not Gemini TTS.
- **Scope = host only** (the existing multi-viewer audience just listens).
  Multi-driver (several participants talking, turn arbitration) is **phase 2**.

### Why not just use ws-pcm?
ws-pcm already does 1:1 voice (Gemini full-duplex). It **cannot** put the audio in
a shared room → no multi-viewer, no in-room avatar overlay. This feature brings
voice input to the **shared-room** scenario, which is livekit's reason to exist.

---

## Constraints & Requirements

- **Gemini = STT only.** Transcribe the host's speech; do NOT let Gemini generate
  a spoken response (the agent answers). Reuse the existing Gemini Live path in
  STT-only mode.
- **Output reuses FEAT-256**: agent response → Supertonic → LiveKit room.
- **Reuse the ws-pcm mic capture** (pcm-worklet, `_startMicWsPcm`) + the
  transcription accumulation (`pendingUserId`) already in `voice-session.svelte.ts`.
- **Re-enable PTT in livekit** for the host only (today `canPushToTalk` excludes
  livekit). ws-pcm and fullmode unchanged.
- **Depends on FEAT-256** (the room audio publisher is the output path).
- Barge-in: pushing to talk should interrupt the bot's in-room audio.

---

## Options Explored

### Option A: Reuse the Gemini Live `/ws/voice` path in STT-only mode (RECOMMENDED)

In livekit mode, when the host pushes to talk, open the **existing** Gemini voice
WebSocket (`agent_voice.py` / `GeminiLiveClient`) configured **STT-only**
(`input_audio_transcription` on, response suppressed). Stream the mic PCM (reuse
`_startMicWsPcm` + pcm-worklet). On a final `input_transcription`, route the text
to `/agents/chat` (the same `handleSend` livekit branch) → the agent answers →
Supertonic publishes the answer to the room (FEAT-256). The LiveKit room is for
audio **out**; the Gemini WS is for STT **in**.

✅ **Pros:**
- Maximum reuse: Gemini STT path + front mic capture + transcription accumulation
  + the livekit `handleSend` turn + FEAT-256 output all already exist.
- No new STT engine / no LiveKit Agents worker / no new heavy infra.
- Keeps the real ai-parrot agent as the brain (tools/RAG).

❌ **Cons:**
- Two connections per session in livekit (LiveKit room for output + Gemini WS for
  STT). Lifecycle to manage.
- Needs an explicit **STT-only mode** on the Gemini path so Gemini does not also
  answer (avoid a "double brain").

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` (Gemini Live) | STT (input transcription) | already used by ws-pcm; add STT-only mode |
| (front) pcm-worklet | mic capture | already shipped for ws-pcm |

🔗 **Existing Code to Reuse:**
- `handlers/agent_voice.py` — the `/ws/voice` Gemini handler.
- `clients/live.py` — `GeminiLiveClient`: `input_audio_transcription` (live.py:666),
  `input_transcription` event (live.py:806-814), config knobs
  `response_modalities`/`enable_input_transcription` (live.py:722).
- Front `voice-session.svelte.ts` — `_startMicWsPcm`, pcm-worklet, the
  `transcription`/`pendingUserId` accumulation, and the livekit `handleSend` →
  `streamChatWithAgent` turn.
- FEAT-256 `RoomAudioPublisher` — the output path (agent answer → room).

---

### Option B: Per-turn HTTP STT (record → upload → transcribe)

PTT records the utterance; on release, upload the audio to a new HTTP STT endpoint
(Gemini batch transcription) → text → `/agents/chat` → room.

✅ **Pros:** simplest lifecycle (no second live socket); request/response.
❌ **Cons:** higher latency (no streaming partials, no "listening…" feedback);
new endpoint; worse UX than the realtime path we already have.

📊 **Effort:** Medium

---

### Option C: LiveKit Agents STT in the room

The host publishes their mic as a room track; a server-side **LiveKit Agents**
worker subscribes and runs STT (VAD/turn-detection native).

✅ **Pros:** fully in-room; natural base for multi-driver (phase 2).
❌ **Cons:** reintroduces the LiveKit Agents worker infra that FEAT-249 removed;
this is exactly the "which STT engine" decision we deferred — heavier, and not
needed when Gemini STT already exists. Better revisited for phase-2 multi-driver.

📊 **Effort:** High

---

## Recommendation

**Option A.** It reuses everything that already works — the Gemini STT path, the
ws-pcm mic capture, the livekit text-turn pipeline, and the FEAT-256 output — and
keeps the ai-parrot agent as the brain. The only genuinely new backend piece is an
**STT-only mode** on the Gemini voice path (transcribe input, suppress the spoken
response) so we don't get a "double brain". It avoids new STT engines and the
LiveKit Agents worker (which we can revisit for phase-2 multi-driver, Option C).

---

## Feature Description

### User-Facing Behavior
- In `livekit` mode, **Push-to-Talk is enabled for the host**. Hold/click to talk;
  a "listening…" hint shows; speech is transcribed and appears as the user turn.
- The bot answers **out loud in the room** (FEAT-256), so **viewers also hear it**.
  Avatar overlay still optional.
- ws-pcm and fullmode behave exactly as before.

### Internal Behavior
1. Host starts a livekit session (FEAT-256 output ready).
2. On PTT, the front opens the Gemini voice WS in **STT-only** mode and streams mic
   PCM (reusing `_startMicWsPcm`).
3. Gemini emits `input_transcription`; the front accumulates it (`pendingUserId`).
4. On final transcription, the front routes the text to `/agents/chat`
   (`handleSend` livekit branch) → the agent answers → Supertonic publishes the
   answer into the room (FEAT-256).
5. Pushing to talk again interrupts (barge-in) the in-room audio.

### Edge Cases & Error Handling
- **No STT result / Gemini error:** log + let the host retry; never break the session.
- **Double-brain guard:** Gemini must NOT answer — STT-only config verified.
- **Barge-in:** flush the room audio when the host starts talking.
- **Teardown:** close the Gemini STT socket with the session; do not leak it.

---

## Capabilities

### New Capabilities
- `livekit-gemini-voice-input`: host PTT in livekit → Gemini STT → `/agents/chat`
  → Supertonic to the room. Host-only (multi-driver deferred).

### Modified Capabilities
- `livekit-direct-audio` (FEAT-256): adds the input half (output already shipped).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `handlers/agent_voice.py` / `clients/live.py` | modifies | add an STT-only mode (transcribe input, suppress Gemini response) |
| Front `voice-session.svelte.ts` | modifies | in livekit, open Gemini STT WS on PTT; on final transcription → existing `handleSend` |
| Front `AgentVoiceChat.svelte` | modifies | re-enable PTT for livekit (host); `canPushToTalk` |
| FEAT-256 `RoomAudioPublisher` | uses | output path for the agent answer |

**Breaking changes:** none. ws-pcm/fullmode unchanged; livekit output (FEAT-256) unchanged.

---

## Code Context

### Verified Codebase References (2026-06-24, ai-parrot feat-256 checkout)
```python
# clients/live.py — GeminiLiveClient
#   input_audio_transcription=types.AudioTranscriptionConfig()   # live.py:666
#   emits input_transcription (user speech)                       # live.py:806-814
#   config knobs: response_modalities, enable_input_transcription,
#                 enable_output_transcription                      # live.py:722
# handlers/agent_voice.py — the /ws/voice Gemini handler (ws-pcm transport)

# Front (navigator-frontend-next) voice-session.svelte.ts:
#   _startMicWsPcm() + /pcm-worklet.js  → mic PCM16 16kHz capture (reuse)
#   transcription handling + pendingUserId accumulation (already shipped)
#   handleSend livekit branch → streamChatWithAgent (/agents/chat)
#   FEAT-256: RoomAudioPublisher publishes the agent answer to the room
```

### Does NOT Exist (Anti-Hallucination)
- ~~an STT-only mode on the Gemini voice path~~ — to be added (Gemini currently
  runs full-duplex in ws-pcm). The knobs exist (`response_modalities` etc.).
- ~~real-time mic STT inside the LiveKit room~~ — not present (voice-native deleted,
  FEAT-249). This feature uses the Gemini WS for STT, not the room.

---

## Parallelism Assessment
- **Internal parallelism**: Low — backend STT-only mode + front PTT wiring are coupled.
- **Cross-feature independence**: builds directly on FEAT-256 (must land first).
- **Recommended isolation**: `per-spec`.

---

## Open Questions
- [ ] **STT-only config**: exact Gemini Live setting to transcribe input WITHOUT generating a spoken response (set `response_modalities` minimal? disable output?) — *Owner: implementer (verify against `google-genai`)*.
- [ ] **Partial vs final**: route only the final `input_transcription` to `/agents/chat`, or show partials as a live hint? *Default: send on final; show partials as "listening…".* — *Owner: implementer*.
- [ ] **Barge-in**: should the host's PTT flush the in-room Supertonic audio mid-answer? *Default: yes.* — *Owner: implementer*.
- [ ] **Multi-driver (phase 2)**: several participants talking + turn arbitration — separate feature (revisit Option C / LiveKit Agents then). — *Owner: team lead*.
