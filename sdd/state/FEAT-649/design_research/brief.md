<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
**Option B** is recommended because:

- The deadlock history (FEAT-395) is a structural property of Option A, not a bug that was fixed: awaiting I/O inside transitions in a 1 467-line handler. Option B's invariant — the engine never performs I/O — makes the class of defect unreachable and lets every new rule (planner, matcher, commands, review, resume) be tested as a pure function.
- The owner's cross-cutting requirement (LLM-assisted plausibility "además de las validaciones existentes", on every channel) is only cheap if there is one submit path. Option B creates that path (`SubmissionPipeline`) and fixes four verified bugs (bypassed sinks/events/forwarder, lost tenant, raw transcript on PROMPT_SELECT, comma-joined MULTI_SELECT) as a side effect. Option A would implement the checker twice.
- Option C's convergence is real but premature: A2UI has no voice primitive and `ai-parrot` is optional for formdesigner. B keeps the door open by isolating the protocol in `audio/events.py`.

What we trade: a larger diff, a parity-test task for the extracted submit tail, and two new typed blocks on `FormSchema`. The parity task is the price of fixing the bypass properly; the schema blocks follow the `events` / `persistence` precedent (`core/schema.py:465`, `:473`) that the frontend already consumes.

---

--- Recommended option (B) as described ---

: Transport-agnostic `AudioFormSession` engine + thin WS adapter + shared `SubmissionPipeline` with `AnswerPlausibilityChecker`

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

### Verified code anchors (paths only — open them yourself)
docs/audio-form-voice-modes.md
packages/ai-parrot-server/ui/src/lib/components/agents/VoiceNotePlayer.svelte
packages/ai-parrot-server/ui/src/lib/utils/voice-recorder.ts
packages/parrot-formdesigner/docs/audio-form-voice-modes.md
packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/ws_auth.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/forwarder.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py
packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py
sdd/proposals/report-builder.brainstorm.md
sdd/state/FEAT-430/handoff/navigator-svelte-brief.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
