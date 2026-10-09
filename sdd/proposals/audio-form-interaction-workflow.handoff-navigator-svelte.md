<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->

# Handoff brief — hands-free audio form renderer (navigator-svelte, Svelte 5)

**From:** ai-parrot — `sdd/proposals/audio-form-interaction-workflow.brainstorm.md` (FEAT-ID to be reserved by `/sdd-spec`)
**For:** a Claude Code session run **inside** the `navigator-svelte` repository
**How to use:** open a session there and run that repo's own `/sdd-proposal` (or `/sdd-brainstorm`) with this file as the source. navigator-svelte has its own commands, templates and CLAUDE.md — do not reuse ai-parrot's.
**Prepared:** 2026-10-10. Read-only research on ai-parrot `dev @ b288daa72`; nothing in navigator-svelte was read or modified from here — every navigator-svelte path below is **unverified** and must be located there first.

---

## 1. What the frontend must deliver

A **Svelte 5 (runes) audio-first, hands-free renderer** for FormBuilder forms that talks to the ai-parrot audio-form WebSocket (protocol v2, additive over v1) and lets a user complete a whole form without touching the screen, while keeping the existing visual controls as cues and fallbacks.

Core pieces (names are suggestions; follow the repo's conventions):

| Piece | Responsibility |
|---|---|
| `VoiceFormSession` (`.svelte.ts` class, `$state`) | State machine `idle → connecting → prefetching → asking{listening|recording|transcribing|confirming|visual} → plausibility → review{playing|awaiting|flagged} → submitting → complete|error|resuming`; owns the WS, the segment cache, the recorder and the hands-free policy |
| `VoiceSegmentCache` | `AudioContext` buffers keyed by `audio_segment.key`; plays `audio_keys[]` in order; `pause:<ms>` keys are timers; supports barge-in (stop playback when the user starts talking / presses record) |
| `VoiceRecorder` | Port of ai-parrot's `packages/ai-parrot-server/ui/src/lib/utils/voice-recorder.ts` (MediaRecorder, webm → ogg → mp4 fallback). **One complete container per answer**, ≥ 256 bytes, Safari → mp4. Hands-free: auto-start when the last segment of a question ends; stop on `silence_ms` of VAD silence or `max_recording_seconds` |
| `VoiceFormShell` | Layout: progress (`position{index,total}`, sections), current question card, transcript live region, control bar |
| `VoiceQuestionCard` | Label, then hint after the pause (visual mirror of the narration), transcript in an `aria-live="polite"` region, confidence state |
| `VoiceControlCue` | Mounts the regular FormBuilder control for the field by `render_mode` / `ui_cue{control, focus, highlight, submit_via}`; uploader/date/etc. send `answer_payload`; a select renders `VoiceOptionList` |
| `VoiceOptionList` | Options with **ordinal badges that match what was narrated**; `answer_accepted.matched` highlights the option; `confirm_request.alternatives` shows a disambiguation strip |
| `VoiceConfirmBar` | For `confirm_request`: candidate text, "Sí / Repetir / Cambiar" by voice or buttons → `confirm_answer` |
| `VoiceReviewList` | `review_start.items`; per item play TTS or the recording (`audio_segment{kind: review}`), "Cambiar" button, **plausibility flag** (`flag{confidence, reason}`) with "Mantener / Cambiar"; Send button → `review_confirm{confirmed: true}` |
| `VoiceCommandHint` | Shows the available voice commands for the current phase (repeat / back / skip / help / stop / send / "cambiar la N") and the `command_ack` toast |
| `VoiceResumeBanner` | When a `session_id` exists in `localStorage` for this `form_uid`: offer resume → `start_session{resume_session_id}` |

Keyboard shortcuts (space = push-to-talk override, R = repeat, B = back, Esc = stop) and a **text fallback** (no microphone → typed `answer_text`, same session) are required.

---

## 2. Landing surface (to verify in navigator-svelte)

- The FormBuilder public form renderer and the formbuilder preview — the audio renderer must mount in both or the proposal must decide which first.
- `src/lib/api/ai-parrot.ts` — the existing direct client of ai-parrot (cited by `sdd/state/FEAT-430/handoff/navigator-svelte-brief.md` in ai-parrot); the WS URL is `${apiAiUrl}/api/v1/{tenant}/forms/{form_uid}/audio/ws` (tenant-qualified, FEAT-421 in ai-parrot).
- `src/lib/config.ts` — `apiAiUrl` from `PUBLIC_API_AI_URL`.
- `formbuilder/types/schema.ts` — the frontend mirror of `FormSchema` (ai-parrot `core/constraints.py:203` says `LogicGroup` is mirrored there). It must learn the new fields: `FormField.hint`, `FormField.llm_validation`, `FormSchema.voice`, `FormSchema.llm_validation`.
- The FieldSync copy of the A2UI renderer (ai-parrot `sdd/proposals/report-builder.brainstorm.md`) — prior art for mounting FormBuilder controls from a wire schema.

---

## 3. Backend contract (verified in ai-parrot; v2 items are the brainstorm's design, to be frozen by `/sdd-spec`)

**Endpoint and auth (v1, shipped):** `GET /api/v1/{tenant}/forms/{form_uid}/audio/ws` (`api/routes.py:493`). JWT either as a `Sec-WebSocket-Protocol` subprotocol or as the first text message `{"type": "auth", "token": "..."}` (`api/audio_ws.py:282-347`). Max message 10 MB. Binary frames are speech answers; the server sniffs the container (EBML/OggS/ftyp/RIFF); `< 256 bytes` → `EMPTY_AUDIO`.

**Protocol v1 (shipped, keep working):** client → `start_session, answer_text, <binary>, answer_selection, answer_payload, confirm_answer, skip_question, go_back, repeat_question, end_session, ping`; server → `session_started, question, transcription, confirm_request, answer_accepted, answer_rejected, form_complete, session_ended, error, pong` (`docs/audio-form-voice-modes.md` §7; §9.10 vanilla JS and §9.11 React clients are reference implementations this renderer supersedes).

**Protocol v2 (this feature, additive):**

| Direction | Message | Notes |
|---|---|---|
| C→S | `start_session{form_uid, locale, protocol_version: 2, prefetch: true, resume_session_id?}` | v1 clients omit `protocol_version` and get base64 `audio` in `question` |
| S→C | `session_started{protocol_version, sections[], review{mode, playback}, tts_mime, prefetch_count, max_recording_seconds, hands_free{auto_record, silence_ms}, plausibility{enabled}, warnings?}` | |
| S→C | `audio_segment{key, mime, bytes, kind: label\|hint\|options\|review\|system}` **+ one binary frame** | buffer by `key`; `tts_mime` is `audio/wav` for SuperTonic |
| S→C | `question{…v1…, field_uid, section{uid,title}, hint?, prompt?, position{index,total}, audio_keys[], ui_cue{control,focus,highlight,submit_via}, answer_modes[], options[{value,label,ordinal}], required, computed_default?}` | play `audio_keys` in order; `pause:<ms>` is a client timer |
| S→C | `command_ack{command}` | after a recognised voice command; the usual effect message follows (`question`, `review_start`, `session_ended`…) |
| S→C | `plan_updated{order, hidden, cleared, required_changed, hidden_by_cap}` · `section_enter{section_uid, title, audio_key}` · `question_skipped` · `answer_cleared{field_id}` | dependencies / sections |
| S→C | `review_start{items[{position, field_id, label, answer_text, has_audio, audio_key\|blob_ref, flag?{confidence, reason}}]}` → `review_item` → `review_prompt` | `flag` comes from the LLM plausibility batch |
| S→C | `plausibility_result{status: ok\|skipped, items{field_id: {plausible, confidence, reason}}, reason?}` | informational; never blocks |
| C→S | `review_confirm{confirmed: bool}` · `review_edit{field_id}` | Send button / "Cambiar N" |
| S→C | `validation_errors{errors, first_field_id}` | deterministic validator failed at submit; the server re-asks |
| S→C | `session_resumed{answers, phase, cursor, plan}` | after `start_session{resume_session_id}` |
| S→C | `form_complete{submission_id, stored_in, plausibility_summary}` | |

**Error codes:** `EMPTY_AUDIO`, `UNSUPPORTED_AUDIO`, `AUDIO_DECODE_ERROR`, `WRONG_FIELD`, `NO_MATCH`, `TOO_MANY_QUESTIONS`, `RESUME_FORBIDDEN`, `RESUME_UNAVAILABLE`, `RESUME_STALE`.

**HTTP (cross-cutting LLM validation, also for the visual renderer):** `POST /api/v1/{tenant}/forms/{form_uid}/validate` with `llm_validation: true` returns an additive `plausibility{field_id: {plausible, confidence, reason}}` block so the HTML renderer can show "Revisa la respuesta N" **before** submitting; `POST …/data` returns and persists the same block. Low confidence never changes the HTTP status.

---

## 4. Constraints inherited from the brainstorm (do not re-litigate)

- **Deterministic server loop.** Narration and matching are template/lexicon based; the only LLM step is the end-of-form plausibility batch, which is fail-open. Do not design UI that depends on the LLM being present (`plausibility.enabled` may be false, `status` may be `skipped`).
- **Prefetch is mandatory for v2.** Buffer every `audio_segment` before playing the first question; pauses are client timers; never request base64 audio when `protocol_version: 2`.
- **`extra="forbid"` on the server.** Send only documented keys; unknown keys are rejected.
- **`sensitive` questions** are never narrated in review ("[hidden]") and never sent to the LLM — mirror that in the UI (mask the transcript).
- **Hands-free is a client policy** signalled by `hands_free{auto_record, silence_ms}`: auto-open the microphone when the last segment of a question ends; end-of-speech by VAD + silence or `max_recording_seconds`. A push-to-talk override must always exist.
- **One container per answer.** Never stream partial chunks; the server transcribes whole files.
- **Session identity.** Persist `session_id` per `form_uid` in `localStorage` for resume; the server enforces one active session per user.
- **Commands can be disabled per field** by the author (`meta.voice.commands: off`); the `question` payload will carry the effective command set — render `VoiceCommandHint` from it, not from a static list.
- **Optimiser is staging-only**: `POST …/voice/optimize` returns proposals; applying them is a designer action through the regular field-update path.
- **`hidden_by_cap`** questions exist (per-form cap, required always included): decide how the UI offers "more questions" or informs the user.

---

## 5. Prior art to locate in navigator-svelte before speccing

- The FormBuilder renderer components and how a field control is mounted from the schema (needed by `VoiceControlCue`).
- Any existing microphone / MediaRecorder utility or voice feature (do not duplicate; ai-parrot's `voice-recorder.ts` is a portable reference).
- The FieldSync A2UI renderer copy (mounting pattern).
- Existing WebSocket clients and reconnection helpers.
- Accessibility conventions (live regions, focus management) already in the repo.

---

## 6. Suggested open questions for the frontend proposal

1. Where does the renderer mount first: public form page, formbuilder preview, or both?
2. Hands-free end-of-speech is **decided**: client-side VAD + `silence_ms`, server reports only `max_recording_seconds`. Open here: which VAD library (bundle size, Safari/Capacitor support) and the default `silence_ms`.
3. Default review playback: TTS read-back, the user's recording, or both?
4. How to present `hidden_by_cap` questions and the per-form cap?
5. Capacitor / mobile: MediaRecorder MIME support and background audio behaviour.
6. Should the visual (non-audio) renderer also consume the `plausibility` block from `POST …/validate` as inline warnings? (The backend supports it; the brainstorm recommends yes.)
7. Scope of `session_id` persistence (per device, per user, per form) and resume UX.

---

## 7. Coordination

navigator-svelte runs an independent SDD flow with its own FEAT numbering; this work needs **its own FEAT-ID there**. For backend asks, follow that repo's convention `sdd/BACKEND-REQUEST-<topic>.md` addressed to ai-parrot and citing the requesting FEAT/TASK. The protocol v2 message set is frozen by ai-parrot's `/sdd-spec audio-form-interaction-workflow`; request changes there before the backend spec is accepted.
