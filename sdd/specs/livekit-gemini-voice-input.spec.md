---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LiveKit Gemini Voice Input (host PTT → Gemini STT → agent)

**Feature ID**: FEAT-257
**Date**: 2026-06-24
**Author**: Juanfran
**Status**: draft
**Target version**: next

> Source brainstorm: `sdd/proposals/livekit-gemini-voice-input.brainstorm.md`.
> Builds on FEAT-256 (livekit-direct-audio, merged to dev).

---

## 1. Motivation & Business Requirements

### Problem Statement
After FEAT-256 the `livekit` transport has voice **output** (the ai-parrot agent
speaks into the shared LiveKit room via Supertonic; avatar optional) but its
**input is text-only** — Push-to-Talk is disabled. You cannot *talk* to the bot in
livekit. ws-pcm lets you talk but is a private 1:1 stream (no multi-viewer, no
in-room avatar). We want **voice input for the host** in the **shared room**: the
host pushes to talk, their speech is transcribed, the **ai-parrot agent** answers,
and the answer is **spoken into the room** so viewers also hear it.

### Goals
- Host PTT in `livekit` → **Gemini STT only** → text turn to `/agents/chat` (the
  real agent: tools/RAG) → response audio via Supertonic to the room (FEAT-256).
- Re-enable PTT in livekit for the host; barge-in on the in-room audio.
- Reuse the existing ws-pcm mic capture + the Gemini transcription path.

### Non-Goals (explicitly out of scope)
- **Gemini as the conversational brain** — Gemini is STT only; the agent answers.
  (Gemini-as-brain is ws-pcm, which is 1:1 and cannot broadcast.)
- **Multi-driver** (several participants talking + turn arbitration) — phase 2.
- No changes to ws-pcm or fullmode. No new STT engine; no LiveKit Agents worker.

---

## 2. Architectural Design

### Overview
In `livekit` mode, on PTT the frontend opens the **existing** Gemini voice
WebSocket (`/ws/voice`, `agent_voice.py` / `GeminiLiveClient`) in a new **STT-only**
mode (transcribe input, suppress Gemini's spoken response) and streams mic PCM
(reusing the ws-pcm `_startMicWsPcm` + pcm-worklet). On the **final**
`input_transcription`, the frontend routes the text to `/agents/chat` (the existing
livekit `handleSend` branch) → the agent answers → Supertonic publishes the answer
into the room (FEAT-256 `RoomAudioPublisher`). The LiveKit room carries audio
**out**; the Gemini WS carries STT **in**.

### Component Diagram
```
Host mic ─PTT→ pcm-worklet ──PCM16─→ /ws/voice (Gemini, STT-ONLY)
                                          │ input_transcription (final)
                                          ▼
                       handleSend(text) → /agents/chat  (ai-parrot agent: tools/RAG)
                                          │ response
                                          ▼
                       Supertonic → RoomAudioPublisher → LiveKit room  (viewers hear)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `handlers/agent_voice.py` / `clients/live.py` | modifies | add STT-only mode (transcribe, suppress spoken response) |
| `clients/live.py` `GeminiLiveClient` | uses | `input_audio_transcription` + `input_transcription` event |
| FEAT-256 `RoomAudioPublisher` | uses | output path for the agent answer |
| Front `voice-session.svelte.ts` | modifies | livekit: open Gemini STT WS on PTT; on final transcription → `handleSend` |
| Front `AgentVoiceChat.svelte` | modifies | re-enable PTT for livekit (`canPushToTalk`); barge-in |

### New Public Interfaces
```python
# Backend: an STT-only switch on the voice session (exact knob TBD — see Open Q).
# Conceptually: start_session(..., stt_only=True) → emits input_transcription,
#   does NOT generate a model audio/text response.
```

---

## 3. Module Breakdown

### Module 1 (BACKEND, ai-parrot): Gemini STT-only mode
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` +
  `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**: accept an `stt_only` flag on the voice session; configure
  Gemini Live to transcribe input (`input_audio_transcription`) but NOT produce a
  spoken/text response (no "double brain"); keep emitting `input_transcription`.
- **Depends on**: existing GeminiLiveClient.

### Module 2 (FRONTEND, navigator-frontend-next): livekit STT session on PTT
- **Path**: `src/lib/components/agents/voice/voice-session.svelte.ts`
- **Responsibility**: in `livekit` mode, on PTT open the Gemini STT WS in STT-only
  mode and stream mic PCM (reuse `_startMicWsPcm`/pcm-worklet + the
  `transcription`/`pendingUserId` accumulation). On final transcription, invoke the
  existing livekit text-turn path (`handleSend` → `streamChatWithAgent`).
- **Depends on**: Module 1.

### Module 3 (FRONTEND): re-enable PTT + barge-in
- **Path**: `src/lib/components/agents/voice/AgentVoiceChat.svelte`
- **Responsibility**: `canPushToTalk` allows livekit (host); flush the in-room
  audio on PTT start (barge-in).
- **Depends on**: Module 2.

### Module 4: Tests
- **Path**: ai-parrot unit tests (M1) + front unit tests (M2/M3).
- **Responsibility**: STT-only suppresses the response; final transcription routes
  to the agent turn; PTT enabled in livekit; barge-in flushes.

> Cross-repo: M1 lands in **ai-parrot** (its own worktree/PR); M2–M3 land in
> **navigator-frontend-next**. Decompose backend vs front tasks per repo.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_stt_only_no_model_response` | M1 | STT-only session emits input_transcription, NO model response |
| `test_stt_only_still_transcribes` | M1 | input_transcription still flows in STT-only |
| `livekit_ptt_opens_stt_session` | M2 | PTT in livekit opens the Gemini STT WS (mocked) |
| `livekit_final_transcription_routes_to_agent` | M2 | final transcription → handleSend → streamChatWithAgent |
| `ptt_enabled_in_livekit` | M3 | `canPushToTalk` true in livekit; barge-in flushes |

### Integration Tests
| Test | Description |
|---|---|
| `livekit_voice_input_end_to_end_mock` | PTT → STT (mock) → agent turn → answer published to room (FEAT-256 mock) |

---

## 5. Acceptance Criteria

- [ ] In livekit, the host can PTT; speech is transcribed via Gemini **STT-only**
      (Gemini does NOT answer).
- [ ] The **ai-parrot agent** answers (`/agents/chat`) and the answer is **spoken
      into the room** (FEAT-256) — viewers hear it.
- [ ] PTT is enabled in livekit (host); barge-in interrupts the in-room audio.
- [ ] ws-pcm and fullmode unchanged; no new STT engine / no LiveKit Agents worker.
- [ ] Backend + front unit tests pass; integration test passes.

---

## 6. Codebase Contract

> Verified against ai-parrot `dev` (post FEAT-256) + navigator-frontend-next `dev`, 2026-06-24.

### Verified (backend, ai-parrot)
```python
# clients/live.py — GeminiLiveClient
#   input_audio_transcription=types.AudioTranscriptionConfig()   # live.py:666
#   emits input_transcription (user speech)                       # live.py:806-814
#   config knobs: response_modalities, enable_input_transcription,
#                 enable_output_transcription                      # live.py:722
# handlers/agent_voice.py — the /ws/voice Gemini handler (ws-pcm transport today)
```

### Verified (frontend, navigator-frontend-next)
```typescript
// voice-session.svelte.ts
//   _startMicWsPcm() + /pcm-worklet.js  → mic PCM16 16kHz capture (reuse)
//   _handleVoiceMsg 'transcription' + pendingUserId accumulation (shipped)
//   handleSend livekit branch → streamChatWithAgent(agentId, {query, session_id, stream})
//   canPushToTalk = canTalk && mode !== "livekit"   ← relax to allow livekit (host)
// FEAT-256: RoomAudioPublisher publishes the agent answer to the room (output path)
```

### Does NOT Exist (Anti-Hallucination)
- ~~an `stt_only` mode on the Gemini voice path~~ — to be added (M1). Gemini runs
  full-duplex in ws-pcm today; the config knobs (`response_modalities` etc.) exist.
- ~~real-time mic STT inside the LiveKit room~~ — not present (voice-native deleted,
  FEAT-249). This feature uses the Gemini WS for STT, not the room.
- ~~Gemini as the conversational brain in livekit~~ — explicitly NOT this; the agent answers.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Reuse, don't duplicate: ws-pcm mic capture, the transcription accumulation, and
  the livekit text-turn (`handleSend`) all exist — wire them, don't rewrite.
- Async throughout; idempotent teardown of the STT socket with the session.

### Known Risks / Gotchas
- **Double brain**: Gemini MUST be STT-only — verify it does not also answer.
- **Two connections** in livekit (room out + Gemini STT in) — manage both lifecycles.
- **Cross-repo**: M1 (ai-parrot) and M2–M3 (front) ship separately; keep the
  contract (the `stt_only` flag + the `/ws/voice` protocol) stable across both.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` (Gemini Live) | (existing) | STT — already used by ws-pcm |

---

## 8. Open Questions
- [ ] **STT-only config**: exact Gemini Live setting to transcribe input WITHOUT a spoken response (minimal `response_modalities`? disable output transcription/audio?). — *Owner: implementer (verify vs `google-genai`)*.
- [ ] **Partial vs final**: route only the final `input_transcription` to `/agents/chat`; show partials as a "listening…" hint. *Default: send on final.* — *Owner: implementer*.
- [ ] **Barge-in**: PTT flushes the in-room Supertonic audio mid-answer. *Default: yes.* — *Owner: implementer*.
- [ ] **Multi-driver (phase 2)**: several participants + turn arbitration — separate feature. — *Owner: team lead*.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-24 | Juanfran | Initial draft from the brainstorm. Gemini STT-only + ai-parrot agent brain + Supertonic-to-room output (reuse FEAT-256). Host-only; multi-driver deferred. Cross-repo (backend M1 + front M2–M3). |
