---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [parrot-formdesigner, ai-parrot-integrations, ai-parrot-server, docs]
tags: [formdesigner, audio-form, tts, stt, websocket, voice, llm-validation, hands-free, navigator-svelte, migration]
---

# Brainstorm: Audio Form Interaction Workflow — turn-based voice forms, LLM-assisted answer plausibility, hands-free Svelte renderer

**Date**: 2026-10-10
**Author**: Jesus Lara (proposal + decisions) · Claude (codebase re-verification on `dev @ b288daa72`, 2026-10-10)
**Status**: accepted (all 16 open questions resolved with the owner on 2026-10-10)
**Recommended Option**: B — transport-agnostic `AudioFormSession` engine + thin WS adapter + `AnswerPlausibilityChecker` in a shared `SubmissionPipeline`
**Related**:
- `sdd/proposals/audio-form-interaction-workflow.proposal.md` — the source plan this brainstorm expands; its eight owner decisions are carried in verbatim (see Open Questions, resolved block).
- `sdd/specs/formdesigner-audio-renderer.spec.md` (**FEAT-224**, 8/8 tasks done) and `sdd/specs/audio-renderer-form.spec.md` (**FEAT-236**, completed) — the baseline this feature evolves. Several items promised there were never built (see Problem Statement).
- `sdd/specs/audio-ws-confirm-answer-deadlock.spec.md` (**FEAT-395**, completed) — the I/O-inside-transition deadlock that motivates the pure-engine design of Option B.
- **FEAT-234** `formdesigner-conditional-sections` (`RuleEvaluator`, 10/10 done) · **FEAT-186** `formdesigner-partial-saves` (`PartialSaveStore`) · **FEAT-457** `formbuilder-formschema-persistency` (per-form sinks) · **FEAT-458** `formdesigner-unknown-fields-capture` · **FEAT-488** `formfield-content-type` (`VoiceAnswerEnvelope`) · **FEAT-393** `formdesigner-field-uid` · **FEAT-188** `formdesigner-lifecycle-events` · **FEAT-183** `formregistry-multi-tenancy` · **FEAT-544** `a2ui-form-output-renderer` · **FEAT-081** / **FEAT-551** Telegram / Teams renderers (future reusers of the engine).
- `docs/audio-form-voice-modes.md` — protocol v1 reference (§7) and the vanilla-JS / React reference clients (§9.10, §9.11) the Svelte handoff supersedes.
- `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` — the frontend brief this brainstorm produces (pattern: `sdd/state/FEAT-430/handoff/navigator-svelte-brief.md`).

> Verification note: all `path:line` references below were re-read on `dev @ b288daa72` with `wikitoolkit` available (`wikitoolkit query` returned no existing LLM-validation page for formdesigner; `wikitoolkit ledger context` on the touched files reported no open issues). Paths are relative to `packages/parrot-formdesigner/src/parrot_formdesigner/` unless stated otherwise.

---

## Problem Statement

FEAT-224 and FEAT-236 shipped a working but minimal audio form: a flat question list over a WebSocket, TTS per question, whole-file STT per answer, a confidence gate, and a direct write to `FormSubmissionStorage`. Field users (accessibility, hands-busy data capture), form authors, data operators who read `form_data`, and the `navigator-svelte` frontend team are all blocked by the following, every item verified in code:

**Promised in FEAT-224/236 and never built**
- No per-field voice hint. `FormField` (`core/schema.py:65-143`) has `label`, `description`, `placeholder`, `meta`, but no `hint`; the handler narrates only `label` + "Options: …" (`api/audio_ws.py:1333`). `description`/`placeholder` are never spoken.
- `MAX_QUESTIONS = 10` is a module constant (`api/audio_ws.py:59`) that silently truncates the question list (`api/audio_ws.py:490`), required fields included.
- No resume: `AudioSessionState` (`audio/models.py:179-210`) is memory-only with an integer `current_index`; the `PartialSaveStore` that `setup_form_api` receives (`api/routes.py:202`) is never passed to the audio handler (`api/routes.py:483-491`).
- No voice→option matching: a binary answer on a PROMPT_SELECT question stores the raw transcript as the value without checking `options`.
- No sections / dependencies: `RuleEvaluator.resolve()` (`services/rule_evaluator.py:578`) is never called from the audio path; `depends_on` / `post_depends` are ignored, questions advance by `index += 1` in two duplicated methods (`api/audio_ws.py:1072`, `:1094`).
- `FormValidator` is injected (`api/audio_ws.py:147-158`) but never invoked. Submissions are stored with `is_valid` unverified.
- The spoken audio is discarded after transcription (`_accept_answer`, `api/audio_ws.py:1009` stores only the string); `blob_storage` is never wired into the audio handler.

**Additional bugs found**
- `_finish_session` (`api/audio_ws.py:1115-1160`) builds `FormSubmission(form_version="1", data={fid: a.value})` and calls `FormSubmissionStorage.store()` directly, bypassing `FormAPIHandler.submit_data` (`api/handlers.py:1498`): no FEAT-457 sinks (`api/handlers.py:1824-1830`), no FEAT-188 lifecycle events, no forwarder (`api/handlers.py:1887`), and `registry.get(..., tenant=None)` (`api/audio_ws.py:1138`) loses the tenant from the URL.
- MULTI_SELECT answers are stored as a comma-joined string (`api/audio_ws.py:595`).

**New requirements (owner, 2026-10-10)** — quoted from the invocation and the proposal:
1. Turn-based TTS→STT with per-field hints, pre-synthesised audio pushed over the WebSocket, visual cues, item-by-item option narration with voice selection, HTML fallbacks, persisted text+audio per answer, section/dependency awareness, a final review step, a deterministic runtime with templates, and an optional design-time LLM optimiser.
2. *"Un atributo de validación LLM-assisted, al final (antes de enviar un formulario) además de las validaciones existentes: enviar pregunta+respuesta a un LLM que puede validar con un grado de confidencia que la respuesta tiene sentido en base a la pregunta — para evitar que ruido o cualquier otra cosa haya captado lo que no es y se haya registrado como respuesta."* This is a **cross-cutting FormBuilder change**, not an audio-only one.
3. The spec must emit an artefact that lets the `navigator-svelte` project build a **Svelte 5, audio-first, hands-free renderer**.

Why now: FEAT-544 (A2UI) and the Telegram/Teams renderers are converging on a shared form runtime; the audio handler is the only renderer that still owns its own submit path, and every new audio requirement would deepen that fork.

---

## Constraints & Requirements

- **Deterministic runtime.** No LLM in the per-turn loop. The only LLM touch points are (a) the design-time hint optimiser and (b) the end-of-form plausibility batch, both optional and fail-open. Narration comes from templates.
- **Additive protocol.** Inbound Pydantic models use `extra="forbid"` (pattern in `core/schema.py:121`); a v1 client must keep working against a v2 server, and a v2 client must negotiate (`protocol_version`) before relying on `audio_segment` prefetch.
- **`parrot.voice.*` and `parrot.clients.*` stay optional.** `audio_ws.py:47-54` guards them under `TYPE_CHECKING`; `parrot-formdesigner` must import and run without `ai-parrot` installed (the `ai-parrot` extra is `pyproject.toml:53-54`). The plausibility checker is therefore a separate service that degrades to `skipped`.
- **STT is whole-file.** `AbstractTranscriberBackend.transcribe(audio_path, language)` (`packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py:39`) takes a `Path`; there is no streaming or `bytes` entry point. Moonshine is English-only and may return `confidence=None` (`transcriber/backend.py:59`, `moonshine_backend.py:33-35`).
- **SuperTonic TTS is WAV without SSML** (`tts/models.py:47`), so pauses are separate segments, never markup.
- **One tenant per URL** (`/api/v1/{tenant}/forms/{form_uid}/audio/ws`, `api/routes.py:493`); the audio submit must carry it.
- **Never truncate required fields; never narrate or send `sensitive` content** (today `sensitive` is derived: `field.field_type == FieldType.PASSWORD`, `renderers/audio.py:361`).
- **Plausibility check never blocks** (owner, Round 1): low confidence re-asks (audio) or flags (HTTP); LLM failure or absence ⇒ submit proceeds with an audit mark.
- **Plausibility input is text only**: label, description, hint, field type, options and the scalar answer. Never `sensitive` fields, never blobs or `data_url`, no cross-field context in v1 (owner, Round 2).
- **Owner decisions from the proposal** (do not re-litigate): WS-only prefetch; `FormField.hint` first-class; voice envelope in `data[field_id]` for every spoken answer; list-all-then-listen selectors; per-form DDL migration + legacy normalisation; voice-or-button review confirmation; resume, per-form cap, optimiser, handoff and migration all in scope.
- Existing `FormValidator.validate()` signature (`services/validators.py:221-229`) and `ValidationResult` (`services/validators.py:160-178`: `is_valid`, `errors`, `sanitized_data`, `extra_data`) are the deterministic gate; the plausibility report is **additive**, never folded into `errors`.

---

## Options Explored

### Option A: Evolve `api/audio_ws.py` in place (the FEAT-236 pattern)

Keep `AudioFormWSHandler` as the single owner of state, I/O and transitions. Add `hint`, matching, `RuleEvaluator` calls, review, resume, blob persistence, the plausibility batch and the command lexicon as new private methods and new message types inside the handler; copy the sink/event/forwarder logic from `submit_data` into `_finish_session`.

✅ **Pros:**
- Smallest conceptual change; the existing fixtures (`tests/formdesigner/test_audio_ws_handler.py`, `test_audio_integration.py`) keep their shape.
- No new package layout to review.

❌ **Cons:**
- The handler is already 1 467 lines with two copies of advance (`:1072`, `:1094`) and awaits inside transitions — the exact structure that produced the FEAT-395 deadlock. Review + re-planning + resume + commands push it past 2 500 lines.
- Untestable without a WebSocket; every new rule needs an `aiohttp` test client.
- The submit bypass is "fixed" by copying ~90 lines of `handlers.py:1818-1909`, which then drift.
- Nothing is reusable by the Telegram/Teams renderers or a future A2UI voice surface.
- The plausibility checker would end up as a handler method, so the HTTP path could not share it.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp>=3.9` | WS transport | already a dependency (`pyproject.toml:35`) |
| `jinja2>=3.1` | narration templates | already a dependency (`pyproject.toml:41`) |
| `difflib` (stdlib) | fuzzy option matching | `rapidfuzz` optional if importable |

🔗 **Existing Code to Reuse:**
- `api/audio_ws.py` — everything, extended.
- `api/handlers.py:1818-1909` — copied into `_finish_session`.

---

### Option B (recommended): Transport-agnostic `AudioFormSession` engine + thin WS adapter + shared `SubmissionPipeline` with `AnswerPlausibilityChecker`

Split the audio runtime into pure components with no I/O, and make the WebSocket handler an adapter that decodes frames, calls `engine.handle(event) -> list[Outbound]`, performs the I/O the outbound list asks for (synthesise, store blob, persist snapshot) and encodes replies. Extract the HTTP submit tail (`handlers.py:1818-1909`) into `services/submission_pipeline.py` so both HTTP and the engine run validation → plausibility → sink/generic storage → events → forwarder → partial cleanup through one code path.

Proposed layout (new unless marked *modify*):

```
core/schema.py                    modify: FormField.hint: LocalizedString | None; FormField.llm_validation: bool | None;
                                          FormSchema.voice: VoiceFormConfig | None; FormSchema.llm_validation: LLMValidationConfig | None
core/voice.py                     VoiceFormConfig (per-form voice block) + FieldVoiceMeta (parsed from meta["voice"])
core/llm_validation.py            LLMValidationConfig {enabled, threshold, on_error, model, timeout_s, max_fields}
core/voice_answer.py              modify: VoiceEvidenceEnvelope(VoiceAnswerEnvelope) with answer: Any, confidence, source,
                                          audio_mime, duration_ms, language, plausibility; helpers is_voice_envelope/unwrap_voice/wrap_voice
audio/models.py                   modify: UiCue, NarrationPlan, OptionMatch, PlausibilityVerdict; deltas on AudioQuestion/AudioAnswer/AudioSessionState
audio/events.py                   inbound/outbound Pydantic models discriminated by `type` (protocol v2)
audio/planner.py                  QuestionPlanner: manifest + RuleEvaluator → visible plan, cap, cleared, next cursor
audio/option_matcher.py           deterministic match_option() + per-locale lexicon (ordinals, yes/no, conjunctions)
audio/commands.py                 classify_command(transcript, locale) → VoiceCommand | None (repeat/back/skip/help/stop/next/send/change N)
audio/option_refiner.py           OptionRefiner protocol + optional LLM impl (AbstractClient), confirm-only, off by default
audio/narration/{engine,lexicon}.py + templates/{en,es}/narration.yaml   Narrator (Jinja2 ImmutableSandboxedEnvironment)
audio/segments.py                 AudioSegmentCache + synthesis (moves _presynthize_to_cache/_synthesize/_auto_synthesize_cached)
audio/engine.py                   AudioFormSession: handle(event) -> list[Outbound]; phases below
audio/session_store.py            AudioSessionStore over PartialSaveStore's Redis client (resume snapshots)
audio/recordings.py               put/delete recordings via AbstractBlobStorage
services/plausibility.py          AnswerPlausibilityChecker(client) .check(form, scalars, *, locale, fields) -> PlausibilityReport  [cross-cutting]
services/submission_pipeline.py   SubmissionPipeline.submit(...) extracted from handlers.py:1818-1909; runs validator → plausibility → storage
services/validators.py            modify: unwrap→validate→rewrap for envelopes on any field answered by voice
services/sinks/mapper.py, postgres_table.py   modify: JSONB DDL/INSERT for voice-envelope columns
api/audio_ws.py                   modify → adapter (~300 lines): auth, tenant, decode JSON/binary, engine.handle(), encode, I/O
api/handlers.py, api/routes.py    modify: submit_data and validate use SubmissionPipeline / checker; `llm_validation` opt-in on POST …/validate;
                                          POST …/voice/optimize; pass blob_storage/partial_store/client to the audio adapter
tools/edit_toolkit.py             modify: `hint` and `llm_validation` in update_field; propose_voice_hints
renderers/audio.py                modify: section/hint/ui_cue/narration/answer_modes on AudioQuestion
renderers/{html5,jsonschema,adaptive_card,a2ui}.py   modify: expose `hint` (x-hint / <small class="hint">)
migrations/009_voice_envelope_form_data.{sql,py}, 010_voice_envelope_report.py   (package root: packages/parrot-formdesigner/migrations/)
docs/audio-form-voice-modes.md    modify: protocol v2 + plausibility + commands
```

✅ **Pros:**
- Every requirement becomes a pure, unit-testable component (`planner`, `option_matcher`, `commands`, `narration`, `plausibility`) with no WebSocket in the test.
- The engine never awaits inside a transition: `(state, event) → (state', outbound[])`. The FEAT-395 class of deadlock becomes structurally impossible.
- Fixes the submit bypass, the lost tenant, the PROMPT_SELECT raw-transcript bug and the MULTI_SELECT string once, for every channel, by routing audio through `SubmissionPipeline`.
- The plausibility checker lives in the pipeline, so HTML, A2UI, Telegram/Teams and audio all get the same cross-cutting LLM gate from one implementation, while `FormValidator` stays deterministic and `ai-parrot`-free.
- Engine + events are reusable by the Telegram/Teams renderers and by a future A2UI voice surface (Option C's convergence path).

❌ **Cons:**
- Larger diff and a new sub-package to review.
- Extracting ~90 lines of HTTP submit into `SubmissionPipeline` touches the hot path; needs its own task with parity tests against the existing `submit_data` fixtures.
- Two schema blocks (`voice`, `llm_validation`) widen `FormSchema`; the frontend form designer must learn them (handled in the handoff).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jinja2>=3.1` | narration templates (`ImmutableSandboxedEnvironment`, `StrictUndefined`) | already a dependency (`pyproject.toml:41`) |
| `difflib` (stdlib) | fuzzy option / command matching | `rapidfuzz` used only if importable (never a hard dep) |
| `unicodedata` (stdlib) | NFKD + casefold normalisation of transcripts | — |
| `redis>=4.5` | resume snapshots | existing extra (`pyproject.toml:61-62`), no-op without Redis like `PartialSaveStore` |
| `asyncpg` | migrations 009/010 | pattern of `migrations/003_migrate_form_data.py` |
| `ai-parrot>=1.2.1` (`AbstractClient.ask(structured_output=…)`) | plausibility batch + optional refiner/optimiser | optional extra (`pyproject.toml:53-54`); `StructuredOutputConfig` in `parrot/models/outputs.py:59` |
| `pydantic>=2` | events, configs, verdicts | already used throughout |

🔗 **Existing Code to Reuse:**
- `services/rule_evaluator.py:555-598` — `RuleEvaluator.resolve()` drives the planner.
- `services/partial_saves.py:24-66` — `PartialSaveStore` (Redis client, TTL, merge-only `save`) backs resume.
- `services/blob_storage.py:55-170` — `BlobMetadata` (deterministic `blob_id`) + `AbstractBlobStorage.put/get/delete` for recordings.
- `services/validators.py:200-345` — `FormValidator.validate()` stays the deterministic gate; `:542-548`, `:613-634` envelope acceptance to generalise.
- `api/handlers.py:197-215` — `_get_llm_client()` (GoogleGenAI default) feeds the checker and optimiser; `:1818-1909` becomes `SubmissionPipeline`.
- `api/handlers.py:1004` — `POST …/validate` dry-run gains the `llm_validation` opt-in.
- `renderers/audio.py:95-130` (`classify_voice_mode`), `:131-216` (synth fallback), `:277-390` (`split_into_questions`, GROUP expansion).
- `api/audio_ws.py:71-100` (`_sniff_audio_suffix`), `:282-347` (auth), `:1237-1330` (synthesis helpers) — moved, not rewritten.
- `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:23,124,186,213` — `VoiceSynthesizer.synthesize`, `get_shared_synthesizer`, `close_shared_synthesizers`.
- `packages/ai-parrot/src/parrot/clients/base.py:1817-1826` — `AbstractClient.ask(..., structured_output=type | StructuredOutputConfig)`.
- `packages/ai-parrot-server/ui/src/lib/utils/voice-recorder.ts:12,35,68` — `RecordedVoiceNote`, `isVoiceRecordingSupported()`, `VoiceRecorder` to port into navigator-svelte.

---

### Option C (unconventional): Audio form as an A2UI / linked-surfaces voice surface

Model the audio session as an A2UI surface (`renderers/a2ui.py`, FEAT-544) extended with a voice primitive, driving questions as surface updates and answers as A2UI actions; plausibility and commands become surface actions.

✅ **Pros:**
- One renderer family for visual and voice; visual cues come for free as surface components.
- Plausibility flags are a natural "notice" component.

❌ **Cons:**
- A2UI v1.0 has no voice primitive; `renderers/a2ui.py:238` degrades AUDIO to a `notice`. The whole voice vocabulary would have to be invented inside A2UI first.
- A2UI actions are request/response JSON (`api/a2ui_wire.py`), not a stream with binary frames — the WebSocket would still be needed underneath.
- `ai-parrot` is optional for `parrot-formdesigner`; this would make the audio form depend on `parrot.outputs.a2ui.runtime`.

📊 **Effort:** Very High — rejected for v2; recorded as a convergence target: Option B's `audio/events.py` can later be lowered into A2UI envelopes without touching the engine.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot` (`parrot.outputs.a2ui.runtime`) | envelopes, error codes | would become a hard dependency |

🔗 **Existing Code to Reuse:**
- `renderers/a2ui.py`, `api/a2ui_wire.py` — FEAT-544 dual-wire branch in `submit_data` / `validate` (`api/handlers.py:1013-1044`).

---

## Recommendation

**Option B** is recommended because:

- The deadlock history (FEAT-395) is a structural property of Option A, not a bug that was fixed: awaiting I/O inside transitions in a 1 467-line handler. Option B's invariant — the engine never performs I/O — makes the class of defect unreachable and lets every new rule (planner, matcher, commands, review, resume) be tested as a pure function.
- The owner's cross-cutting requirement (LLM-assisted plausibility "además de las validaciones existentes", on every channel) is only cheap if there is one submit path. Option B creates that path (`SubmissionPipeline`) and fixes four verified bugs (bypassed sinks/events/forwarder, lost tenant, raw transcript on PROMPT_SELECT, comma-joined MULTI_SELECT) as a side effect. Option A would implement the checker twice.
- Option C's convergence is real but premature: A2UI has no voice primitive and `ai-parrot` is optional for formdesigner. B keeps the door open by isolating the protocol in `audio/events.py`.

What we trade: a larger diff, a parity-test task for the extracted submit tail, and two new typed blocks on `FormSchema`. The parity task is the price of fixing the bypass properly; the schema blocks follow the `events` / `persistence` precedent (`core/schema.py:465`, `:473`) that the frontend already consumes.

---

## Feature Description

### User-Facing Behavior

**Turn-by-turn (audio channel, protocol v2)**

1. `start_session{form_uid, locale, protocol_version: 2, prefetch: true, resume_session_id?}` → `session_started{protocol_version: 2, sections[], review: {mode, playback}, tts_mime, prefetch_count, max_recording_seconds, hands_free: {auto_record, silence_ms}, plausibility: {enabled}, warnings?}` → a batch of **`audio_segment`** messages (JSON header `{key, mime, bytes, kind: label|hint|options|review|system}` followed by one binary frame; no base64) for every question of the initial plan plus system phrases. The client buffers by `key`.
2. `question{…v1 keys…, field_uid, section{uid, title}, hint?, prompt?, position{index, total}, audio_keys: ["q:<uid>:label", "pause:600", "q:<uid>:hint"], ui_cue{control, focus, highlight, submit_via}, answer_modes[], options[{value, label, ordinal}], required (dynamic), computed_default?}`. Narration order: label → client-side pause → bridge phrase ("Sugerencia:") → hint (or `description` when no hint). Base64 `audio` is sent only when the client asked `prefetch: false` (v1 compatibility).
3. **Hands-free commands.** Any transcript is first classified against the per-locale command lexicon (repeat / back / skip / help / stop / next / send / "cambiar la N"). A match emits `command_ack{command}` followed by the same effect v1 produced for `repeat_question` / `go_back` / `skip_question` / `end_session`. Non-commands continue to step 4. The client starts recording automatically when the question's last segment ends (VAD + silence) — a client policy signalled by `hands_free`.
4. VOICE: binary frame → `transcription{text, language, confidence}` → confidence gate → `answer_accepted{value, blob_ref?, matched?}`.
5. PROMPT_SELECT: segments `q:<uid>:options` are played item by item with ordinals; the microphone opens after the last; the transcript goes through the matcher → `answer_accepted{matched{value, label, method, score}}` (UI marks the option), `confirm_request{candidate, alternatives}` or `answer_rejected{code: NO_MATCH}` + one re-enumeration. `answer_selection` stays canonical and always available.
6. VISUAL_FALLBACK: `fallback_html` + `ui_cue{control: uploader|date|…, focus, highlight}` + bridge phrase ("Usa el control resaltado…"); `answer_payload` as today; files go through `blob_storage`.
7. Sections and dependencies: after each `answer_accepted` the planner re-runs `RuleEvaluator.resolve(form, unwrap(answers))` and emits `plan_updated{order, hidden, cleared, required_changed, hidden_by_cap}`; `question_skipped` / `answer_cleared` (and blob deletion) follow `cascade_clear`; `section_enter{section_uid, title, audio_key}` on section change; `go_back{to_field_id?}` works on the effective plan; `computed` read-only fields are narrated as statements and auto-accepted.
8. **Review.** `review_start{items[{position, field_id, label, answer_text, has_audio, audio_key|blob_ref, flag?}]}`. Before the items are read, the engine runs the **plausibility batch** (step 9). Then `review_item` per entry (TTS "Pregunta N: … Respuesta: …" or the recording via `audio_segment{kind: review}`; `sensitive` read as "[hidden]"), then `review_prompt` "¿Está todo correcto?". The user answers by voice ("sí / ok / enviar", lexicon) or presses Send → `review_confirm{confirmed: true}`; "cambiar la N" → `review_edit{field_id}` → the question → back to review.
9. **LLM-assisted plausibility (cross-cutting).** When `llm_validation` is enabled for the form and at least one eligible field has an answer, the engine emits `plausibility_check{fields}` and the adapter calls `AnswerPlausibilityChecker.check()` once with every eligible (question, answer) pair. Result → `plausibility_result{status: ok|skipped, items: {field_id: {plausible, confidence, reason}}, model?, reason?}`. Items with `confidence < threshold` get `flag: {confidence, reason}` in the review and a narrated prompt: "La respuesta a la pregunta N podría no corresponder: dijiste «…». ¿Quieres cambiarla?" Saying "cambiar" re-asks; saying "no / está bien" keeps it. Flags never block `review_confirm`. When the user edits answers, only the changed fields are re-checked (one delta batch); a field is flagged at most once per answer version.
10. `review_confirm` → `SubmissionPipeline.submit()` → `form_complete{submission_id, stored_in, plausibility_summary}`. If `FormValidator` fails, `validation_errors{errors, first_field_id}` returns to that question with `return_to_review`.
11. `start_session{resume_session_id}` → `session_resumed{answers, phase, cursor, plan}` + prefetch + current question or review; errors `RESUME_FORBIDDEN | RESUME_UNAVAILABLE | RESUME_STALE`.

**HTTP / HTML / A2UI channels (cross-cutting part only)**

- `POST /api/v1/{tenant}/forms/{form_uid}/data` runs the deterministic validator, then the plausibility batch when the form enables it, and returns an **additive** `plausibility` block alongside the existing response; the report is persisted in `FormSubmission.context["llm_validation"]` and, for spoken answers, inside each envelope. Low confidence never changes the HTTP status.
- `POST /api/v1/{tenant}/forms/{form_uid}/validate` accepts `llm_validation: true` (opt-in, body or query) and returns the same `plausibility` block so an HTML/Svelte renderer can warn **before** submitting ("Revisa la respuesta 3: …").
- Form authors toggle it per form (`llm_validation.enabled`) and per field (`FormField.llm_validation: true|false|null` → inherit), from the designer or `EditToolkit.update_field`.

### Internal Behavior

**Models**
- `FormField.hint: LocalizedString | None` (first-class); `FormField.llm_validation: bool | None` (None = inherit the form default); `meta["voice"]` → `FieldVoiceMeta{prompt, enumerate: auto|always|never|count_only, confirm: auto|always|never, pause_ms, ui_cue, match_threshold, skip_in_review}` parsed with `extra="ignore"` + warning; `meta["voice_mode"]` is preserved.
- `FormSchema.voice: VoiceFormConfig | None` (typed block, owner decision) — `{enabled, max_questions=10|None, hint_pause_ms=600, enumerate_options, stt_confirm_threshold=0.6, option_match_threshold=0.8, review: always|never|ask, review_playback: tts|recording|both, store_recordings, resume_ttl_seconds, llm_refine_options=False, commands: on|off, hands_free: {auto_record, silence_ms}, tts_backend, tts_voice, max_recording_seconds=60}`. Session config may only tighten the form config.
- `FormSchema.llm_validation: LLMValidationConfig | None` — `{enabled=False, threshold=0.7, on_error: skip|block = skip, model: str | None, timeout_s=8, max_fields=50, exclude_field_types=[PASSWORD, HIDDEN, …]}`. Typed block (owner decision), same precedent as `events` / `persistence`. `model=None` uses the handler's injected client (`_get_llm_client()`); a per-form `model` string overrides it.
- `VoiceEvidenceEnvelope(VoiceAnswerEnvelope)` with `answer: Any`, plus `confidence, source, audio_mime, duration_ms, language, plausibility: {confidence, reason} | None`; FEAT-488's `answer: str` on TEXT stays valid.
- `AudioQuestion` += `section_uid, section_title, subsection_title, hint, prompt, narration, ui_cue, answer_modes, voice_meta, llm_validation`; `AudioAnswer.value: Any` (list for MULTI_SELECT, bool for BOOLEAN) += `blob_ref, audio_mime, audio_bytes_len, duration_ms, matched, stt_language, answered_at, version`; `AudioSessionState`: `cursor: field_id`, `history`, `plan`, `phase: idle|asking|confirming|plausibility|review|review_editing|submitting|complete|aborted`, `return_to_review`, `review_cursor`, `resolution`, `tenant`, `locale`, `submission_id` (pre-generated), `protocol_version`, `plausibility: PlausibilityReport | None`.

**State machine** (engine, pure): CONNECTED → PLANNING → ASKING(cursor) → ACCEPTING → [CONFIRMING] → re-plan → next | PLAUSIBILITY → REVIEW → (review_edit → ASKING → PLAUSIBILITY(delta) → REVIEW) → SUBMITTING → validate → errors → ASKING | COMPLETE. Invariant: `handle(state, event) -> (state', outbound[])`; every I/O (synthesise, transcribe, blob put/delete, snapshot save, plausibility call, submit) is an `Outbound` request the adapter fulfils and feeds back as an event. The planner's cursor is the first visible field without an accepted answer; the cap applies to the visible plan but always keeps required fields (`required_exceeds_cap` warning, `hidden_by_cap` list).

**Commands** (`audio/commands.py`, pure): normalise (NFKD, casefold, strip punctuation and fillers) → exact phrase match against the locale lexicon → bounded fuzzy (`difflib` ≥ 0.9). Precedence: in PROMPT_SELECT an exact option match beats a command; in VOICE text fields a command must be the whole utterance (≤ 4 tokens); `meta.voice.commands: off` disables commands on a field (owner decision); a lexicon test enumerates command/option-label collisions per locale. Phases: ASKING, CONFIRMING, REVIEW. Unknown short utterances in REVIEW → `review_prompt` repeat, never a silent accept.

**Narration**: `audio/narration/templates/<locale>/narration.yaml` (Jinja2 values in an `ImmutableSandboxedEnvironment`, `StrictUndefined`), keys `question, question_with_prompt, hint_bridge, options_intro, option_item, options_count_only, boolean_prompt, required_mark, confirm_readback, confirm_option, no_match, required_reject, skipped, section_intro, computed_statement, review_intro, review_item, review_item_skipped, review_all_correct, review_edit_ack, plausibility_flag, plausibility_keep, submitted, resume_welcome, command_ack_*`, plus a `commands:` lexicon section. Fallback `es-MX → es → en`; a conformance test asserts every locale defines every key. Author `meta.voice.prompt` is **not** Jinja: `str.format_map` over a whitelist `{label, hint, section, n, total}`. Pauses are `pause:<ms>` segments resolved by the client.

**Prefetch**: sequential synthesis per session (ONNX is not concurrent) of label/hint/options per question + `sys:*` phrases, keyed `(form_uid, version, locale, voice, hash(text))`, per-session cache + in-process LRU, bounded by `max_questions`; the rest lazily in `_send_question`. One shared synthesiser per process (`get_shared_synthesizer`) guarded by an `asyncio.Lock` per synthesis call (owner decision).

**Option matching** (`audio/option_matcher.py`, pure): normalise → exact value/label → ordinal/cardinal ("la segunda", "opción 3", "última") → yes/no (BOOLEAN) → numeric (LIKERT/NPS/RANKING) → unique `contains` → fuzzy `difflib` (≥ 0.8 accept; 0.6–0.8 `confirm_request`; < 0.6 `NO_MATCH`); multi: split on conjunctions, "todas / ninguna"; effective acceptance `stt_confidence(None → 1.0) × score ≥ threshold`. `OptionRefiner` (LLM, `_get_llm_client()`) only when `llm_refine_options` and the method was fuzzy/none, and its output always goes through `confirm_request`.

**Plausibility** (`services/plausibility.py`): `AnswerPlausibilityChecker(client: AbstractClient | None, *, config: LLMValidationConfig)`. `check(form, scalars, *, locale, fields: set[str] | None = None) -> PlausibilityReport{status: ok|skipped, reason?, model?, latency_ms, items: dict[field_id, PlausibilityVerdict{plausible: bool, confidence: float, reason: str}]}`. Eligibility: field enabled (`field.llm_validation` if not None else `form.llm_validation.enabled`), answered (non-empty scalar), not `read_only`/computed, not HIDDEN/PASSWORD/`sensitive`, type not excluded, ≤ `max_fields` (required first). Prompt per item: resolved `label`, `description`, `hint`, `field_type`, `options` labels (SELECT family), and the scalar answer as text (lists joined, booleans localised). **No blobs, no `data_url`, no cross-field context.** One `client.ask(prompt, structured_output=PlausibilityBatch)` call under `asyncio.wait_for(timeout_s)`; any exception, `client is None`, or an unparsable result ⇒ `status: skipped` with `reason` (fail-open). `on_error` is implemented in both modes (owner decision): `skip` (default) proceeds with `status: skipped`; `block` makes LLM unavailability/timeout a submit failure — HTTP `503`-class response with `plausibility.status = "blocked"`, audio `error{code: PLAUSIBILITY_UNAVAILABLE}` and the review stays open for retry. `block` governs only LLM *failure*; low confidence never blocks in either mode. `FormValidator` is **not** modified for this; the pipeline calls the checker after `validate()` succeeds. Verdicts are stored in `FormSubmission.context["llm_validation"]` (`{status, model, threshold, items}`) and, for spoken answers, as `plausibility` inside the envelope. Audio-channel reasons are narrated through `plausibility_flag`; HTTP returns them verbatim in the `plausibility` block.

**Audio persistence**: on accept (not on finish) `blob_storage.put(iter([bytes]), metadata=BlobMetadata(form_uid, form_id, field_uid, field_id, submission_id, tenant, content_type, size_bytes, blob_id=f"voice-{session_id}-{field_uid}"))` — the deterministic id means re-answering overwrites; pending (unconfirmed) audio stays in memory; `blob_storage=None` or `store_recordings=False` ⇒ `blob_ref=None` (never `data_url`); delete on `cascade_clear` and on `end_session` without submit; orphan cleanup by TTL is an operational gap covered by migration 010's report.

**Submit** (`SubmissionPipeline.submit(form, data, *, tenant, user_id, locale, context, extra_data, auth_context, merge_session_id, llm_validation)`): scalars = `unwrap(answers)` → `FormValidator.validate(form, scalars, locale=…, auth_context=…)` (re-runs `RuleEvaluator`, FEAT-458 unknown keys) → errors ⇒ `validation_errors` (never store `is_valid=False` from audio) → plausibility (if enabled and not already attached by the audio engine) → rewrap: every field with `source == "speech"` ⇒ `{answer: <sanitised scalar>, blob_ref, confidence, source, audio_mime, duration_ms, language, plausibility}` → `FormSubmission(submission_id=session.submission_id, form_version=form.version, tenant, user_id, locale, context={channel: "audio", session_id, stt_backend, tts_backend, protocol_version: 2, llm_validation: {...}}, extra_data)` → sink-or-generic storage (FEAT-457 exclusivity preserved), lifecycle events (`dispatch`, `services/event_dispatcher.py`), forwarder with scalars + `voice_data`, partial cleanup → `form_complete{stored_in}`. The HTTP `submit_data` becomes a thin caller of the same pipeline (parity tests).

**Migration** (`packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql` + `009b/010_*.py`, pattern `003_migrate_form_data.py`): (a) FEAT-457 per-form tables: for every column whose field may carry an envelope, `ALTER TABLE … ALTER COLUMN <field_id> TYPE JSONB USING jsonb_build_object('answer', <field_id>)`, parametrised from `form_schemas.persistence`; the sink DDL map produces JSONB and `jsonb_columns` includes those fields (`services/sinks/postgres_table.py:322-331`); (b) `form_data.data`: legacy strings on fields declared `answer_envelope="voice"` → `{"answer": <str>, "blob_ref": null}` in batches, idempotent, `--dry-run`; (c) SQL function `fd_unwrap_voice(jsonb)` + view `form_data_scalar` for SQL consumers expecting scalars; (d) `010_voice_envelope_report.py`: envelope inventory, orphan `blob_ref`s (`--blob-url`), `--apply --downgrade` reversible. Readers to adapt with `unwrap_voice()`: `list_revisions`, forwarder, `prefilled` in HTML5/PDF renderers, Telegram/Teams renderers, `_row_to_submission` (re-fold on read). CSV/GSheet sinks receive the envelope JSON-serialised like ARRAY today (`services/sinks/mapper.py:209`); the rejected alternative (reserved `voice_data JSONB` sidecar) is kept in Open Questions.

**Resume**: scalar answers (key `field_uid`) go to the normal partial store (`save`; new `remove_keys` for `cascade_clear`) so a voice session can be finished in HTML (`/partial` + `merge_partials`); the cursor snapshot lives at `parrot:audio:{form_uid}:{session_id}` (`AudioSessionStore` reusing the `PartialSaveStore` Redis client/TTL): `phase, cursor, history, review_cursor, return_to_review, locale, config, blob_refs, answer_meta, plausibility, submission_id, user_id, tenant, saved_at, expires_at`. Autosave after each transition and in the WS `finally`. On resume: verify `user_id` and tenant (no existence oracle), re-resolve the form (drop unknown `field_uid`s, re-validate options), **re-plan** (never trust the saved `plan`), drop `pending`, reuse `session_id` (stable blob ids), one active session per user (`parrot:audio:active:{user_id}`); a stale plausibility report is discarded and re-run at review.

**Limits**: `max_questions` (default 10, `None` unlimited) on the visible plan with required always inside; `max_recording_seconds` reported to the client; prefetch cap; `llm_validation.max_fields`.

**Design-time optimiser**: `POST /api/v1/{tenant}/forms/{form_uid}/voice/optimize` (`_wrap_auth`) + `EditToolkit.propose_voice_hints`; input `{locale, fields?, style, max_hint_words}`; output `proposals[{field_uid, hint{locale}, prompt?, enumerate, llm_validation?, rationale, warnings}]` + `narration_preview`. **Staging only (owner decision)**: the endpoint never writes; the designer applies accepted proposals through the existing `update_field` path in `api/operations.py` (identity `field_uid`, If-Match version check, validation). Client `_get_llm_client()` with structured output. Includes a **deterministic matcher self-test** (label collisions ≥ 0.8) that runs without an LLM.

### Edge Cases & Error Handling

- No TTS available → text-only turns with the same `narration` payload; `audio_segment` batch is empty and `session_started.prefetch_count = 0`.
- STT fails → `AUDIO_DECODE_ERROR` and re-record; `confidence=None` (Moonshine) → weak gate, `stt_backend` audited in `context`.
- Plausibility: LLM missing / timeout / malformed JSON → `plausibility_result{status: skipped, reason}`, review proceeds unflagged, `context.llm_validation.status = "skipped"`. A model that returns a verdict for an unknown `field_id` is dropped with a warning. Confidence outside `[0, 1]` is clamped. The checker is never called with zero eligible fields.
- A transcript that is both an option and a command ("saltar" as an option label) → exact option wins in PROMPT_SELECT; the lexicon test enumerates collisions per locale.
- Disconnect during review → resume in `review`; disconnect during the plausibility call → the adapter drops the in-flight result, resume re-runs it.
- Form edited between sessions → `RESUME_STALE` / re-ask only the affected fields.
- GROUP children: `RuleEvaluator.resolve()` iterates `iter_all_fields()` (`services/rule_evaluator.py:598`), which does not recurse into GROUP children (`core/schema.py:477-489`; `iter_fields_recursive()` at `:490` does). The planner inherits the GROUP parent's visibility; the evaluator is **not** changed in this feature (owner decision) — a ledger issue tracks evaluating `iter_fields_recursive` separately.
- Memory: M concurrent sessions share one ONNX synthesiser behind a lock; prefetch is sequential per session.
- Sensitive fields are excluded from plausibility, narrated as "[hidden]" in review and never written to `context.llm_validation`.

---

## Capabilities

### New Capabilities
- `audio-form-interaction-workflow`: transport-agnostic `AudioFormSession` engine, protocol v2 (`audio_segment` prefetch, sections, review, commands), thin WS adapter.
- `formfield-hint`: first-class `FormField.hint` narrated after a pause and exposed by every renderer.
- `llm-assisted-answer-plausibility`: `FormSchema.llm_validation` + `FormField.llm_validation`, `AnswerPlausibilityChecker`, additive `plausibility` block on submit / validate, audio review flags. **Cross-cutting, all channels.**
- `hands-free-voice-commands`: per-locale deterministic command lexicon (`audio/commands.py`) and `command_ack`, `hands_free` session hints.
- `voice-answer-attachments`: recordings persisted through `AbstractBlobStorage` and referenced from `VoiceEvidenceEnvelope`.
- `audio-form-session-resume`: `AudioSessionStore` snapshots over the partial-save Redis client, cross-channel completion.
- `submission-pipeline-extraction`: `SubmissionPipeline` shared by HTTP, A2UI and audio (fixes the bypass).
- `form-data-voice-envelope-migration`: migrations 009/010 and the `fd_unwrap_voice` view.
- `audio-form-llm-optimizer`: design-time hint / prompt / `llm_validation` proposals.
- `audio-form-svelte-handoff`: the navigator-svelte brief (`…handoff-navigator-svelte.md`) the spec must list as a deliverable.

### Modified Capabilities
- `formdesigner-audio-renderer` (FEAT-224) and `audio-renderer-form` (FEAT-236): handler becomes an adapter; protocol v2 additive over v1.
- `formfield-content-type` (FEAT-488): `VoiceEvidenceEnvelope` subclass, envelope accepted on any voice-answered type.
- `formbuilder-formschema-persistency` (FEAT-457): JSONB columns for voice fields, `jsonb_columns` extension.
- `formdesigner-partial-saves` (FEAT-186): `remove_keys`, shared Redis client for `AudioSessionStore`.
- `a2ui-form-output-renderer` (FEAT-544): `validate` / `submit_data` A2UI branch flows through `SubmissionPipeline` and gains the `plausibility` block.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `core/schema.py` (`FormField`, `FormSchema`) | extends | `hint`, `llm_validation` on fields; `voice`, `llm_validation` typed blocks on the form. `FormField` is `extra="forbid"` (`:121`), so every consumer that builds `FormField` must learn the new keys; `FormSchema` has no `model_config` (pydantic default ignores unknown keys), so older readers tolerate the new blocks |
| `core/voice_answer.py` | extends | `VoiceEvidenceEnvelope(VoiceAnswerEnvelope)`; `answer: str` contract for TEXT unchanged |
| `core/voice.py`, `core/llm_validation.py` | new | typed config blocks |
| `audio/*` (engine, planner, matcher, commands, narration, segments, events, session_store, recordings) | new | pure components; the only I/O is in the adapter |
| `api/audio_ws.py` | modifies | becomes the adapter; v1 messages still accepted |
| `api/handlers.py` (`submit_data`, `validate`) | modifies | delegate to `SubmissionPipeline`; `llm_validation` opt-in on validate; `voice/optimize` endpoint |
| `api/routes.py` (`setup_form_api`) | modifies | pass `blob_storage`, `partial_store`, `client` to the audio adapter; mount optimize route |
| `services/submission_pipeline.py` | new | extracted from `handlers.py:1818-1909`; parity tests mandatory |
| `services/plausibility.py` | new | `AnswerPlausibilityChecker`; depends on optional `parrot.clients.base.AbstractClient` |
| `services/validators.py` | modifies | unwrap → validate → rewrap for envelopes on any voice-answered type (today TEXT/TEXT_AREA only, `:542-548`) |
| `services/sinks/mapper.py`, `postgres_table.py` | modifies | JSONB DDL + `jsonb_columns` for voice fields |
| `services/partial_saves.py` | extends | `remove_keys`; Redis client reused by `AudioSessionStore` |
| `services/submissions.py` | depends on | `context["llm_validation"]`, envelopes in `data`; readers use `unwrap_voice()` |
| `tools/edit_toolkit.py`, `api/operations.py` | extends | `hint`, `llm_validation` in `update_field`; `propose_voice_hints` |
| `renderers/{html5,jsonschema,adaptive_card,a2ui,pdf,telegram,teams}` | extends | expose `hint`; `prefilled` reads through `unwrap_voice()` |
| `packages/parrot-formdesigner/migrations/` | new | `009_*`, `010_*` |
| `parrot.voice.tts/transcriber` (ai-parrot-integrations) | depends on | unchanged API; shared synthesiser preferred |
| `parrot.clients.base.AbstractClient` (ai-parrot) | depends on | `ask(structured_output=…)`; **not modified** |
| `docs/audio-form-voice-modes.md` | modifies | protocol v2, plausibility, commands; §9.10/9.11 superseded by the Svelte handoff |
| navigator-svelte (external) | depends on | consumes protocol v2; its own FEAT via the handoff brief |

Breaking changes: none on the wire for v1 clients; `form_data.data` shape changes for voice fields after migration 009 (readers adapt via `fd_unwrap_voice` / `unwrap_voice()`). New optional dependency use only.

---

## Code Context

### User-Provided Code

No code was pasted. The owner's requirement text is quoted in the Problem Statement; the eight proposal decisions are reproduced in Open Questions (resolved block).

### Verified Codebase References — ai-parrot (`dev @ b288daa72`, paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`)

#### Classes & Signatures
```python
# core/schema.py
class UnknownFieldsPolicy(str, Enum): ...                                   # :51
class FormField(BaseModel):                                                 # :65
    model_config = ConfigDict(extra="forbid")                               # :121
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)                # :123
    field_id: str                                                           # :124
    field_type: FieldType                                                   # :125   (FieldType in core/types.py:16)
    label: LocalizedString                                                  # :126
    description: LocalizedString | None = None                              # :127
    placeholder: LocalizedString | None = None                              # :128
    required: bool = False                                                  # :129
    read_only: bool = False                                                 # :131
    options: list[FieldOption] | None = None                                # :133
    depends_on: DependencyRule | None = None                                # :135
    post_depends: list[PostDependency] | None = None                        # :136
    meta: dict[str, Any] | None = None                                      # :140
    content_type: str | None = None                                         # :141
    accept_content_types: list[str] | None = None                           # :142
    answer_envelope: Literal["voice"] | None = None                         # :143
class FormSubsection(BaseModel): fields: list[FormField]                    # :195, :221
SectionItem = Union[FormField, FormSubsection]                              # :226
class FormSection(BaseModel): fields: list[SectionItem]                     # :229, :254
def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]        # :267
class SubmitAction(BaseModel): ...                                          # :300
class FormSchema(BaseModel):                                                # :401
    # NOTE: FormSchema declares NO model_config → pydantic default extra="ignore"; extra="forbid" is on FormField (:121),
    #       FormSubsection (:215) and the :367 source model (:382). New top-level blocks are therefore ignored, not rejected, by older code.
    form_uid: uuid.UUID; form_id: str; version: str = "1.0"                 # :453-455
    description: LocalizedString | None; meta: dict[str, Any] | None        # :457, :461
    events: FormEventsConfig | None = None                                  # :465
    persistence: FormPersistenceConfig | None = None                        # :473   (core/persistence.py:226)
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP          # :475
    def iter_all_fields(self) -> Iterator[FormField]                        # :477   (does NOT recurse GROUP children)
    def iter_fields_recursive(self) -> Iterator[FormField]                  # :490

# core/voice_answer.py (FEAT-488)
class VoiceAnswerEnvelope(BaseModel):                                       # :13
    model_config = ConfigDict(extra="forbid")
    answer: str; blob_ref: str | None = None; data_url: str | None = None

# core/constraints.py
class LogicGroup(BaseModel)  # :193  (mirrors navigator-svelte formbuilder/types/schema.ts, :203)
class DependencyRule(BaseModel)  # :216
class PostDependency(BaseModel)  # :334

# services/validators.py
class ValidationResult(BaseModel):                                          # :160
    is_valid: bool; errors: dict[str, list[str]]; sanitized_data: dict[str, Any]
    extra_data: dict[str, Any] = Field(default_factory=dict)                # :174-177
class FormValidator:                                                        # :200
    def __init__(self) -> None                                              # :217  (no LLM client)
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en",
                       auth_context: AuthContext | None = None, location_vars: dict[str, Any] | None = None,
                       visit_context: dict[str, Any] | None = None) -> ValidationResult   # :221-229
    async def validate_field(...)                                           # :351
    @staticmethod
    def _is_voice_envelope_field(field: FormField) -> bool                  # :542-548  (TEXT/TEXT_AREA only)
    # envelope coercion: field.answer_envelope == "voice" → VoiceAnswerEnvelope.model_validate(value).model_dump()  # :629-634
    def validate_rules(self, form: FormSchema) -> list[str]                 # :1382

# services/rule_evaluator.py
class RuleResolution(BaseModel)                                             # :53   (visible, required, computed, cleared)
class RuleEvaluator:                                                        # :555
    async def resolve(self, form, answers, *, locale, location_vars, visit_context) -> RuleResolution   # :578
    # all_fields = list(form.iter_all_fields())                             # :598

# services/blob_storage.py
class BlobMetadata(BaseModel):                                              # :55
    blob_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")   # :93
class AbstractBlobStorage(ABC):                                             # :119
    async def put(self, stream, *, metadata: BlobMetadata) -> str           # :131
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]              # :158
    async def delete(self, blob_ref: str) -> None                           # :169
    # key = f"{prefix}{form_uid}/{field_uid}/{blob_id or uuid4}"            # :241-242

# services/partial_saves.py
class PartialSaveStore:                                                     # :24
    REDIS_KEY_PREFIX = "parrot:partial:"                                    # :50
    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None) -> None   # :52-55
    async def save(...)  # :67   async def get(...)  # :123   async def delete(...)  # :145

# services/submissions.py
class FormSubmission(BaseModel):                                            # :50
    submission_id: str; form_version: str; data: dict[str, Any]; is_valid: bool   # :93-101
    tenant: str | None = None; context: dict[str, Any] | None = None; extra_data: dict[str, Any] | None = None  # :108, :118-119
class FormSubmissionStorage:                                                # :122
    async def store(self, submission, *, tenant: str | None = None, ...) -> str   # :313-317

# services/sinks
def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]   # mapper.py:142
def _extract_value(data, column_name, field) -> Any                         # mapper.py:176  (json.dumps only for ARRAY, :209)
_DEFAULT_DDL_TYPE = "TEXT"                                                  # postgres_table.py:79
# jsonb_columns = {"context", "extra_data"} | {...}; non-str values json.dumps'd   # postgres_table.py:322-331

# services/forwarder.py / registry.py / event_dispatcher.py
class SubmissionForwarder: async def forward(self, outbound, submit) -> ...  # forwarder.py:36, :61
class FormRegistry: async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None   # registry.py:240, :976
from ..services.event_dispatcher import apply_schema_overrides, dispatch     # handlers.py:27

# api/handlers.py
class FormAPIHandler:
    def __init__(..., client: "AbstractClient | None" = None, submission_storage=None, forwarder=None, ...)   # :147-149
    def _get_llm_client(self) -> "AbstractClient | None"                     # :197-215  (lazy GoogleGenAIClient default)
    async def validate(self, request: web.Request) -> web.Response           # :1004  (POST …/validate dry-run; A2UI dual-wire :1013-1044)
    async def submit_data(self, request: web.Request) -> web.Response        # :1498
    # persistence sinks exclusive branch                                     # :1818-1830
    # forwarder: if form.submit.action_type == "endpoint" and self._forwarder   # :1887-1888
    # partial cleanup after merge                                            # :1900-1902

# api/routes.py
def setup_form_api(app, ..., blob_storage: "AbstractBlobStorage | None" = None, partial_store: "PartialSaveStore | None" = None,
                   synthesizer: "VoiceSynthesizer | None" = None, transcriber: "FasterWhisperBackend | None" = None,
                   token_validator: "TokenValidator | None" = None) -> None   # :192-205
# route f"{tp}/forms/{{form_uid}}/validate"                                  # :415
# AudioFormWSHandler(...) mounted at f"{tp}/forms/{{form_uid}}/audio/ws" when transcriber/token_validator given   # :473-496

# api/audio_ws.py
MAX_QUESTIONS = 10                                                           # :59
_MIN_AUDIO_BYTES = 256                                                       # :68
def _sniff_audio_suffix(data: bytes) -> Optional[str]                        # :71  (EBML/OggS/ftyp/RIFF)
class AudioFormWSHandler:                                                    # :102
    def __init__(self, registry: "FormRegistry", synthesizer: Optional["VoiceSynthesizer"], transcriber: Optional["FasterWhisperBackend"],
                 validator: "FormValidator", *, token_validator=None, submission_storage=None, max_msg_size=10*1024*1024, ...)   # :143-161
    async def _authenticate(...)                                             # :282  (Sec-WebSocket-Protocol :309-310; first "auth" message :324-330)
    async def _dispatch_text(...)                                            # :349  (handler table incl. "confirm_answer" :373)
    # questions = questions[:MAX_QUESTIONS]                                  # :490
    # value = ",".join(values)   (MULTI_SELECT)                              # :595
    async def _handle_confirm_answer(...)                                    # :637
    async def _handle_answer_audio(...)                                      # :691  (EMPTY_AUDIO :730, UNSUPPORTED_AUDIO :738, AUDIO_DECODE_ERROR :770, confirm_request :812)
    async def _accept_answer(...)                                            # :1009
    async def _advance_session(...)  # :1072     async def _advance_session_no_request(...)  # :1094
    async def _finish_session(...)                                           # :1115  (registry.get(..., tenant=None) :1138; FormSubmission :1141; store :1149; form_complete :1158)
    async def _send_question(...)                                            # :1167
    async def _synthesize(...)  # :1237     async def _auto_synthesize_cached(...)  # :1271
    def _narration_text(...)                                                 # :1333
    async def _presynthize_to_cache(...)                                     # :1414
# _audio_cache: dict[int, str] = {}                                          # :230

# audio/models.py
class VoiceMode(str, Enum)                                                   # :18   VOICE | PROMPT_SELECT | VISUAL_FALLBACK
class AudioSessionConfig(BaseModel):                                         # :38
    form_uid: str; locale: str = "en"; tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: Optional[str]; tts_mime_format: str = "audio/wav"; auto_advance: bool = True
    enumerate_options: bool = True; stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
class AudioQuestion(BaseModel):                                              # :72
    index: int; field_id: str; field_uid: uuid.UUID; field_type: str; label: str; description: Optional[str]
    required: bool; audio_prompt: Optional[bytes]; constraints: Optional[dict]; options: Optional[list[dict]]
    voice_mode: VoiceMode; render_mode: Literal["voice", "select", "visual"]; sensitive: bool
    fallback_html: Optional[str]; accept_content_types: Optional[list[str]]; answer_envelope: Optional[Literal["voice"]]
class AudioFormManifest(BaseModel)                                           # :128
class AudioAnswer(BaseModel):                                                # :153
    value: str; source: Literal["text", "speech", "selection"] = "text"; confidence: Optional[float] = None   # :173-175
class AudioSessionState(BaseModel):                                          # :179
    session_id: str; form_uid: str; user_id: str; current_index: int = 0
    answers: dict[str, AudioAnswer]; manifest: Optional[AudioFormManifest]; completed: bool; config: Optional[AudioSessionConfig]

# renderers/audio.py
_SKIP_FIELD_TYPES = frozenset({FieldType.HIDDEN})                            # :36
def classify_voice_mode(field: FormField) -> VoiceMode                       # :95   (meta["voice_mode"] override :109)
def build_audio_synthesizer(...)                                             # :131
async def synthesize_with_fallback(...)                                      # :164  (SuperTonic → Google → None)
def _resolve(value: LocalizedString | None, locale: str = "en") -> str       # :218
class AudioFormRenderer(AbstractFormRenderer):                               # :242
    def split_into_questions(self, form, ...)                                # :277  (form.iter_all_fields() :299; GROUP expansion :331)
    # sensitive = field.field_type == FieldType.PASSWORD                     # :361

# renderers/a2ui.py — AUDIO degraded to "notice" primitive                   # :238
# tools/edit_toolkit.py — class EditToolkit(AbstractToolkit) :63; async def update_field(...) :318
# tools/create_form.py — class CreateFormTool(AbstractTool) :348; self._client.ask(text, **ask_kwargs) :730
```

```python
# ai-parrot core — packages/ai-parrot/src/parrot/
class AbstractClient:                                                        # clients/base.py
    async def ask(self, ..., structured_output: Union[type, StructuredOutputConfig, None] = None, ...)   # :1817, :1826
    async def invoke(self, ..., structured_output: Optional[StructuredOutputConfig] = None, ...)          # :1904, :1909
class StructuredOutputConfig                                                 # models/outputs.py:59
class OutputFormat(Enum)                                                     # models/basic.py:12
class TokenValidator                                                         # core/ws_auth.py:44

# ai-parrot-integrations — packages/ai-parrot-integrations/src/parrot/voice/
class VoiceSynthesizer:                                                      # tts/synthesizer.py:23
    async def synthesize(self, text, *, language) -> SynthesisResult         # :124
async def get_shared_synthesizer(config: TTSConfig) -> VoiceSynthesizer      # :186
async def close_shared_synthesizers() -> None                                # :213
TTSConfig.backend: Literal["google", "elevenlabs", "openai", "supertonic", "polly"]   # tts/models.py:47
class AbstractTranscriberBackend(ABC):                                       # transcriber/backend.py:18
    async def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult   # :39  (confidence Optional :59)
class TranscriberBackend(str, Enum)                                          # transcriber/models.py:16
class TranscriptionResult(BaseModel)                                         # transcriber/models.py:90
class FasterWhisperBackend(AbstractTranscriberBackend)                       # transcriber/faster_whisper_backend.py:21
# Moonshine: English-only, _DEFAULT_MODEL = "moonshine/base"                 # transcriber/moonshine_backend.py:33-35
```

#### Verified Imports
```python
# parrot-formdesigner (internal)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, walk_fields
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope
from parrot_formdesigner.core.constraints import DependencyRule, PostDependency, LogicGroup
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.services.validators import FormValidator, ValidationResult
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator, RuleResolution
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage, BlobMetadata
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission
from parrot_formdesigner.services.event_dispatcher import dispatch, apply_schema_overrides
from parrot_formdesigner.services.forwarder import SubmissionForwarder
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.audio.models import VoiceMode, AudioSessionConfig, AudioQuestion, AudioFormManifest, AudioAnswer, AudioSessionState
from parrot_formdesigner.renderers.audio import AudioFormRenderer, classify_voice_mode, synthesize_with_fallback
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, MAX_QUESTIONS, _sniff_audio_suffix

# optional (guarded with TYPE_CHECKING / try-import, pattern api/audio_ws.py:47-54, api/handlers.py:93, :209)
from parrot.clients.base import AbstractClient
from parrot.clients.google import GoogleGenAIClient
from parrot.models import StructuredOutputConfig, OutputFormat           # re-exported; clients/base.py:50
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator
from parrot.voice.tts.synthesizer import VoiceSynthesizer, get_shared_synthesizer, close_shared_synthesizers
from parrot.voice.tts.models import TTSConfig
from parrot.voice.transcriber.backend import AbstractTranscriberBackend
from parrot.voice.transcriber.models import TranscriberBackend, TranscriptionResult
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
```

#### Key Attributes & Constants
- `MAX_QUESTIONS = 10` → `int` (`api/audio_ws.py:59`); `_MIN_AUDIO_BYTES = 256` (`:68`); `max_msg_size = 10 * 1024 * 1024` (`:151`).
- `AudioSessionConfig.stt_confirm_threshold` → `float`, default `0.6` (`audio/models.py:69`).
- `PartialSaveStore.REDIS_KEY_PREFIX = "parrot:partial:"` (`services/partial_saves.py:50`); key shape `parrot:partial:{form_id}:{session_id}` (`:191`).
- `BlobMetadata.blob_id` regex `^[A-Za-z0-9_-]{1,128}$` (`services/blob_storage.py:93`).
- `_DEFAULT_DDL_TYPE = "TEXT"` (`services/sinks/postgres_table.py:79`); `jsonb_columns` base `{"context", "extra_data"}` (`:322`).
- `FormSubmission.is_valid: bool` (`services/submissions.py:101`); DDL `is_valid BOOLEAN NOT NULL DEFAULT TRUE` (`:195`).
- Protocol v1 inbound: `start_session, answer_text, <binary answer_audio>, answer_selection, answer_payload, confirm_answer, skip_question, go_back, repeat_question, end_session, ping`; outbound: `session_started, question, transcription, confirm_request, answer_accepted, answer_rejected, form_complete, session_ended, error, pong` (`docs/audio-form-voice-modes.md` §7.1 L415-585, §7.2 L599-786).
- Dependencies: `aiohttp>=3.9` (`pyproject.toml:35`), `jinja2>=3.1` (`:41`), extras `ai-parrot = ["ai-parrot>=1.2.1"]` (`:53-54`), `redis = ["redis>=4.5"]` (`:61-62`).
- Migrations live at `packages/parrot-formdesigner/migrations/` (001–008; `003_migrate_form_data.py` is the asyncpg `--dsn --schema --batch-size --dry-run` pattern; `README.md`).
- Existing audio tests: `packages/parrot-formdesigner/tests/formdesigner/test_audio_{control_metadata,fieldtype,routes,field_renderer,integration,models,tenant,ws_handler,form_renderer}.py`.

### Verified Codebase References — navigator-svelte (cited from this repo only; **not verified in navigator-svelte**)
- `core/constraints.py:203` states `LogicGroup` mirrors the frontend's `formbuilder/types/schema.ts`.
- `sdd/state/FEAT-430/handoff/navigator-svelte-brief.md` cites `src/lib/api/ai-parrot.ts` (direct ai-parrot client), `src/lib/config.ts` (`apiBaseUrl`, `apiAiUrl` from `PUBLIC_API_URL` / `PUBLIC_API_AI_URL`), and that the repo runs its own SDD flow with its own FEAT numbering.
- `sdd/proposals/report-builder.brainstorm.md` §"Verified — navigator-svelte + FieldSync" documents a FieldSync copy of the A2UI renderer.
- In this repo: `packages/ai-parrot-server/ui/src/lib/utils/voice-recorder.ts` exports `RecordedVoiceNote` (L12), `isVoiceRecordingSupported()` (L35), `class VoiceRecorder` (L68) — MediaRecorder with webm → ogg → mp4 fallback; `packages/ai-parrot-server/ui/src/lib/components/agents/VoiceNotePlayer.svelte` exists. **No Svelte client of the forms WebSocket exists in any repo.**

### Does NOT Exist (Anti-Hallucination)
- ~~`FormField.hint`~~, ~~`FormField.audio_hint`~~, ~~`FormField.llm_validation`~~, ~~`FormField.sensitive`~~ (sensitivity is derived from `FieldType.PASSWORD` at `renderers/audio.py:361`), ~~`meta["audio_hint"]`~~ consumed anywhere at runtime.
- ~~`FormSchema.voice`~~, ~~`FormSchema.llm_validation`~~, ~~`core/voice.py`~~, ~~`core/llm_validation.py`~~.
- ~~`ValidationResult.warnings`~~ / ~~`.advisories`~~ / ~~`.plausibility`~~ — the result has only `is_valid`, `errors`, `sanitized_data`, `extra_data`.
- ~~`FormValidator(client=...)`~~ — the constructor takes no arguments; no LLM anywhere in `services/validators.py`.
- ~~`services/plausibility.py`~~, ~~`AnswerPlausibilityChecker`~~, ~~`PlausibilityReport`~~, ~~`services/submission_pipeline.py`~~, ~~`SubmissionPipeline`~~.
- ~~`AudioQuestion.hint / narration / ui_cue / section_uid / answer_modes`~~, ~~`AudioAnswer.blob_ref / matched / plausibility`~~, ~~`AudioSessionState.phase / cursor / plan`~~.
- ~~`audio/{engine,planner,option_matcher,commands,option_refiner,narration,segments,events,session_store,recordings}.py`~~.
- Messages ~~`audio_segment`, `plan_updated`, `section_enter`, `question_skipped`, `answer_cleared`, `review_*`, `plausibility_check`, `plausibility_result`, `command_ack`, `session_resumed`, `validation_errors`, `goto_question`, `save_session`~~.
- ~~`PartialSaveStore.remove_keys()`~~; ~~`AudioSessionStore`~~; any use of `RuleEvaluator` or `blob_storage` or `partial_store` in `api/audio_ws.py`.
- ~~`AbstractTranscriberBackend.transcribe_bytes()`~~ or any streaming STT; ~~SSML in SuperTonic~~; ~~`VoiceSynthesizer.synthesize_to_base64()`~~.
- ~~A2UI voice primitive~~ (AUDIO degrades to `notice`, `renderers/a2ui.py:238`).
- ~~`packages/parrot-formdesigner/src/parrot_formdesigner/migrations/`~~ — migrations live at the package root `packages/parrot-formdesigner/migrations/`; ~~`009_*`, `010_*`~~ do not exist yet.
- ~~`packages/parrot-formdesigner/docs/audio-form-voice-modes.md`~~ — the doc is at the repo root `docs/audio-form-voice-modes.md`.
- ~~`POST …/voice/optimize`~~, ~~`EditToolkit.propose_voice_hints`~~, ~~`llm_validation` flag on `POST …/validate`~~.
- ~~A Svelte client of the forms WebSocket~~ in any repo.

---

## Parallelism Assessment

- **Internal parallelism**: after a first "models + schema" task (`FormField.hint/llm_validation`, `FormSchema.voice/llm_validation`, `VoiceEvidenceEnvelope`, `audio/events.py`), four lanes are independent: (1) planner + option matcher + commands + narration (pure, no I/O); (2) `SubmissionPipeline` extraction + `AnswerPlausibilityChecker` + validators unwrap/rewrap + sinks JSONB + migrations 009/010; (3) resume (`AudioSessionStore`, `PartialSaveStore.remove_keys`) + recordings; (4) renderer `hint` exposure + `EditToolkit` fields. The engine + adapter task integrates (1)–(3); the HTTP `validate`/`submit_data` wiring and the optimiser follow (2); the Svelte handoff and docs close.
- **Cross-feature independence**: shared hot files are `core/schema.py`, `services/validators.py`, `api/handlers.py`, `api/routes.py`. `git log --since 2026-09-01` on those shows only FEAT-544 (completed) and FEAT-488 (completed) commits; the only open formdesigner-adjacent index is FEAT-536 `voicebot-liveavatar-implementation` (different package, no shared files). FEAT-636 `linked-a2ui` is completed. The `claude/form-submission-metadata-TYH8Z` remote branch (2026-05-18) touches submissions metadata but is stale and unmerged — check before the pipeline extraction task.
- **Recommended isolation**: `mixed` — one feature worktree; lane (1) and lane (3) tasks may run in sub-worktrees because they create only new files; lane (2) and the engine/adapter tasks must be sequential because they modify `handlers.py`, `validators.py`, `audio_ws.py`.
- **Rationale**: pure components with no shared files parallelise safely; the submit-path extraction is the single highest-risk change and must land with parity tests before the audio adapter switches to it.

---

## Open Questions

Resolved (owner decisions — carried from the proposal and the two discovery rounds of 2026-10-10):

- [x] Pre-synthesised audio delivery — *Owner: Jesus*: WebSocket only; pre-synthesis at `start_session` plus a prefetch batch of `audio_segment` frames; no audio in the HTTP manifest.
- [x] Per-field voice configuration — *Owner: Jesus*: first-class `FormField.hint: LocalizedString | None`; other voice settings under `FormField.meta["voice"]`.
- [x] Where text + audio of an answer live — *Owner: Jesus*: envelope per field in `FormSubmission.data[field_id]` (`VoiceEvidenceEnvelope`), audio in blob storage.
- [x] Envelope scope — *Owner: Jesus*: every spoken answer, any field type; typed/selected answers stay flat scalars.
- [x] Item-by-item selectors — *Owner: Jesus*: list all options (one segment each, with ordinal), then listen; `option_matched` highlights the option in the UI.
- [x] `form_data` migration — *Owner: Jesus*: per-form DDL (`ALTER COLUMN … TYPE JSONB USING jsonb_build_object('answer', col)`) + legacy normalisation of voice-declared string answers to `{answer, blob_ref: null}`; sink DDL emits JSONB for voice fields going forward.
- [x] Review confirmation — *Owner: Jesus*: voice ("ok / sí / enviar", deterministic per-locale lexicon) or Send button → `review_confirm`; "cambiar la N" re-asks and returns to review.
- [x] Extras in scope — *Owner: Jesus*: Redis resume, per-form question cap (never truncate required), design-time LLM optimiser, separate frontend handoff, migration.
- [x] LLM-assisted validation — declaration and channels — *Owner: Jesus*: per-field attribute (`FormField.llm_validation`) with a form-level default (`FormSchema.llm_validation`), applied on **every** channel (audio and HTTP submit).
- [x] LLM-assisted validation — low confidence — *Owner: Jesus*: re-ask (audio) or flag with per-field `confidence` (HTTP); never block the submit; persist the confidence in the envelope / `context`.
- [x] LLM-assisted validation — LLM unavailable or timeout — *Owner: Jesus*: fail-open with audit (`llm_validation.status = skipped` + reason in `context`).
- [x] LLM-assisted validation — invocation — *Owner: Jesus*: one batched structured-output call at the end of the form (`[{field_id, plausible, confidence, reason}]`).
- [x] LLM-assisted validation — placement — *Owner: Jesus*: separate `services/plausibility.py` service invoked by the `SubmissionPipeline` after `FormValidator`; the validator stays deterministic and `ai-parrot`-free.
- [x] LLM-assisted validation — HTTP surface — *Owner: Jesus*: additive `plausibility` block in the submit response (persisted) **and** an opt-in `llm_validation: true` on `POST …/validate` so HTML can warn before submitting.
- [x] LLM-assisted validation — model input — *Owner: Jesus*: label + description + hint + field type + options + scalar answer; never `sensitive` fields, never blobs or `data_url`; no cross-field context in v1.
- [x] Hands-free navigation commands — *Owner: Jesus*: in scope; the engine classifies transcripts against a per-locale command lexicon (repeat / back / skip / help / stop / …) before the option matcher and emits `command_ack`; the client auto-opens the microphone when TTS ends (VAD + silence).

Resolved in the owner review of 2026-10-10 (all former open items):

- [x] Per-form blocks typed vs `meta` — *Owner: Jesus*: typed `FormSchema.voice` and `FormSchema.llm_validation` (precedent `events`/`persistence`); the navigator-svelte designer schema learns them via the handoff.
- [x] MULTI_SELECT by voice — *Owner: Jesus*: stored as a list (fixes `audio_ws.py:595`); `form_complete` keeps a display string.
- [x] `sensitive` fields in review — *Owner: Jesus*: narrate "[hidden]"; the item keeps its position so "cambiar la N" still works.
- [x] HTTP `/partial` and the audio snapshot — *Owner: Jesus*: `/partial` exposes answers only; the cursor/phase snapshot is private to the audio channel (`parrot:audio:*`).
- [x] `VoiceEvidenceEnvelope` shape — *Owner: Jesus*: subclass of `VoiceAnswerEnvelope`; FEAT-488's `answer: str` contract on TEXT/TEXT_AREA stays intact.
- [x] LLM option refinement at runtime — *Owner: Jesus*: off by default, opt-in `voice.llm_refine_options`; results always go through `confirm_request`.
- [x] Optimiser `apply` — *Owner: Jesus*: staging only; the endpoint returns proposals and never writes; the designer applies them through `update_field`.
- [x] Migration 009 and the `voice_data` sidecar — *Owner: Jesus*: keep the envelope in the column; `ALTER COLUMN … JSONB` in a maintenance window with `--dry-run`; `fd_unwrap_voice` + `form_data_scalar` view for SQL readers; the sidecar stays rejected.
- [x] GROUP children in `RuleEvaluator` — *Owner: Jesus*: do not change the evaluator; the planner inherits the GROUP parent's visibility; open a ledger issue for `iter_fields_recursive` as separate work.
- [x] Thresholds and lexicons — *Owner: Jesus*: defaults option match 0.8 / confirm 0.6, plausibility threshold 0.7, `timeout_s` 8, `max_fields` 50, all configurable per form; lexicons `en` + `es` in v1, `pt`/`fr` as follow-up (owner to assign).
- [x] Synthesiser sharing — *Owner: Jesus*: one shared synthesiser per process (`get_shared_synthesizer`) with an `asyncio.Lock` per synthesis call.
- [x] `llm_validation.on_error` — *Owner: Jesus*: implement **both** `skip` (default, fail-open with audit) and `block` (LLM failure fails the submit with a retryable error); low confidence never blocks in either mode.
- [x] Plausibility re-check after `review_edit` — *Owner: Jesus*: delta batch for changed fields only; at most one flag per answer version; a kept answer is never re-flagged.
- [x] Default plausibility model — *Owner: Jesus*: the handler's injected client (`_get_llm_client()`, GoogleGenAI default) with a per-form `llm_validation.model` override.
- [x] Command vs option collisions — *Owner: Jesus*: exact option match wins in PROMPT_SELECT; `meta.voice.commands: off` disables commands per field; a lexicon test enumerates collisions per locale.
- [x] Hands-free end-of-speech — *Owner: Jesus* (frontend executes): client-side VAD + `silence_ms`; the server only reports `max_recording_seconds`; VAD library choice is delegated to the navigator-svelte proposal.
