---
type: feature
base_branch: dev
projects: [parrot-formdesigner, ai-parrot-integrations, ai-parrot-server, docs]
tags: [formdesigner, audio-form, tts, stt, websocket, voice, llm-validation, hands-free, navigator-svelte, migration]
---

# Feature Specification: Audio Form Interaction Workflow — turn-based voice forms, LLM-assisted answer plausibility, hands-free Svelte renderer

**Feature ID**: FEAT-649
**Date**: 2026-10-10
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor of `parrot-formdesigner` (1.3.0; current `1.2.1`)

Source brainstorm: `sdd/proposals/audio-form-interaction-workflow.brainstorm.md`
(**accepted** 2026-10-10; Recommended Option B — transport-agnostic `AudioFormSession`
engine + thin WebSocket adapter + `AnswerPlausibilityChecker` inside a shared
`SubmissionPipeline`). All 32 of its questions are resolved; every decision is carried
into the body below and echoed in §8. Frontend deliverable:
`sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`.

Verified against `dev @ dc54b7ae6` (code files identical to `b288daa72`, the brainstorm's
base). Paths are relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless stated otherwise.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-224 / FEAT-236 shipped a minimal audio form: a flat question list over a WebSocket,
TTS per question, whole-file STT per answer, a confidence gate and a direct write to
`FormSubmissionStorage`. Every item below is verified in code at the base commit:

- **Promised and never built**: no per-field voice hint (`FormField` has `label`,
  `description`, `placeholder`, `meta` — `core/schema.py:65-143` — and the handler narrates
  only label + "Options: …", `api/audio_ws.py:1333`); `MAX_QUESTIONS = 10` silently
  truncates the list including required fields (`api/audio_ws.py:59`, `:490`); no resume
  (`AudioSessionState` is memory-only, `audio/models.py:179-210`, and the `PartialSaveStore`
  given to `setup_form_api` is never passed to the audio handler, `api/routes.py:202`,
  `:483-491`); no voice→option matching (a binary answer on a select stores the raw
  transcript); no sections/dependencies (`RuleEvaluator.resolve()` is never called from
  audio; questions advance by `index += 1` in two duplicated methods,
  `api/audio_ws.py:1072`, `:1094`); `FormValidator` injected but never invoked
  (`:147-158`); spoken audio discarded after transcription (`_accept_answer`, `:1009`).
- **Bugs**: `_finish_session` (`:1115-1160`) builds `FormSubmission(form_version="1", …)`
  and stores it directly, bypassing `FormAPIHandler.submit_data` (`api/handlers.py:1498`) —
  no FEAT-457 sinks, no FEAT-188 events, no forwarder — and loses the tenant
  (`registry.get(..., tenant=None)`, `:1138`). MULTI_SELECT is stored comma-joined (`:595`).
- **New requirements (owner)**: turn-based TTS→STT with hints and pre-synthesised audio pushed
  over the WebSocket, visual cues, item-by-item option narration with voice selection,
  HTML fallbacks, persisted text+audio per answer, section/dependency awareness, a final
  review step, a deterministic templated runtime, an optional design-time LLM optimiser;
  **a cross-cutting FormBuilder LLM-assisted validation attribute** that, before a form is
  sent and in addition to the deterministic validators, asks an LLM to judge with a
  confidence score whether each answer makes sense for its question (so noise captured by
  STT is not silently recorded as an answer); and an artefact that lets `navigator-svelte`
  build a Svelte 5, audio-first, hands-free renderer.

Affected: field users (accessibility, hands-busy capture), form authors, data operators
reading `form_data`, and the `navigator-svelte` team.

### Goals

- G1. A pure, transport-agnostic audio session engine: `(state, event) → (state', outbound[])`
  with **no I/O inside transitions**; every I/O is an outbound request the adapter fulfils.
- G2. Protocol v2 **additive** over v1: v1 clients keep working; v2 negotiated via
  `protocol_version`; pre-synthesised audio delivered as `audio_segment` header + binary frame.
- G3. First-class `FormField.hint`, narrated after a client-side pause and exposed by every renderer.
- G4. Deterministic per-locale narration templates (Jinja2 sandbox) and lexicons (`en`, `es`
  in v1) for option matching, yes/no, ordinals, review confirmation and **hands-free commands**.
- G5. Sections and dependencies honoured through `RuleEvaluator`; per-form question cap that
  never drops required fields; MULTI_SELECT stored as a list.
- G6. Every spoken answer persisted as a `VoiceEvidenceEnvelope` in `data[field_id]` with the
  recording in blob storage; typed/selected answers stay flat scalars.
- G7. **LLM-assisted answer plausibility on every channel** (audio, HTTP, A2UI): per-field
  opt-in with a per-form default, one batched structured-output call before submit, additive
  result, never blocks on low confidence, `on_error: skip|block` both implemented.
- G8. One `SubmissionPipeline` for HTTP and audio: validator → plausibility → sinks/generic
  storage → lifecycle events → forwarder → partial cleanup; fixes the bypass and the tenant loss.
- G9. Resume over Redis (`AudioSessionStore`), cross-channel completion through the partial store.
- G10. Migration 009/010 for `form_data` and per-form sink tables (JSONB envelopes, scalar view).
- G11. Design-time LLM optimiser that **proposes** hints/prompts (staging only, never writes).
- G12. The navigator-svelte handoff brief kept in sync with the frozen protocol v2.

### Non-Goals (explicitly out of scope)

- In-place growth of `api/audio_ws.py` (brainstorm Option A) and an A2UI voice surface (Option
  C) — rejected; `audio/events.py` keeps the A2UI convergence path open.
- Audio in the HTTP manifest (`GET …/audio`); streaming or partial STT; SSML on SuperTonic.
- Changing `RuleEvaluator` to recurse into GROUP children (owner: planner inherits the GROUP's
  visibility; a ledger issue tracks `iter_fields_recursive` separately).
- Exposing the audio cursor/phase snapshot through the HTTP `/partial` endpoints.
- The rejected `voice_data JSONB` sidecar for CSV/GSheet sinks.
- Cross-field (coherence) context in the plausibility prompt; `pt`/`fr` lexicons (follow-up).
- Any change to `parrot/clients/base.py` or to the `parrot.voice.*` APIs.
- The Svelte renderer itself — built in navigator-svelte from the handoff brief.

---

## 2. Architectural Design

### Overview

The audio runtime is split into pure components and one adapter. `AudioFormSession`
(`audio/engine.py`) owns the state machine
`CONNECTED → PLANNING → ASKING(cursor) → ACCEPTING → [CONFIRMING] → re-plan → … →
PLAUSIBILITY → REVIEW → (review_edit → ASKING → PLAUSIBILITY(delta) → REVIEW) → SUBMITTING →
COMPLETE` and exposes `handle(event) -> list[Outbound]`. It composes `QuestionPlanner`
(manifest + `RuleEvaluator.resolve()` → visible plan, cap, cleared, cursor), `Narrator`
(YAML + Jinja2 sandbox → `NarrationPlan` and `audio_keys`), `match_option()` and
`classify_command()` (normalised transcript → option / command, with the lexicon),
and a `PlausibilityReport` it receives as an event. The adapter `AudioFormWSHandler`
(`api/audio_ws.py`, rewritten to ~300 lines) authenticates, decodes JSON/binary, calls the
engine, performs the requested I/O — synthesis through `AudioSegmentCache` (one shared
synthesiser per process behind an `asyncio.Lock`), transcription, blob `put`/`delete`
(`audio/recordings.py`), snapshot `save` (`AudioSessionStore`), the plausibility call and
the submit — and encodes replies. Phase transitions never await.

Cross-cutting, the HTTP submit tail (`api/handlers.py:1818-1909`) is extracted into
`SubmissionPipeline.submit()` (`services/submission_pipeline.py`) and called by
`submit_data`, the A2UI branch and the engine's SUBMITTING outbound. After
`FormValidator.validate()` passes, the pipeline calls `AnswerPlausibilityChecker.check()`
(`services/plausibility.py`) once with every eligible (question, answer) pair when the form
enables `llm_validation`; the report is returned additively (`plausibility` block), persisted
in `FormSubmission.context["llm_validation"]` and, for spoken answers, inside the envelope.
`POST …/validate` accepts `llm_validation: true` to return the same block before submit.
`FormValidator` is **not** modified for plausibility and stays deterministic and
`ai-parrot`-free; the checker degrades to `status: skipped` when no client is available
(`on_error: skip`, default) or fails the submit with a retryable error (`on_error: block`).
Low confidence never blocks in either mode: audio re-asks from the review, HTTP flags.

Schema additions are typed (owner decision): `FormField.hint: LocalizedString | None`,
`FormField.llm_validation: bool | None` (None inherits), `FormSchema.voice: VoiceFormConfig |
None`, `FormSchema.llm_validation: LLMValidationConfig | None`; `meta["voice"]` parses into
`FieldVoiceMeta` (extra ignored, warning) and `meta["voice_mode"]` is preserved.
`VoiceEvidenceEnvelope(VoiceAnswerEnvelope)` widens `answer: Any` and adds evidence fields;
FEAT-488's `answer: str` contract on TEXT/TEXT_AREA stays intact.

### Component Diagram

```
                      ┌───────────────────────────── api/audio_ws.py (adapter, I/O only) ─────────────────────────────┐
WS client ── JSON/bin ─▶ auth · decode ──▶ AudioFormSession.handle(event) ──▶ outbound[] ──▶ encode · I/O ──▶ WS client
                      │                      │ (audio/engine.py — pure)                        │                        │
                      │        ┌─────────────┼─────────────┬───────────────┐                   │                        │
                      │  QuestionPlanner   Narrator     match_option     classify_command        │  AudioSegmentCache    │
                      │  (audio/planner)   (narration)  (option_matcher) (commands)              │  (shared synth+Lock)  │
                      │        │                                                                  │  recordings (blob)    │
                      │  RuleEvaluator.resolve()  ◀── existing                                    │  AudioSessionStore    │
                      └──────────────────────────────────────────────────────────────────────────┼──────────────────────┘
                                                                                                 ▼
HTTP submit_data / validate (api/handlers.py) ──┐                               SubmissionPipeline.submit()  (services/submission_pipeline.py)
A2UI branch (api/a2ui_wire.py) ─────────────────┤──▶ FormValidator.validate() ─▶ AnswerPlausibilityChecker.check() ─▶ sinks | FormSubmissionStorage
                                                │        (unchanged)              (services/plausibility.py,            ─▶ dispatch(events) ─▶ forwarder
                                                │                                  AbstractClient.ask(structured_output))  ─▶ partial cleanup
Schema: FormField.hint / .llm_validation · FormSchema.voice / .llm_validation · VoiceEvidenceEnvelope (core/)
Data:   form_data.data[field_id] = envelope (spoken) | scalar · context.llm_validation · per-form sink JSONB (migrations 009/010)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormField`, `FormSchema` (`core/schema.py:65`, `:401`) | extends | `hint`, `llm_validation` on fields; `voice`, `llm_validation` blocks on the form. `FormField` is `extra="forbid"` (`:121`); `FormSchema` has no `model_config` (unknown keys ignored) |
| `VoiceAnswerEnvelope` (`core/voice_answer.py:13`) | extends | `VoiceEvidenceEnvelope` subclass; helpers `is_voice_envelope/unwrap_voice/wrap_voice` |
| `FormValidator.validate()` (`services/validators.py:221`) | uses + modifies | called unchanged by the pipeline; envelope acceptance widened from TEXT/TEXT_AREA (`:542-548`, `:629-634`) to any voice-answered type via unwrap → validate → rewrap |
| `RuleEvaluator.resolve()` (`services/rule_evaluator.py:578`) | uses | planner re-plans after every accepted answer; **not modified** |
| `PartialSaveStore` (`services/partial_saves.py:24`) | extends | `remove_keys()`; Redis client/TTL reused by `AudioSessionStore` |
| `AbstractBlobStorage`, `BlobMetadata` (`services/blob_storage.py:119`, `:55`) | uses | recordings with deterministic `blob_id = f"voice-{session_id}-{field_uid}"` |
| `FormSubmission`, `FormSubmissionStorage` (`services/submissions.py:50`, `:122`) | uses | `context["llm_validation"]`, envelopes in `data`; readers adapt via `unwrap_voice()` |
| `flatten_submission`/`_extract_value` (`services/sinks/mapper.py:142`, `:176`), `postgres_table.py:79`, `:322` | modifies | JSONB DDL + `jsonb_columns` for voice fields |
| `FormAPIHandler.submit_data` / `validate` / `_get_llm_client` (`api/handlers.py:1498`, `:1004`, `:197`) | modifies / uses | delegate to `SubmissionPipeline`; `llm_validation` opt-in on validate; `voice/optimize` endpoint; the injected client feeds checker + optimiser |
| `setup_form_api` (`api/routes.py:192`) | modifies | passes `blob_storage`, `partial_store`, `client` to the adapter; mounts optimize |
| `AudioFormWSHandler` (`api/audio_ws.py:102`) | rewrites | becomes the adapter; v1 messages still accepted |
| `AudioFormRenderer.split_into_questions` (`renderers/audio.py:277`) | modifies | section/hint/ui_cue/answer_modes/voice_meta on `AudioQuestion` |
| `EditToolkit.update_field` (`tools/edit_toolkit.py:318`), `api/operations.py` | extends | `hint`, `llm_validation` fields; `propose_voice_hints` |
| HTML5/JSON-Schema/Adaptive Card/A2UI/PDF renderers | extends | expose `hint`; `prefilled` reads through `unwrap_voice()` |
| `VoiceSynthesizer`, `get_shared_synthesizer` (ai-parrot-integrations `tts/synthesizer.py:23`, `:186`) | uses | one shared synthesiser per process + `asyncio.Lock`; API unchanged |
| `AbstractTranscriberBackend.transcribe(Path)` (`transcriber/backend.py:39`) | uses | whole-file; `confidence` may be `None` |
| `AbstractClient.ask(structured_output=…)` (ai-parrot `clients/base.py:1817`) | uses | plausibility batch, optimiser, optional refiner; **never modified** |
| `docs/audio-form-voice-modes.md` | modifies | protocol v2, plausibility, commands; §9.10/9.11 superseded by the Svelte handoff |

### Data Models

```python
# core/voice.py (new)
class FieldVoiceMeta(BaseModel):            # parsed from FormField.meta["voice"]; extra="ignore" + warning
    prompt: str | None = None               # str.format_map whitelist {label, hint, section, n, total} — NOT Jinja
    enumerate: Literal["auto", "always", "never", "count_only"] = "auto"
    confirm: Literal["auto", "always", "never"] = "auto"
    pause_ms: int | None = None
    ui_cue: UiCue | None = None
    match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    skip_in_review: bool = False
    commands: Literal["on", "off"] = "on"   # owner: per-field command opt-out
    sensitive: bool = False                 # S8: marks a non-PASSWORD field as sensitive for narration/review/plausibility/logs

class VoiceFormConfig(BaseModel):           # FormSchema.voice (typed block)
    enabled: bool = True
    max_questions: int | None = 10          # None = unlimited; required fields always kept
    hint_pause_ms: int = 600
    enumerate_options: bool = True
    stt_confirm_threshold: float = 0.6
    option_match_threshold: float = 0.8
    review: Literal["always", "never", "ask"] = "always"
    review_playback: Literal["tts", "recording", "both"] = "tts"
    store_recordings: bool = True
    resume_ttl_seconds: int = 3600
    llm_refine_options: bool = False        # owner: off by default
    commands: Literal["on", "off"] = "on"
    hands_free: HandsFreeConfig = HandsFreeConfig()   # {auto_record: bool = True, silence_ms: int = 1200}
    tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: str | None = None
    max_recording_seconds: int = 60

# core/llm_validation.py (new)
class LLMValidationConfig(BaseModel):       # FormSchema.llm_validation (typed block)
    enabled: bool = False
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    on_error: Literal["skip", "block"] = "skip"      # BOTH implemented (owner); governs LLM failure only
    model: str | None = None                          # None → handler's injected client
    timeout_s: float = 8.0
    max_fields: int = 50                              # required fields first
    exclude_field_types: list[FieldType] = [PASSWORD, HIDDEN, FILE, IMAGE_DROPZONE, CREDIT_CARD, SIGNATURE]

class PlausibilityVerdict(BaseModel):
    plausible: bool
    confidence: float = Field(ge=0.0, le=1.0)         # clamped on parse
    reason: str

class PlausibilityReport(BaseModel):
    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = {}       # keyed by field_id

# core/voice_answer.py (modify)
class VoiceEvidenceEnvelope(VoiceAnswerEnvelope):   # FEAT-488 base untouched
    answer: Any                                       # list for MULTI_SELECT, bool for BOOLEAN, …
    confidence: float | None = None
    source: Literal["speech"] = "speech"
    audio_mime: str | None = None
    duration_ms: int | None = None
    language: str | None = None
    plausibility: PlausibilityVerdict | None = None

# audio/models.py (modify) — deltas
class UiCue(BaseModel): control: str; focus: bool = True; highlight: bool = True; submit_via: Literal["voice", "control", "both"] = "both"
class OptionMatch(BaseModel): value: Any; label: str; method: Literal["exact", "ordinal", "yes_no", "numeric", "contains", "fuzzy", "llm"]; score: float
class NarrationPlan(BaseModel): text: str; audio_keys: list[str]; segments: dict[str, str]   # key → text
AudioQuestion  += section_uid, section_title, subsection_title, hint, prompt, narration: NarrationPlan, ui_cue, answer_modes: list[str], voice_meta: FieldVoiceMeta, llm_validation: bool
AudioAnswer    .value: Any  += blob_ref, audio_mime, audio_bytes_len, duration_ms, matched: OptionMatch | None, stt_language, answered_at, version: int
AudioSessionState += phase: Phase, cursor: str | None, history: list[str], plan: list[str], return_to_review: bool, review_cursor: int,
                     resolution: RuleResolution | None, tenant: str | None, locale: str, submission_id: str, protocol_version: int,
                     plausibility: PlausibilityReport | None, flagged: dict[str, int]   # field_id → answer version flagged
```

### New Public Interfaces

```python
# audio/engine.py
class AudioFormSession:
    def handle(self, event: InboundEvent) -> list[Outbound]: ...   # pure; never awaits
# audio/events.py — Pydantic unions InboundEvent / Outbound discriminated by `type` (protocol v2, see Module 2)
# services/plausibility.py
class AnswerPlausibilityChecker:
    async def check(self, form: FormSchema, scalars: dict[str, Any], *, locale: str, fields: set[str] | None = None) -> PlausibilityReport: ...
# services/submission_pipeline.py
class SubmissionPipeline:
    async def submit(self, form: FormSchema, data: dict[str, Any], *, tenant: str | None, user_id: str | None, locale: str,
                     context: dict[str, Any] | None, extra_data: dict[str, Any] | None, auth_context: AuthContext | None,
                     merge_session_id: str | None, plausibility: PlausibilityReport | None = None) -> SubmitOutcome: ...
# HTTP
POST /api/v1/{tenant}/forms/{form_uid}/validate        body may carry "llm_validation": true → response gains "plausibility"
POST /api/v1/{tenant}/forms/{form_uid}/data            response gains "plausibility" when the form enables it
POST /api/v1/{tenant}/forms/{form_uid}/voice/optimize  proposals only (staging), never writes
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 Schema & config models | yes | field names, types, defaults and `extra` policies fixed in §2 Data Models; `core/__init__.py` exports | — |
| M2 Protocol events & model deltas | yes | message names and payload keys frozen in this spec and the handoff; discriminator `type`; `extra="forbid"` inbound | — |
| M3 Narration | yes | YAML key list fixed; Jinja2 `ImmutableSandboxedEnvironment` + `StrictUndefined`; `es-MX → es → en` fallback; author prompt via `str.format_map` whitelist | — |
| M4 Option matcher & commands | yes | normalisation pipeline, method order and thresholds fixed; command precedence rules fixed | — |
| M5 Planner | yes | cursor rule, cap rule (required always kept), re-plan trigger fixed; uses `RuleEvaluator.resolve()` verbatim | — |
| M6 Segments & recordings | yes | cache key, shared synthesiser + lock, deterministic `blob_id` fixed | — |
| M7 Session store | yes | Redis key, snapshot fields, resume checks fixed | — |
| M8 Plausibility checker | yes | eligibility rules, prompt content, structured-output schema, `on_error` semantics fixed | — |
| M9 Submission pipeline | **no** | extraction of `handlers.py:1818-1909` must preserve FEAT-457 sink exclusivity, FEAT-188 event ordering and FEAT-544 A2UI envelopes; parity tests first | behaviour-preserving refactor of the hot path needs the thinking model |
| M10 Engine | **no** | state machine is specified but phase/edge interplay (review_edit → delta plausibility → review, resume re-plan) is the design core | integration of M2–M5 semantics |
| M11 WS adapter | yes (after M10) | I/O mapping table per `Outbound` kind fixed; auth code moved verbatim | — |
| M12 Sinks JSONB & migrations | yes | DDL/`jsonb_columns` rule, `ALTER COLUMN … USING jsonb_build_object`, `fd_unwrap_voice`, report CLI flags fixed | — |
| M13 Renderers hint, toolkit, optimiser | yes | `hint` placement per renderer named; optimiser is proposals-only with fixed I/O | — |
| M14 Docs & handoff | yes | protocol v2 tables as frozen here | — |

### Module 1: Schema & config models
- **Path**: `core/schema.py` (modify), `core/voice.py` (new), `core/llm_validation.py` (new), `core/voice_answer.py` (modify), `core/__init__.py` (modify)
- **Responsibility**: typed blocks and field attributes decided by the owner; envelope subclass and helpers; `field_voice_meta()` parser.
- **Depends on**: existing `LocalizedString`, `FieldType` (`core/types.py:16`), `VoiceAnswerEnvelope`.
- **Interface Skeleton**:
  ```python
  # core/schema.py  (modifies core/schema.py:143 and :475)
  class FormField(BaseModel):                       # verified: core/schema.py:65
      hint: LocalizedString | None = None           # narrated after the pause; shown as help text by renderers
      llm_validation: bool | None = None            # None → inherit FormSchema.llm_validation.enabled
  class FormSchema(BaseModel):                      # verified: core/schema.py:401
      voice: VoiceFormConfig | None = None          # typed block (owner decision)
      llm_validation: LLMValidationConfig | None = None

  # core/voice.py (new)
  class HandsFreeConfig(BaseModel): ...
  class UiCue(BaseModel): ...                       # re-exported by audio/models.py
  class FieldVoiceMeta(BaseModel): ...              # §2 Data Models
  class VoiceFormConfig(BaseModel): ...
  def is_sensitive(field: FormField) -> bool:
      """Single sensitivity policy (S8): field_type == PASSWORD (verified: renderers/audio.py:361) or meta["voice"]["sensitive"] is True. Used by narration, review, plausibility eligibility, logging and form_complete."""
  def field_voice_meta(field: FormField, *, logger: logging.Logger | None = None) -> FieldVoiceMeta:
      """Parse ``field.meta["voice"]`` (extra keys ignored with one warning); defaults when absent/invalid."""
  def resolve_voice_config(form: FormSchema, session: AudioSessionConfig | None) -> VoiceFormConfig:
      """Effective config: session may only tighten (lower thresholds up, caps down) the form block."""

  # core/llm_validation.py (new)
  class LLMValidationConfig(BaseModel): ...
  class PlausibilityVerdict(BaseModel): ...
  class PlausibilityReport(BaseModel): ...
  def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:
      """field.llm_validation if not None else bool(form.llm_validation and form.llm_validation.enabled)."""

  # core/voice_answer.py  (modifies core/voice_answer.py:13 — adds below the base class)
  class VoiceEvidenceEnvelope(VoiceAnswerEnvelope): ...   # verified base: core/voice_answer.py:13
  def is_voice_envelope(value: Any) -> bool:
      """True for a dict/model carrying the envelope shape (``answer`` key present, ``source == "speech"`` or ``blob_ref``)."""
  def unwrap_voice(data: dict[str, Any]) -> dict[str, Any]:
      """Return scalars: envelopes replaced by their ``answer``; everything else untouched."""
  def wrap_voice(scalars: dict[str, Any], evidence: dict[str, AudioAnswer]) -> dict[str, Any]:
      """Re-fold sanitised scalars into ``VoiceEvidenceEnvelope`` for fields whose AudioAnswer.source == "speech"."""
  ```

### Module 2: Protocol events & audio model deltas
- **Path**: `audio/events.py` (new), `audio/models.py` (modify), `audio/__init__.py` (modify)
- **Responsibility**: protocol v2 inbound/outbound models; the `AudioQuestion`/`AudioAnswer`/`AudioSessionState` deltas; `Phase` enum.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # audio/events.py (new) — v2 inbound models: model_config = ConfigDict(extra="forbid"); v1 (protocol_version absent) is parsed by LegacyInbound models with extra="ignore" (S6 — today's handler ignores unknown keys, api/audio_ws.py:420-431)
  class Phase(str, Enum): IDLE, PLANNING, ASKING, ACCEPTING, CONFIRMING, PLAUSIBILITY, REVIEW, REVIEW_EDITING, SUBMITTING, COMPLETE, ABORTED
  # inbound (client → engine; the adapter wraps binary frames and I/O results as events too)
  class StartSession(BaseModel): type: Literal["start_session"]; form_uid: str; locale: str = "en"; protocol_version: int = 1; prefetch: bool = True; resume_session_id: str | None = None; stt_confirm_threshold: float | None = None
  class AnswerText / AnswerSelection / AnswerPayload / ConfirmAnswer / SkipQuestion / GoBack(to_field_id: str | None) / RepeatQuestion / EndSession / Ping   # v1 names preserved
  class ReviewConfirm(BaseModel): type: Literal["review_confirm"]; confirmed: bool
  class ReviewEdit(BaseModel): type: Literal["review_edit"]; field_id: str
  class TranscriptReady(BaseModel): type: Literal["_transcript"]; field_id: str; text: str; language: str | None; confidence: float | None; audio_mime: str; audio_bytes_len: int; duration_ms: int | None   # adapter-internal
  class BlobStored / SnapshotSaved / PlausibilityDone(report: PlausibilityReport) / SubmitDone(outcome) / IOFailed(code, detail)   # adapter-internal
  InboundEvent = Annotated[Union[...], Field(discriminator="type")]
  # outbound (engine → adapter). Wire messages:
  SessionStarted, AudioSegment(key, mime, kind, text) , Question, Transcription, ConfirmRequest, AnswerAccepted(matched, blob_ref), AnswerRejected(code), CommandAck(command),
  PlanUpdated(order, hidden, cleared, required_changed, hidden_by_cap), SectionEnter, QuestionSkipped, AnswerCleared, ReviewStart(items), ReviewItem, ReviewPrompt,
  PlausibilityResult(status, items, reason), ValidationErrors(errors, first_field_id), SessionResumed, FormComplete(submission_id, stored_in, plausibility_summary), SessionEnded, Error(code, message), Pong
  # I/O requests (adapter performs, then feeds a *_Done event back):
  Synthesize(keys: list[str], texts: dict[str, str]), Transcribe(field_id, audio: bytes), StoreBlob(field_id, audio, mime), DeleteBlob(blob_ref), SaveSnapshot(state), RunPlausibility(fields: set[str]), Submit(data, context)
  Outbound = Union[...]

  # audio/models.py  (modifies audio/models.py:72, :153, :179 — field additions per §2 Data Models)
  class AudioQuestion(BaseModel): ...      # verified: audio/models.py:72
  class AudioAnswer(BaseModel): ...        # verified: audio/models.py:153 — value: Any (was str)
  class AudioSessionState(BaseModel): ...  # verified: audio/models.py:179 — current_index kept for v1 compatibility, derived from cursor
  ```

### Module 3: Narration
- **Path**: `audio/narration/__init__.py`, `audio/narration/engine.py`, `audio/narration/lexicon.py`, `audio/narration/templates/en/narration.yaml`, `audio/narration/templates/es/narration.yaml` (all new); `pyproject.toml` package-data for the YAML files.
- **Responsibility**: deterministic text for every spoken turn and the per-locale lexicon (ordinals, yes/no, conjunctions, fillers, commands, review confirmations).
- **Depends on**: Module 1 (`FieldVoiceMeta`, `FormField.hint`).
- **Interface Skeleton**:
  ```python
  # audio/narration/engine.py
  NARRATION_KEYS: frozenset[str] = frozenset({"question", "question_with_prompt", "hint_bridge", "options_intro", "option_item", "options_count_only",
      "boolean_prompt", "required_mark", "confirm_readback", "confirm_option", "no_match", "required_reject", "skipped", "section_intro", "computed_statement",
      "review_intro", "review_item", "review_item_skipped", "review_all_correct", "review_edit_ack", "plausibility_flag", "plausibility_keep", "submitted",
      "resume_welcome", "command_ack_repeat", "command_ack_back", "command_ack_skip", "command_ack_help", "command_ack_stop", "command_ack_next", "command_ack_send", "command_ack_change"})
  class Narrator:
      def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None:
          """Load ``<locale>/narration.yaml`` with fallback ``es-MX → es → en``; Jinja2 ImmutableSandboxedEnvironment + StrictUndefined."""
      def render(self, key: str, **ctx: Any) -> str:
          """Render one template key; raises KeyError for an unknown key (conformance test guards every locale)."""
      def plan_question(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> NarrationPlan:
          """label → ``pause:<ms>`` → hint_bridge + hint (or description) → options_intro + option_item×N / options_count_only; returns keys ``q:<uid>:label|hint|options``."""
      def plan_review(self, items: list[ReviewItemData], cfg: VoiceFormConfig) -> NarrationPlan: ...
      def system_phrases(self) -> dict[str, str]:
          """``sys:*`` keys pre-synthesised at start_session."""
  def render_author_prompt(prompt: str, *, label: str, hint: str, section: str, n: int, total: int) -> str:
      """``str.format_map`` over a whitelist dict; unknown placeholders rendered verbatim (never Jinja)."""
  # audio/narration/lexicon.py
  class Lexicon(BaseModel): ordinals: dict[str, int]; cardinals: dict[str, int]; yes: list[str]; no: list[str]; all: list[str]; none: list[str];
                            conjunctions: list[str]; fillers: list[str]; commands: dict[str, list[str]]; review_confirm: list[str]; review_change: list[str]
  def load_lexicon(locale: str) -> Lexicon: ...
  def normalize(text: str, lexicon: Lexicon) -> str:
      """NFKD → casefold → strip punctuation → drop fillers → collapse whitespace."""
  ```

### Module 4: Option matcher, commands, optional refiner
- **Path**: `audio/option_matcher.py`, `audio/commands.py`, `audio/option_refiner.py` (all new)
- **Responsibility**: pure deterministic matching of a transcript to options / booleans / numeric scales / review items; hands-free command classification; the opt-in LLM refiner protocol.
- **Depends on**: Module 3 (`Lexicon`, `normalize`), Module 2 (`OptionMatch`).
- **Interface Skeleton**:
  ```python
  # audio/option_matcher.py
  class MatchOutcome(BaseModel): status: Literal["accepted", "confirm", "no_match"]; match: OptionMatch | None; alternatives: list[OptionMatch]; matches: list[OptionMatch]   # matches for multi
  def match_option(transcript: str, options: list[dict], *, field_type: FieldType, lexicon: Lexicon, threshold: float = 0.8, confirm_floor: float = 0.6,
                   stt_confidence: float | None = None, multi: bool = False) -> MatchOutcome:
      # S4: options with disabled=True are never candidates; a tie between the two best candidates (|Δscore| < 0.05) → status "confirm" with alternatives, never a guess.
      """exact value/label → ordinal/cardinal → yes/no (BOOLEAN) → numeric (LIKERT/NPS/RANKING) → unique contains → difflib fuzzy.
      Effective score = score × (stt_confidence or 1.0); ≥ threshold accepted, [confirm_floor, threshold) confirm, else no_match.
      multi=True splits on conjunctions and resolves ``all``/``none``."""
  def match_review_item(transcript: str, items: list[ReviewItemData], lexicon: Lexicon) -> int | None:
      """'cambiar la N' / label match → item position; None when not a change request."""
  # audio/commands.py
  class VoiceCommand(str, Enum): REPEAT, BACK, SKIP, HELP, STOP, NEXT, SEND, CHANGE, YES, NO
  def classify_command(transcript: str, *, lexicon: Lexicon, phase: Phase, max_tokens: int = 4) -> VoiceCommand | None:
      """Whole-utterance match (≤ max_tokens after normalize) against lexicon.commands; fuzzy ≥ 0.9; phase-gated (YES/NO/SEND/CHANGE only in CONFIRMING/REVIEW)."""
  def command_option_collisions(options: list[dict], lexicon: Lexicon) -> list[tuple[str, VoiceCommand]]:
      """Option labels that normalise to a command phrase — used by tests and the optimiser self-test."""
  # audio/option_refiner.py
  class OptionRefiner(Protocol):
      async def refine(self, transcript: str, options: list[dict], *, locale: str) -> OptionMatch | None: ...
  class LLMOptionRefiner:
      def __init__(self, client: "AbstractClient", *, timeout_s: float = 5.0) -> None: ...     # ai-parrot optional; verified: parrot/clients/base.py:1817
      async def refine(...) -> OptionMatch | None:
          """Structured output {value, confidence}; result ALWAYS surfaces as confirm_request (method="llm"), never a direct accept."""
  ```

### Module 5: Question planner
- **Path**: `audio/planner.py` (new)
- **Responsibility**: visible plan from the manifest + `RuleEvaluator.resolve()`; cap that keeps required fields; cursor; cascade clears; section boundaries; computed auto-accept.
- **Depends on**: Module 1, Module 2; existing `RuleEvaluator` (not modified).
- **Interface Skeleton**:
  ```python
  # audio/planner.py
  class PlanDelta(BaseModel): order: list[str]; hidden: list[str]; cleared: list[str]; required_changed: dict[str, bool]; hidden_by_cap: list[str]; entered_section: str | None; computed: dict[str, Any]
  class QuestionPlanner:
      def __init__(self, form: FormSchema, manifest: AudioFormManifest, cfg: VoiceFormConfig) -> None: ...
      async def replan(self, answers: dict[str, AudioAnswer], *, locale: str, resolution: RuleResolution | None = None) -> tuple[list[str], PlanDelta]:
          """Calls RuleEvaluator().resolve(form, unwrap(answers), locale=locale) (verified: services/rule_evaluator.py:578) when ``resolution`` is None;
          visible = manifest order ∩ resolution.visible; GROUP children inherit the parent's visibility (owner decision);
          cap = cfg.max_questions applied to visible keeping every required field (warning ``required_exceeds_cap``)."""
      def effective_required(self, field_id: str) -> bool:
          """Dynamic `RuleResolution.required` (S1a) — AudioQuestion.required is never the static flag."""
      def next_cursor(self, plan: list[str], answers: dict[str, AudioAnswer]) -> str | None:
          """First field_id in plan without an accepted answer; None → review."""
      def previous(self, plan: list[str], history: list[str], to_field_id: str | None) -> str | None: ...
  ```
  Note: `replan` is the one planner method that awaits (RuleEvaluator is async); the engine therefore emits a `Replan` outbound and receives `PlanReady` — the engine itself never awaits.

### Module 6: Audio segments & recordings
- **Path**: `audio/segments.py`, `audio/recordings.py` (new); `api/audio_ws.py:1237-1330`, `:1414` logic moved here.
- **Responsibility**: synthesis with one shared synthesiser per process behind a lock, per-session cache + process LRU; blob persistence of recordings with deterministic ids.
- **Depends on**: Module 2; existing `synthesize_with_fallback` (`renderers/audio.py:164`), `get_shared_synthesizer` (`tts/synthesizer.py:186`), `AbstractBlobStorage` (`services/blob_storage.py:119`).
- **Interface Skeleton**:
  ```python
  # audio/segments.py
  class AudioSegmentCache:
      def __init__(self, synthesizer: "VoiceSynthesizer | None", *, lock: asyncio.Lock, max_entries: int = 512) -> None: ...
      async def ensure(self, items: dict[str, str], *, locale: str, voice: str | None, form_uid: str, version: str) -> dict[str, bytes]:
          """Sequentially synthesise missing keys under the shared lock; cache key = (form_uid, version, locale, voice, template_rev, sha1(text)) (S7); returns key → bytes (WAV/MP3 per backend).
          Prefetch covers every question of the initial plan (owner decision); questions that become visible after a re-plan are synthesised lazily before their `question` message."""
      def mime(self) -> str: ...
  _SYNTH_LOCK: asyncio.Lock   # module-level, one per process (owner decision)
  # audio/recordings.py
  def recording_blob_id(session_id: str, field_uid: uuid.UUID) -> str:
      """``f"voice-{session_id}-{field_uid}"`` — matches BlobMetadata.blob_id regex (verified: services/blob_storage.py:93)."""
  async def store_recording(storage: AbstractBlobStorage, *, audio: bytes, mime: str, form: FormSchema, field: FormField, session_id: str, submission_id: str, tenant: str | None) -> str:
      """storage.put(iter([audio]), metadata=BlobMetadata(...)) → blob_ref (verified: services/blob_storage.py:131)."""
  async def delete_recording(storage: AbstractBlobStorage, blob_ref: str) -> None: ...
  ```

### Module 7: Session store (resume)
- **Path**: `audio/session_store.py` (new), `services/partial_saves.py` (modify: `remove_keys`)
- **Responsibility**: snapshot of the engine state under `parrot:audio:{form_uid}:{session_id}` plus the active-session marker; scalar answers go to the normal partial store so HTML can finish the form.
- **Depends on**: Module 2; existing `PartialSaveStore` (`services/partial_saves.py:24`, `_get_redis` `:195`).
- **Interface Skeleton**:
  ```python
  # services/partial_saves.py  (modifies after :145)
  class PartialSaveStore:                                                     # verified: services/partial_saves.py:24
      async def remove_keys(self, form_id: str, session_id: str, keys: Iterable[str]) -> PartialFormData | None:
          """Drop answer keys (cascade_clear); no-op without Redis, same TTL refresh as save()."""
  # audio/session_store.py
  AUDIO_KEY_PREFIX = "parrot:audio:"
  class AudioSnapshot(BaseModel): revision: int; form_version: str; phase, cursor, history, review_cursor, return_to_review, locale, config, blob_refs, answer_meta, plausibility, flagged, submission_id, user_id, tenant, saved_at, expires_at
  class AudioSessionStore:
      def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None: ...   # reuses partial_store._get_redis()
      async def save(self, form_uid: str, session_id: str, snapshot: AudioSnapshot, *, expected_revision: int | None = None) -> int:
          """Compare-and-set on ``revision`` (S5): raises SnapshotConflict when the stored revision differs; returns the new revision. Without Redis → RESUME_UNAVAILABLE on load, no-op on save."""
      async def load(self, form_uid: str, session_id: str) -> AudioSnapshot | None: ...
      async def delete(self, form_uid: str, session_id: str) -> None: ...
      async def claim_active(self, user_id: str, session_id: str) -> bool:
          """SET NX ``parrot:audio:active:{user_id}``; False when another session is active."""
  # resume rules (engine): verify user_id + tenant (RESUME_FORBIDDEN, no existence oracle), drop unknown field_uids and re-validate options (RESUME_STALE),
  # ALWAYS re-plan (never trust saved plan), drop pending, discard saved plausibility (re-run at review), reuse session_id (stable blob ids)
  ```

### Module 8: Answer plausibility checker (cross-cutting)
- **Path**: `services/plausibility.py` (new)
- **Responsibility**: eligibility, prompt construction, one batched structured-output LLM call, `on_error` semantics, report shaping.
- **Depends on**: Module 1; optional `parrot.clients.base.AbstractClient` (`ask(structured_output=…)`, `clients/base.py:1817-1826`).
- **Interface Skeleton**:
  ```python
  # services/plausibility.py
  class PlausibilityBatch(BaseModel):                      # structured-output schema sent to the LLM
      items: list[PlausibilityItemOut]                      # {field_id: str, plausible: bool, confidence: float, reason: str}
  class PlausibilityBlocked(Exception):
      """Raised only when cfg.on_error == "block" and the LLM is unavailable/timed out/unparsable."""
  def eligible_fields(form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None) -> list[FormField]:
      """llm_validation_enabled(form, field) ∧ answered (non-empty) ∧ not read_only ∧ field_type ∉ cfg.exclude_field_types ∧ not PASSWORD/HIDDEN;
      ordered required-first and cut at cfg.max_fields."""
  def build_items(form: FormSchema, fields: list[FormField], scalars: dict[str, Any], *, locale: str) -> list[dict[str, Any]]:
      """Per field: label, description, hint, field_type, option labels (SELECT family), answer rendered as text (lists joined; booleans localised).
      NEVER blobs, data_url or sensitive fields; no cross-field context (owner decision)."""
  class AnswerPlausibilityChecker:
      def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None: ...
      async def check(self, form: FormSchema, scalars: dict[str, Any], *, locale: str, fields: set[str] | None = None) -> PlausibilityReport:
          """One client.ask(prompt, structured_output=PlausibilityBatch) under asyncio.wait_for(config.timeout_s).
          client None / exception / unparsable → status "skipped" (on_error=skip) or raise PlausibilityBlocked (on_error=block).
          Verdicts for unknown field_ids dropped with a warning; confidence clamped to [0, 1]; never called with zero eligible fields (returns status ok, items {})."""
  ```

### Module 9: Submission pipeline & HTTP wiring
- **Path**: `services/submission_pipeline.py` (new), `services/validators.py` (modify), `api/handlers.py` (modify: `submit_data`, `validate`), `api/routes.py` (modify)
- **Responsibility**: behaviour-preserving extraction of `handlers.py:1818-1909`; plausibility step; envelope unwrap/rewrap; `llm_validation` opt-in on validate; `plausibility` block on both responses.
- **Depends on**: Module 1, Module 8; existing `FormValidator`, sinks, `dispatch`, `SubmissionForwarder`, `FormSubmissionStorage`.
- **Interface Skeleton**:
  ```python
  # services/submission_pipeline.py
  class SubmitOutcome(BaseModel): submission_id: str; stored_in: Literal["sink", "generic", "none"]; forwarded: bool; forward_status: int | None; forward_error: str | None; plausibility: PlausibilityReport | None; validation: ValidationResult
  class SubmissionPipeline:
      def __init__(self, *, validator: FormValidator, submission_storage: "FormSubmissionStorage | None", forwarder: "SubmissionForwarder | None",
                   partial_store: "PartialSaveStore | None", plausibility: AnswerPlausibilityChecker | None, logger: logging.Logger | None = None) -> None: ...
      async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str, auth_context: AuthContext | None, llm_validation: bool = False) -> tuple[ValidationResult, PlausibilityReport | None]:
          """unwrap_voice → FormValidator.validate (verified: services/validators.py:221) → optional plausibility (only when is_valid and form enables it)."""
      async def submit(self, form: FormSchema, data: dict[str, Any], *, tenant, user_id, locale, context, extra_data, auth_context, merge_session_id, plausibility: PlausibilityReport | None = None) -> SubmitOutcome:
          """validate → plausibility (unless a report is passed by the audio engine) → rewrap envelopes → FormSubmission(context[...]["llm_validation"]) →
          sink-exclusive (form.persistence, verified: api/handlers.py:1824) or FormSubmissionStorage.store → dispatch events → forwarder (verified :1887) → partial cleanup (verified :1900).
          Raises ValidationFailed(errors) — callers decide the HTTP/WS shape; raises PlausibilityBlocked when on_error=block."""
  # services/validators.py  (modifies :543-548 and :629-634)
  class FormValidator:
      @staticmethod
      def _is_voice_envelope_field(field: FormField) -> bool:   # verified: services/validators.py:543 — widened: answer_envelope == "voice" OR any field type when the value is a VoiceEvidenceEnvelope
      # coercion branch :629-634 → unwrap envelope, validate the scalar with the field's normal rules, re-fold via wrap_voice semantics
  # api/handlers.py  (modifies :1004 validate, :1498 submit_data)
  #   validate: body/query "llm_validation": true → pipeline.validate(..., llm_validation=True); response {"is_valid", "errors", "plausibility"?}; A2UI branch unchanged + "plausibility" in the envelope data
  #   submit_data: lines 1818-1909 replaced by pipeline.submit(); response gains "plausibility" when present; 422 shape unchanged
  # api/routes.py  (modifies :192-205 and :473-496)
  #   setup_form_api(..., client=...) builds SubmissionPipeline once (app["submission_pipeline"]) and passes blob_storage, partial_store, pipeline to AudioFormWSHandler
  ```

### Module 10: Audio form session engine
- **Path**: `audio/engine.py` (new)
- **Responsibility**: the pure state machine; composes Modules 2–5; produces I/O requests for Module 11.
- **Depends on**: Modules 2, 3, 4, 5; Module 8's `PlausibilityReport` type (via Module 1).
- **Interface Skeleton**:
  ```python
  # audio/engine.py
  class EngineError(Exception): code: str
  class AudioFormSession:
      def __init__(self, *, form: FormSchema, manifest: AudioFormManifest, cfg: VoiceFormConfig, narrator: Narrator, lexicon: Lexicon,
                   state: AudioSessionState, llm_cfg: LLMValidationConfig | None) -> None: ...
      def handle(self, event: InboundEvent) -> list[Outbound]:
          """Dispatch on (state.phase, event.type); mutates state; returns wire messages + I/O requests. Never awaits, never raises for client errors (emits Error)."""
      # phase handlers (pure):
      def on_start(self, ev: StartSession) -> list[Outbound]           # → Replan + Synthesize(sys + first N questions) + SessionStarted
      def on_plan_ready(self, ev: PlanReady) -> list[Outbound]         # → Question | ReviewStart | PlanUpdated/SectionEnter/QuestionSkipped/AnswerCleared(+DeleteBlob)
      def on_transcript(self, ev: TranscriptReady) -> list[Outbound]   # classify_command → CommandAck+effect | match_option → AnswerAccepted(+StoreBlob)+Replan | ConfirmRequest | AnswerRejected
      def on_selection / on_text / on_payload / on_confirm / on_skip / on_back / on_repeat(...)
      def on_review_prompt_answer(self, ev: TranscriptReady) -> list[Outbound]  # yes → RunPlausibility already done → Submit; 'cambiar N' → ReviewEdit path
      def on_plausibility_done(self, ev: PlausibilityDone) -> list[Outbound]    # flags (confidence < threshold, once per answer version) → ReviewStart(items with flag) ; status skipped → unflagged review
      def on_review_confirm / on_review_edit(...)                     # review_edit → ASKING(field) → on accept → RunPlausibility(fields={field}) (delta) → REVIEW
      def on_submit_done(self, ev: SubmitDone) -> list[Outbound]       # FormComplete | ValidationErrors(+ASKING first_field_id, return_to_review)
      def snapshot(self) -> AudioSnapshot: ...
      @classmethod
      def from_snapshot(cls, snap: AudioSnapshot, **deps) -> "AudioFormSession": ...   # then on_start re-plans
  ```
  Invariants (tested): no `await` in `audio/engine.py`; every accepted answer triggers `Replan`; `Submit` is only emitted from REVIEW with `confirmed=True` or when `cfg.review == "never"`; `is_sensitive()` answers never appear in `ReviewItem.answer_text` ("[hidden]"), in `RunPlausibility.fields`, in logs, nor unmasked in `FormComplete` (S8); an answer for a field other than the cursor is `WRONG_FIELD` and re-answers bump `AudioAnswer.version` (S6 duplicate handling).

### Module 11: WebSocket adapter
- **Path**: `api/audio_ws.py` (rewrite in place), `api/routes.py` (modify wiring)
- **Responsibility**: auth (moved verbatim from `:282-347`), tenant from URL, JSON/binary decode, `engine.handle()`, I/O for each outbound kind, encode (v1 shapes preserved; `audio` base64 only when `protocol_version == 1` or `prefetch=False`), snapshot autosave after every transition and in `finally`.
- **Depends on**: Modules 6, 7, 9, 10.
- **Interface Skeleton**:
  ```python
  # api/audio_ws.py  (rewrites class at api/audio_ws.py:102; keeps module constants :59-:100 and _sniff_audio_suffix :71)
  class AudioFormWSHandler:                                                   # verified: api/audio_ws.py:102
      def __init__(self, registry: "FormRegistry", synthesizer: "VoiceSynthesizer | None", transcriber: "AbstractTranscriberBackend | None", validator: "FormValidator", *,
                   token_validator: "TokenValidator | None" = None, pipeline: SubmissionPipeline | None = None, blob_storage: "AbstractBlobStorage | None" = None,
                   session_store: AudioSessionStore | None = None, plausibility: AnswerPlausibilityChecker | None = None, max_msg_size: int = 10 * 1024 * 1024) -> None: ...
      async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse: ...   # route target unchanged (verified: api/routes.py:493-494)
      # S11: the authenticated user (parrot.core.ws_auth.AuthenticatedUser) is mapped to AuthContext and passed to pipeline.submit(auth_context=…); tenant comes from the URL.
      async def _perform(self, ws, session: AudioFormSession, outbound: list[Outbound]) -> None:
          """Wire messages → ws.send_json / send_bytes (AudioSegment header then binary); I/O requests → await then feed *_Done/IOFailed back into session.handle()."""
  ```

### Module 12: Sinks JSONB & migrations
- **Path**: `services/sinks/mapper.py`, `services/sinks/postgres_table.py` (modify); `packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql`, `009_voice_envelope_sink_tables.py`, `010_voice_envelope_report.py`, `migrations/README.md` (new/modify)
- **Responsibility**: envelope-capable columns are JSONB; legacy normalisation; scalar view; inventory/orphan report.
- **Depends on**: Module 1 (`is_voice_envelope`, `unwrap_voice`).
- **Interface Skeleton**:
  ```python
  # services/sinks/postgres_table.py  (modifies :79 neighbourhood and :322)
  def _ddl_type_for(field_type: FieldType, *, voice: bool = False) -> str:   # verified: postgres_table.py:85 — voice=True → "JSONB"
  # jsonb_columns = {"context", "extra_data"} | {voice-capable field columns}  (verified: :322)
  # services/sinks/mapper.py  (modifies :176)
  def _extract_value(data, column_name, field) -> Any:   # verified: mapper.py:176 — envelope dict → json.dumps (like ARRAY :209); CSV/GSheet receive the JSON string
  # migrations/009_voice_envelope_form_data.sql  — CREATE FUNCTION fd_unwrap_voice(jsonb) RETURNS jsonb; CREATE VIEW form_data_scalar AS ...; UPDATE form_data SET data = ... (legacy strings on answer_envelope="voice" fields → {"answer": s, "blob_ref": null}) — idempotent
  # migrations/009_voice_envelope_sink_tables.py  — argparse --dsn --schema --batch-size --dry-run (pattern 003_migrate_form_data.py); per form_schemas.persistence table: ALTER TABLE … ALTER COLUMN <col> TYPE JSONB USING jsonb_build_object('answer', <col>)
  # migrations/010_voice_envelope_report.py      — --dsn --schema --blob-url [--apply --downgrade]: envelope inventory, orphan blob_refs, reversible downgrade
  ```

### Module 13: Renderers `hint`, toolkit fields, design-time optimiser
- **Path**: `renderers/audio.py`, `renderers/html5.py`, `renderers/jsonschema.py`, `renderers/adaptive_card.py`, `renderers/a2ui.py`, `renderers/pdf.py` (modify); `tools/edit_toolkit.py`, `api/operations.py`, `extractors/yaml.py`, `tools/create_form.py` (modify — S9: `hint`/`llm_validation` round-trip through YAML extraction and the creation prompt); `api/handlers.py` (`optimize_voice`), `api/routes.py` (route) (modify); `tools/voice_optimizer.py` (new)
- **Responsibility**: `hint` exposure everywhere; `hint`/`llm_validation` editable; proposals-only optimiser with a deterministic matcher self-test.
- **Depends on**: Modules 1, 3, 4.
- **Interface Skeleton**:
  ```python
  # renderers/audio.py  (modifies :277 split_into_questions / :359-383 question build)
  #   AudioQuestion += section_uid/section_title/subsection_title, hint (resolved), prompt (render_author_prompt), ui_cue, answer_modes, voice_meta, llm_validation; options[] entries gain "disabled": bool (S4, verified drop at renderers/audio.py:343-349); required = dynamic (S1a)
  # renderers/html5.py:714 → <small class="hint">; renderers/jsonschema.py:428 → "x-hint"; renderers/adaptive_card.py (field block) → TextBlock isSubtle; renderers/a2ui.py → Text(hint) under the control; pdf → italic line
  # tools/edit_toolkit.py  (modifies :318)
  #   async def update_field(..., hint: dict[str, str] | str | None = None, llm_validation: bool | None = None, ...)   # verified: tools/edit_toolkit.py:318
  #   async def propose_voice_hints(self, form_uid: str, *, locale: str = "en", fields: list[str] | None = None, style: str = "concise", max_hint_words: int = 20) -> dict
  # tools/voice_optimizer.py (new)
  class VoiceHintProposal(BaseModel): field_uid: uuid.UUID; hint: dict[str, str]; prompt: str | None; enumerate: str; llm_validation: bool | None; rationale: str; warnings: list[str]
  class VoiceOptimizer:
      def __init__(self, client: "AbstractClient", narrator_factory: Callable[[str], Narrator]) -> None: ...
      async def propose(self, form: FormSchema, *, locale: str, fields: set[str] | None, style: str, max_hint_words: int) -> tuple[list[VoiceHintProposal], dict[str, str]]:
          """Structured output; returns proposals + narration_preview. NEVER writes (owner decision)."""
      def self_test(self, form: FormSchema, lexicon: Lexicon) -> list[str]:
          """Deterministic: option-label fuzzy collisions ≥ 0.8 and command collisions; runs without an LLM."""
  # api/handlers.py — async def optimize_voice(self, request) -> web.Response   (POST {tp}/forms/{form_uid}/voice/optimize, _wrap_auth; 503 when _get_llm_client() is None)
  ```

### Module 14: Docs & handoff sync
- **Path**: `docs/audio-form-voice-modes.md` (modify §6, §7, §10; mark §9.10/9.11 superseded), `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` (modify: frozen v2 tables)
- **Responsibility**: protocol v2 reference, plausibility and commands documented from `audio/events.py`; handoff kept identical to the implemented wire.
- **Depends on**: Modules 2, 11.
- **Interface Skeleton**: n/a (documentation) — a test asserts every `Outbound`/`InboundEvent` `type` literal appears in `docs/audio-form-voice-modes.md` §7.

---

## 4. Test Specification

Tests live in `packages/parrot-formdesigner/tests/formdesigner/` (existing `test_audio_*.py`
siblings) unless noted. Run with `PYTHONPATH=packages/parrot-formdesigner/src` inside a worktree.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_schema_hint_and_llm_validation_fields` | M1 | `FormField.hint`/`llm_validation` round-trip; `FormSchema.voice`/`llm_validation` typed blocks; unknown keys in `meta["voice"]` ignored with one warning |
| `test_voice_evidence_envelope_subclass` | M1 | `VoiceAnswerEnvelope` contract unchanged (`answer: str`, extra forbid); subclass accepts `answer: list|bool`; `unwrap_voice`/`wrap_voice` idempotent |
| `test_events_discriminated_union_and_forbid` | M2 | every `type` literal unique; unknown inbound key rejected; v1 message shapes still parse |
| `test_narration_conformance_all_locales` | M3 | every `NARRATION_KEYS` key present in `en` and `es`; fallback `es-MX → es → en`; `StrictUndefined` raises on a missing variable |
| `test_author_prompt_is_not_jinja` | M3 | `{{ 7*7 }}` rendered verbatim; whitelist placeholders substituted |
| `test_match_option_methods_and_thresholds` | M4 | exact / ordinal ("la segunda", "opción 3", "última") / yes-no / numeric / contains / fuzzy; 0.8 accept, 0.6–0.8 confirm, <0.6 no_match; `stt_confidence=None → 1.0` |
| `test_match_multi_select_conjunctions` | M4 | "A y C", "todas", "ninguna" → lists |
| `test_classify_command_phase_gating_and_precedence` | M4 | commands only as whole short utterances; exact option beats command in PROMPT_SELECT; `commands: off` disables |
| `test_command_option_collisions_enumerated` | M4 | lexicon vs option labels report |
| `test_planner_cap_keeps_required` | M5 | `max_questions=3` with 4 required → 4 visible + `required_exceeds_cap` warning; `hidden_by_cap` lists optional ones |
| `test_planner_replan_cascade_clear_and_sections` | M5 | `RuleEvaluator` stub: hidden field answer cleared; `section_enter` on boundary; GROUP children inherit parent visibility |
| `test_segment_cache_shared_lock_and_key` | M6 | two sessions share one synthesiser; identical text synthesised once; key includes locale/voice/version |
| `test_recording_blob_id_deterministic` | M6 | re-answer overwrites same `blob_ref`; `store_recordings=False` → `blob_ref=None`, never `data_url` |
| `test_session_store_roundtrip_and_claim` | M7 | snapshot save/load/delete over a fake Redis; `claim_active` NX semantics; `remove_keys` on `PartialSaveStore` |
| `test_plausibility_eligibility_and_prompt_privacy` | M8 | sensitive/HIDDEN/read_only/disabled excluded; prompt contains no `blob_ref`/`data_url`; required-first cut at `max_fields` |
| `test_plausibility_on_error_skip_and_block` | M8 | client None / timeout / bad JSON → `skipped` or `PlausibilityBlocked`; unknown field_id dropped; confidence clamped |
| `test_plausibility_single_batched_call` | M8 | fake client asserts exactly one `ask()` with `structured_output` |
| `test_submission_pipeline_parity_with_submit_data` | M9 | golden fixtures from existing `submit_data` tests: sink-exclusive path, generic path, events order, forwarder, partial cleanup identical before/after extraction |
| `test_validate_endpoint_llm_validation_opt_in` | M9 | without flag no LLM call; with flag `plausibility` block present; HTTP status unaffected by low confidence |
| `test_submit_response_and_context_llm_validation` | M9 | `plausibility` in response and `context["llm_validation"]`; spoken envelope carries `plausibility` |
| `test_validator_envelope_any_type` | M9 | envelope on SELECT/BOOLEAN/NUMBER validated through the scalar; TEXT with `answer_envelope="voice"` unchanged |
| `test_engine_has_no_await` | M10 | AST scan of `audio/engine.py`: no `Await`/`AsyncFunctionDef` |
| `test_engine_turn_flow_voice_select_fallback` | M10 | scripted events → expected outbound sequences for the three voice modes |
| `test_engine_review_flag_and_edit_delta` | M10 | low-confidence item flagged once; `review_edit` → ASKING → `RunPlausibility(fields={field})` → REVIEW; kept answer not re-flagged |
| `test_engine_review_voice_or_button_and_sensitive_hidden` | M10 | "sí/ok/enviar" and `review_confirm` both submit; sensitive item reads "[hidden]" and is excluded from plausibility |
| `test_engine_resume_replans_and_rejects` | M10 | `from_snapshot` re-plans; wrong user → `RESUME_FORBIDDEN`; changed form → `RESUME_STALE` |
| `test_sink_ddl_jsonb_for_voice_fields` | M12 | DDL emits JSONB; `jsonb_columns` includes voice fields; `_extract_value` serialises envelopes |
| `test_migration_009_sql_idempotent` | M12 | SQL text parses (sqlglot/regex) and re-running the UPDATE is a no-op on fixture rows (asyncpg optional, skipped without DB) |
| `test_renderers_expose_hint` | M13 | HTML5 `<small class="hint">`, JSON Schema `x-hint`, Adaptive Card subtle block, A2UI Text, PDF line |
| `test_edit_toolkit_hint_and_llm_validation` | M13 | `update_field(hint=..., llm_validation=...)` persists through `api/operations.py` |
| `test_voice_optimizer_proposals_only_and_self_test` | M13 | `propose` never calls storage; `self_test` reports collisions without a client |
| `test_docs_list_every_protocol_type` | M14 | every event `type` literal appears in `docs/audio-form-voice-modes.md` §7 |
| `test_match_option_skips_disabled_and_ties_confirm` | M4 | disabled options never matched; equal-score tie → `confirm` with alternatives (S4) |
| `test_envelope_coercion_number_boolean_select` | M9 | NUMBER/BOOLEAN/SELECT/MULTI_SELECT envelopes validate through the scalar and re-fold (S3) |
| `test_snapshot_cas_conflict` | M7 | stale `expected_revision` raises `SnapshotConflict`; load validates tenant/user/form_version (S5) |
| `test_legacy_inbound_ignores_unknown_keys` | M2/M11 | v1 `start_session` with extra keys accepted; v2 rejected (S6) |
| `test_sensitive_policy_everywhere` | M1/M10 | `is_sensitive` masks narration, review, plausibility input, logs and `form_complete` (S8) |
| `test_generic_storage_and_sink_envelope_paths` | M12 | envelope stored in `form_data.data` JSONB and in a per-form JSONB column; legacy string normalised (S10) |
| `test_yaml_extractor_and_create_form_hint_roundtrip` | M13 | `hint`/`llm_validation` survive `extractors/yaml.py` and the creation prompt schema (S9) |

### Integration Tests
| Test | Description |
|---|---|
| `test_audio_ws_v1_client_still_works` | existing `test_audio_ws_handler.py` / `test_audio_integration.py` fixtures pass unchanged against the adapter (base64 `audio`, v1 message names) |
| `test_audio_ws_v2_prefetch_review_submit` | aiohttp test client: `protocol_version: 2` → `audio_segment` batch, questions, `review_start`, `plausibility_result` (fake checker), `review_confirm` → `form_complete`; submission reached sinks/events via the pipeline with tenant |
| `test_audio_ws_commands_and_go_back` | binary "repetir"/"atrás" transcripts (fake transcriber) → `command_ack` + effects |
| `test_audio_ws_resume_cross_channel` | disconnect mid-form, `start_session{resume_session_id}` → `session_resumed`; `/partial` + `merge_partials` completes the same answers over HTTP |
| `test_http_submit_with_plausibility_block_mode` | `on_error: block` + unavailable client → retryable error; `skip` → stored with `skipped` |
| `test_audio_adversarial_suite` | hidden/required flips mid-session, disabled option by voice, duplicate binary after cursor moved (`WRONG_FIELD`), sensitive answer never echoed, v1 client with extra keys (S12) |

### Test Data / Fixtures
```python
@pytest.fixture
def voice_form() -> FormSchema: ...          # 2 sections, SELECT with 4 options (one labelled "Saltar"), BOOLEAN, TEXT with hint, PASSWORD, GROUP with children, depends_on chain
@pytest.fixture
def fake_transcriber():                      # returns scripted TranscriptionResult(text, confidence|None)
@pytest.fixture
def fake_synthesizer():                      # returns deterministic WAV bytes per text; counts calls
@pytest.fixture
def fake_llm_client():                       # AbstractClient stub recording ask() calls; configurable PlausibilityBatch / exception / timeout
@pytest.fixture
def fake_redis():                            # dict-backed stub honouring SET NX / EXPIRE used by PartialSaveStore/AudioSessionStore (fakeredis is NOT installed)
@pytest.fixture
def memory_blob_storage():                   # AbstractBlobStorage over a dict
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `pytest packages/parrot-formdesigner/tests -q` passes, including the unchanged FEAT-224/236 audio tests (v1 compatibility) and the new tests in §4.
- [ ] AC2. `audio/engine.py` contains no `await` (AST test) and every transition is reproducible from a scripted event list.
- [ ] AC3. A v1 client (`protocol_version` absent) receives base64 `audio` in `question` and the v1 message names; a v2 client receives `audio_segment` header+binary frames for every planned question before the first `question`.
- [ ] AC4. `FormField.hint` is narrated after a `pause:<hint_pause_ms>` segment and rendered by HTML5, JSON Schema, Adaptive Card, A2UI and PDF renderers; `description`/`placeholder` are never silently dropped from narration when `hint` is absent (description narrated).
- [ ] AC5. `max_questions` never hides a required field; `hidden_by_cap` and `required_exceeds_cap` are reported; `MAX_QUESTIONS` module constant is gone.
- [ ] AC6. A spoken answer on a SELECT is matched by label / ordinal / number and stored as the option **value** (never the raw transcript); disabled options are never matched; ties yield `confirm_request`; MULTI_SELECT by voice is stored as a **list**.
- [ ] AC7. After each accepted answer `RuleEvaluator.resolve()` is re-run; hidden fields are skipped, `cascade_clear` clears answers and deletes their blobs; sections emit `section_enter`; `RuleEvaluator` source is unchanged.
- [ ] AC8. Every spoken answer (any field type — NUMBER/BOOLEAN/SELECT envelopes validate through their scalar) is stored as `VoiceEvidenceEnvelope` in `data[field_id]` with `blob_ref` to the recording (`blob_id = voice-{session_id}-{field_uid}`); typed/selected answers are flat scalars; `data_url` is never produced server-side; `VoiceAnswerEnvelope` (FEAT-488) tests pass unchanged.
- [ ] AC9. The audio submit goes through `SubmissionPipeline.submit()`: tenant preserved, FEAT-457 sink exclusivity, FEAT-188 events, forwarder and partial cleanup identical to `submit_data` (parity test), `FormValidator.validate()` runs and failures return `validation_errors` without storing.
- [ ] AC10. **Plausibility — declaration**: `FormField.llm_validation` (None inherits) and typed `FormSchema.llm_validation` exist; disabled forms make zero LLM calls on any channel.
- [ ] AC11. **Plausibility — invocation**: exactly one `AbstractClient.ask(structured_output=…)` call per submit (plus one delta call per `review_edit` batch); input contains label/description/hint/type/options/scalar only; sensitive, HIDDEN, read_only and excluded types are absent; no `blob_ref`/`data_url` ever reaches the prompt.
- [ ] AC12. **Plausibility — outcome**: low confidence never changes HTTP status or blocks `review_confirm`; audio flags the item once per answer version and re-asks on request; HTTP returns the additive `plausibility` block on `POST …/data` and on `POST …/validate` when `llm_validation: true`; the report is persisted in `context["llm_validation"]` and in spoken envelopes.
- [ ] AC13. **Plausibility — failure**: `on_error: skip` (default) proceeds with `status: skipped` + reason; `on_error: block` fails the submit with a retryable error (HTTP 503-class / WS `PLAUSIBILITY_UNAVAILABLE`) and nothing is stored.
- [ ] AC14. Hands-free: `session_started.hands_free{auto_record, silence_ms}` and `max_recording_seconds` are sent; repeat/back/skip/help/stop/next/send/"cambiar N" transcripts yield `command_ack` + the v1 effect; an exact option match beats a command; `meta.voice.commands: off` disables commands on that field.
- [ ] AC15. Review: items narrated with position; sensitive read as "[hidden]"; confirmation by voice ("sí/ok/enviar") or `review_confirm`; "cambiar la N" re-asks and returns to review.
- [ ] AC16. Resume: `start_session{resume_session_id}` restores answers and phase, re-plans, uses compare-and-set snapshots (`revision`), rejects wrong user/tenant (`RESUME_FORBIDDEN`) and changed forms (`RESUME_STALE`); one active session per user; scalar answers are visible to HTTP `/partial` + `merge_partials`; the audio snapshot is **not** exposed by `/partial`.
- [ ] AC17. One shared synthesiser per process guarded by a lock; synthesis of identical text happens once per `(form_uid, version, locale, voice, text)`.
- [ ] AC18. Migration 009 converts envelope-capable per-form sink columns to JSONB and normalises legacy voice strings idempotently with `--dry-run`; `fd_unwrap_voice` + `form_data_scalar` exist; migration 010 reports envelopes and orphan `blob_ref`s and supports `--downgrade`; sink DDL emits JSONB for voice-capable fields going forward.
- [ ] AC19. `POST …/voice/optimize` returns proposals and a narration preview and performs no write; its matcher self-test runs without an LLM; `EditToolkit.update_field` accepts `hint` and `llm_validation`.
- [ ] AC20. `docs/audio-form-voice-modes.md` documents every v2 message, the plausibility and command flows, and the error codes; the handoff brief tables match `audio/events.py` literal-for-literal.
- [ ] AC21. No import of `requests`/`httpx`/langchain; `parrot.voice.*` and `parrot.clients.*` remain optional (`TYPE_CHECKING` / lazy import); `ruff check` passes on every touched file; `parrot/clients/base.py` untouched.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified on `dev @ dc54b7ae6` (code identical to
> `b288daa72`). Paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/` unless
> prefixed with `packages/`.

### Verified Imports
```python
# parrot-formdesigner (internal)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, walk_fields   # core/schema.py:65, :401, :229, :195, :267
from parrot_formdesigner.core.types import FieldType                                                          # core/types.py:16
from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope                                         # core/voice_answer.py:13 ; re-exported core/__init__.py:53,:60
from parrot_formdesigner.core.constraints import DependencyRule, PostDependency, LogicGroup                   # core/constraints.py:216, :334, :193
from parrot_formdesigner.core.persistence import FormPersistenceConfig                                        # core/persistence.py:226
from parrot_formdesigner.services.validators import FormValidator, ValidationResult                           # services/validators.py:200, :160
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator, RuleResolution                         # services/rule_evaluator.py:555, :53
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage, BlobMetadata                       # services/blob_storage.py:119, :55
from parrot_formdesigner.services.partial_saves import PartialSaveStore                                       # services/partial_saves.py:24
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage                    # services/submissions.py:50, :122
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission                     # services/sinks/mapper.py:142 ; nest_submission used at api/handlers.py:1853
from parrot_formdesigner.services.event_dispatcher import dispatch, apply_schema_overrides                    # imported at api/handlers.py:27
from parrot_formdesigner.services.forwarder import SubmissionForwarder                                       # services/forwarder.py:36
from parrot_formdesigner.services.registry import FormRegistry                                               # services/registry.py:240
from parrot_formdesigner.services.auth_context import AuthContext                                            # services/auth_context.py:20
from parrot_formdesigner.audio.models import VoiceMode, AudioSessionConfig, AudioQuestion, AudioFormManifest, AudioAnswer, AudioSessionState   # audio/models.py:18,:38,:72,:128,:153,:179 ; audio/__init__.py exports all but VoiceMode
from parrot_formdesigner.renderers.audio import AudioFormRenderer, classify_voice_mode, synthesize_with_fallback   # renderers/audio.py:242, :95, :164
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler, MAX_QUESTIONS, _sniff_audio_suffix          # api/audio_ws.py:102, :59, :71
from parrot_formdesigner.api import a2ui_wire                                                                 # api/a2ui_wire.py (used api/handlers.py:1038)

# optional — guard with TYPE_CHECKING / lazy import (pattern api/audio_ws.py:47-54, api/handlers.py:93, :209)
from parrot.clients.base import AbstractClient                                   # packages/ai-parrot/src/parrot/clients/base.py
from parrot.clients.google import GoogleGenAIClient                              # used api/handlers.py:209
from parrot.models import StructuredOutputConfig, OutputFormat                   # re-exported; clients/base.py:50 ; defs models/outputs.py:59, models/basic.py:12
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator                # packages/ai-parrot/src/parrot/core/ws_auth.py:44
from parrot.voice.tts.synthesizer import VoiceSynthesizer, get_shared_synthesizer, close_shared_synthesizers   # packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:23, :186, :213
from parrot.voice.tts.models import TTSConfig                                    # tts/models.py:47 (backend Literal)
from parrot.voice.transcriber.backend import AbstractTranscriberBackend          # transcriber/backend.py:18
from parrot.voice.transcriber.models import TranscriberBackend, TranscriptionResult   # transcriber/models.py:16, :90
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend # transcriber/faster_whisper_backend.py:21
```

### Existing Class Signatures
```python
# core/schema.py
class FormField(BaseModel):                                                 # :65 ; model_config = ConfigDict(extra="forbid") :121
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)                # :123
    field_id: str; field_type: FieldType                                    # :124-125
    label: LocalizedString; description: LocalizedString | None = None; placeholder: LocalizedString | None = None   # :126-128
    required: bool = False; read_only: bool = False                         # :129, :131
    options: list[FieldOption] | None = None                                # :133
    depends_on: DependencyRule | None = None; post_depends: list[PostDependency] | None = None   # :135-136
    meta: dict[str, Any] | None = None                                      # :140
    content_type: str | None = None; accept_content_types: list[str] | None = None   # :141-142
    answer_envelope: Literal["voice"] | None = None                         # :143  ← anchor for M1 additions
class FormSubsection(BaseModel): fields: list[FormField]                    # :195, :221 ; extra="forbid" :215
SectionItem = Union[FormField, FormSubsection]                              # :226
class FormSection(BaseModel): fields: list[SectionItem]                     # :229, :254
def walk_fields(items: Iterable[SectionItem]) -> Iterator[FormField]        # :267
class FormSchema(BaseModel):                                                # :401 — NO model_config (pydantic default extra="ignore")
    form_uid: uuid.UUID; form_id: str; version: str = "1.0"                 # :453-455
    description: LocalizedString | None; meta: dict[str, Any] | None        # :457, :461
    events: FormEventsConfig | None = None                                  # :465
    persistence: FormPersistenceConfig | None = None                        # :473
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP          # :475  ← anchor for M1 additions
    def iter_all_fields(self) -> Iterator[FormField]                        # :477  (does NOT recurse GROUP children)
    def iter_fields_recursive(self) -> Iterator[FormField]                  # :490

# core/voice_answer.py (FEAT-488)
class VoiceAnswerEnvelope(BaseModel):                                       # :13 ; extra="forbid"
    answer: str; blob_ref: str | None = None; data_url: str | None = None

# services/validators.py
class ValidationResult(BaseModel):                                          # :160
    is_valid: bool; errors: dict[str, list[str]]; sanitized_data: dict[str, Any]; extra_data: dict[str, Any] = Field(default_factory=dict)   # :174-177
class FormValidator:                                                        # :200
    def __init__(self) -> None                                              # :217 (no client)
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en", auth_context: AuthContext | None = None,
                       location_vars: dict[str, Any] | None = None, visit_context: dict[str, Any] | None = None) -> ValidationResult   # :221-229
    async def validate_field(...)                                           # :351
    @staticmethod
    def _is_voice_envelope_field(field: FormField) -> bool                  # :543-548 (answer_envelope == "voice" and TEXT/TEXT_AREA)
    # :629-634  if field.answer_envelope == "voice": ... VoiceAnswerEnvelope.model_validate(value).model_dump()
    def validate_rules(self, form: FormSchema) -> list[str]                 # :1382

# services/rule_evaluator.py
class RuleResolution(BaseModel)                                             # :53 (visible, required, computed, cleared)
class RuleEvaluator:                                                        # :555
    async def resolve(self, form, answers, *, locale, location_vars, visit_context) -> RuleResolution   # :578 ; all_fields = list(form.iter_all_fields()) :598

# services/blob_storage.py
class BlobMetadata(BaseModel):                                              # :55 ; blob_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$") :93
class AbstractBlobStorage(ABC):                                             # :119
    async def put(self, stream, *, metadata: BlobMetadata) -> str           # :131
    async def get(self, blob_ref: str) -> AsyncIterator[bytes]              # :158
    async def delete(self, blob_ref: str) -> None                           # :169
    # key = f"{prefix}{form_uid}/{field_uid}/{blob_id or uuid4}"            # :241-242

# services/partial_saves.py
class PartialSaveStore:                                                     # :24 ; REDIS_KEY_PREFIX = "parrot:partial:" :50
    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None) -> None   # :52-55
    async def save(...)  # :67   async def get(...)  # :123   async def delete(...)  # :145
    async def _get_redis(self) -> Any | None   # :195      async def _redis_set(self, redis, partial: PartialFormData) -> None   # :218

# services/submissions.py
class FormSubmission(BaseModel):                                            # :50
    submission_id: str; form_version: str; data: dict[str, Any]; is_valid: bool   # :93-101
    tenant: str | None = None; context: dict[str, Any] | None = None; extra_data: dict[str, Any] | None = None   # :108, :118-119
class FormSubmissionStorage:                                                # :122
    async def store(self, submission, *, tenant: str | None = None, ...) -> str   # :313-317

# services/sinks
def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]   # mapper.py:142
def _extract_value(data, column_name, field) -> Any                         # mapper.py:176 ; json.dumps only for ARRAY :209
_DEFAULT_DDL_TYPE = "TEXT"                                                  # postgres_table.py:79 ; _ddl_type_for :85
# jsonb_columns = {"context", "extra_data"} | {...}; non-str values json.dumps'd   # postgres_table.py:322-331

# services/forwarder.py / registry.py / auth_context.py
class SubmissionForwarder: async def forward(self, outbound, submit) -> ...  # :36, :61
class FormRegistry: async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None   # :240, :976
class AuthContext(BaseModel)                                                # auth_context.py:20

# api/handlers.py
class FormAPIHandler:
    def __init__(..., client: "AbstractClient | None" = None, submission_storage=None, forwarder=None, ...)   # :147-149 ; self._partial_store :167
    def _get_llm_client(self) -> "AbstractClient | None"                     # :197-215 (lazy GoogleGenAIClient default)
    async def validate(self, request: web.Request) -> web.Response           # :1004 ; A2UI dual-wire :1013-1044 ; response {"is_valid", "errors"} 200/422
    async def submit_data(self, request: web.Request) -> web.Response        # :1498 ; sinks exclusive :1824 ; nest/flatten :1853-1855 ; forwarder :1879-1888 ; partial cleanup :1900-1902 ; response "submission_id","is_valid"

# api/routes.py
def setup_form_api(app, ..., blob_storage=None, partial_store=None, synthesizer=None, transcriber=None, token_validator=None) -> None   # :192-205
# route f"{tp}/forms/{{form_uid}}/validate"  :415 ; AudioFormWSHandler import :480, construction :483-491, route f"{tp}/forms/{{form_uid}}/audio/ws" :493-494

# api/audio_ws.py
MAX_QUESTIONS = 10  # :59 ; _MIN_AUDIO_BYTES = 256  # :68 ; def _sniff_audio_suffix(data: bytes) -> Optional[str]  # :71
class AudioFormWSHandler:                                                    # :102
    def __init__(self, registry: "FormRegistry", synthesizer: Optional["VoiceSynthesizer"], transcriber: Optional["FasterWhisperBackend"], validator: "FormValidator", *,
                 token_validator: Optional["TokenValidator"] = None, submission_storage: Optional["FormSubmissionStorage"] = None, max_msg_size: int = 10*1024*1024, ...)   # :143-161
    async def _authenticate(...)  # :282 (header :309-310, first "auth" msg :324-330)     async def _dispatch_text(...)  # :349 ("confirm_answer" :373)
    # questions[:MAX_QUESTIONS] :490 ; ",".join(values) :595 ; _handle_confirm_answer :637 ; _handle_answer_audio :691 (EMPTY_AUDIO :730, UNSUPPORTED_AUDIO :738, AUDIO_DECODE_ERROR :770, confirm_request :812)
    # _accept_answer :1009 ; _advance_session :1072 ; _advance_session_no_request :1094 ; _finish_session :1115 (registry.get tenant=None :1138, FormSubmission :1141, store :1149, form_complete :1158)
    # _send_question :1167 ; _synthesize :1237 ; _auto_synthesize_cached :1271 ; _narration_text :1333 ; _presynthize_to_cache :1414 ; _audio_cache: dict[int, str] :230

# audio/models.py
class VoiceMode(str, Enum)  # :18        class AudioSessionConfig(BaseModel)  # :38 ; stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0) :69
class AudioQuestion(BaseModel)  # :72 (index, field_id, field_uid, field_type, label, description, required, audio_prompt, constraints, options, voice_mode, render_mode, sensitive, fallback_html, accept_content_types, answer_envelope)
class AudioFormManifest(BaseModel)  # :128
class AudioAnswer(BaseModel)  # :153 ; value: str :173 ; source: Literal["text","speech","selection"] :174 ; confidence: Optional[float] :175
class AudioSessionState(BaseModel)  # :179 ; session_id, form_uid, user_id, current_index: int = 0 :206, answers, manifest, completed, config

# renderers/audio.py
_SKIP_FIELD_TYPES = frozenset({FieldType.HIDDEN})  # :36 ; def classify_voice_mode(field) -> VoiceMode  # :95 (meta["voice_mode"] :109)
def build_audio_synthesizer(...)  # :131 ; async def synthesize_with_fallback(...)  # :164 ; def _resolve(value, locale="en") -> str  # :218
class AudioFormRenderer(AbstractFormRenderer):  # :242 ; def split_into_questions(self, form, ...)  # :277 (iter_all_fields :299, GROUP :331, sensitive = PASSWORD :361)

# other anchors
renderers/a2ui.py:238 AUDIO → "notice" ; renderers/html5.py:714 description resolve ; renderers/jsonschema.py:428 item description ; renderers/adaptive_card.py:225/633 ; renderers/a2ui.py:385
tools/edit_toolkit.py: class EditToolkit(AbstractToolkit) :63 ; async def update_field( :318 ; tools/create_form.py: self._client.ask(text, **ask_kwargs) :730
docs/audio-form-voice-modes.md: "## 7. WebSocket Protocol — Complete Message Reference" :407 ; §7.1 :409 ; §7.2 :595 ; §9.10 :1268 ; §9.11 :1677 ; §10 Error Codes :2163
packages/parrot-formdesigner/migrations/: 001–008 ; 003_migrate_form_data.py (asyncpg, --dsn --schema --batch-size --dry-run) ; README.md
packages/ai-parrot/src/parrot/clients/base.py: async def ask(..., structured_output: Union[type, StructuredOutputConfig, None] = None, ...)  :1817, :1826
packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py: async def transcribe(self, audio_path: Path, language=None) -> TranscriptionResult  :39 (confidence Optional :59) ; moonshine English-only :33-35
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QuestionPlanner.replan` | `RuleEvaluator.resolve()` | call with `unwrap_voice(answers)` | `services/rule_evaluator.py:578` |
| `SubmissionPipeline.validate/submit` | `FormValidator.validate()` | call | `services/validators.py:221` |
| `SubmissionPipeline.submit` | sinks exclusive branch / `FormSubmissionStorage.store` / `dispatch` / `SubmissionForwarder.forward` / `PartialSaveStore.delete` | extracted code | `api/handlers.py:1824`, `:1853`, `:1887`, `:1900` |
| `AnswerPlausibilityChecker.check` | `AbstractClient.ask(structured_output=PlausibilityBatch)` | one call | `packages/ai-parrot/src/parrot/clients/base.py:1817` |
| `FormAPIHandler.validate/submit_data/optimize_voice` | `SubmissionPipeline`, `_get_llm_client()` | delegation | `api/handlers.py:1004`, `:1498`, `:197` |
| `AudioSegmentCache` | `get_shared_synthesizer` / `synthesize_with_fallback` | call under lock | `tts/synthesizer.py:186`, `renderers/audio.py:164` |
| `store_recording` | `AbstractBlobStorage.put(iter([bytes]), metadata=BlobMetadata(...))` | call | `services/blob_storage.py:131`, `:93` |
| `AudioSessionStore` | `PartialSaveStore._get_redis()` | shared client | `services/partial_saves.py:195` |
| `AudioFormWSHandler` (adapter) | `AudioFormSession.handle()` | sync call per event | new `audio/engine.py` |
| `setup_form_api` | `AudioFormWSHandler(...)`, `SubmissionPipeline(...)` | construction | `api/routes.py:483-491` |
| Renderers | `FormField.hint` via `_resolve()` | field render | `renderers/html5.py:714`, `jsonschema.py:428`, `audio.py:218` |
| `EditToolkit.update_field` | `api/operations.py` field update | existing path | `tools/edit_toolkit.py:318` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormField.hint`~~, ~~`FormField.audio_hint`~~, ~~`FormField.llm_validation`~~, ~~`FormField.sensitive`~~ (derived from `FieldType.PASSWORD`, `renderers/audio.py:361`), ~~`meta["audio_hint"]`~~ consumed at runtime.
- ~~`FormSchema.voice`~~, ~~`FormSchema.llm_validation`~~, ~~`core/voice.py`~~, ~~`core/llm_validation.py`~~, ~~`FormSchema.model_config`~~ (none declared).
- ~~`ValidationResult.warnings` / `.advisories` / `.plausibility`~~; ~~`FormValidator(client=...)`~~ (constructor takes no args); no LLM anywhere in `services/validators.py`.
- ~~`services/plausibility.py`~~, ~~`AnswerPlausibilityChecker`~~, ~~`PlausibilityReport`~~, ~~`PlausibilityBlocked`~~, ~~`services/submission_pipeline.py`~~, ~~`SubmissionPipeline`~~, ~~`SubmitOutcome`~~.
- ~~`AudioQuestion.hint / narration / ui_cue / section_uid / answer_modes / voice_meta`~~, ~~`AudioAnswer.blob_ref / matched / plausibility / version`~~, ~~`AudioSessionState.phase / cursor / plan / flagged`~~.
- ~~`audio/{engine,planner,option_matcher,commands,option_refiner,segments,events,session_store,recordings}.py`~~, ~~`audio/narration/`~~, ~~`tools/voice_optimizer.py`~~.
- Messages ~~`audio_segment`, `plan_updated`, `section_enter`, `question_skipped`, `answer_cleared`, `review_start/item/prompt/confirm/edit`, `plausibility_check/result`, `command_ack`, `session_resumed`, `validation_errors`~~.
- ~~`PartialSaveStore.remove_keys()`~~, ~~`AudioSessionStore`~~; no use of `RuleEvaluator`, `blob_storage`, `partial_store` or `FormValidator.validate` inside `api/audio_ws.py`.
- ~~`AbstractTranscriberBackend.transcribe_bytes()`~~ / streaming STT; ~~SSML in SuperTonic~~; ~~`VoiceSynthesizer.synthesize_to_base64()`~~.
- ~~A2UI voice primitive~~ (`renderers/a2ui.py:238` degrades AUDIO to `notice`).
- ~~`src/parrot_formdesigner/migrations/`~~ (they live at the package root `packages/parrot-formdesigner/migrations/`); ~~`009_*`, `010_*`~~; ~~`fd_unwrap_voice`~~, ~~`form_data_scalar`~~.
- ~~`packages/parrot-formdesigner/docs/audio-form-voice-modes.md`~~ (the doc is at repo root `docs/`).
- ~~`POST …/voice/optimize`~~, ~~`EditToolkit.propose_voice_hints`~~, ~~`llm_validation` flag on `POST …/validate`~~.
- ~~`fakeredis`~~ is not installed (tests must use a dict-backed stub or a real localhost Redis with skip-if-unreachable).
- ~~A Svelte client of the forms WebSocket~~ in any repo.

### Edit Sites (Blueprint Anchors)

Verified against: `dc54b7ae6` (code files identical to `b288daa72`). `/sdd-task` MUST re-run
`grep -c` per row. Paths relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`
unless prefixed.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `core/schema.py` | MODIFY (M1: `hint`, `llm_validation` on `FormField`) | `    answer_envelope: Literal["voice"] | None = None` | `core/schema.py:143` | 1 |
| `core/schema.py` | MODIFY (M1: `voice`, `llm_validation` on `FormSchema`) | `    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP` | `core/schema.py:475` | 1 |
| `core/voice_answer.py` | MODIFY (M1: subclass + helpers below) | `class VoiceAnswerEnvelope(BaseModel):` | `core/voice_answer.py:13` | 1 |
| `core/__init__.py` | MODIFY (M1: exports) | `from .voice_answer import VoiceAnswerEnvelope` | `core/__init__.py:53` | 1 |
| `core/voice.py` | CREATE (M1) | — | — | — |
| `core/llm_validation.py` | CREATE (M1) | — | — | — |
| `audio/models.py` | MODIFY (M2: `AudioQuestion` deltas) | `class AudioQuestion(BaseModel):` | `audio/models.py:72` | 1 |
| `audio/models.py` | MODIFY (M2: `AudioAnswer` deltas) | `class AudioAnswer(BaseModel):` | `audio/models.py:153` | 1 |
| `audio/models.py` | MODIFY (M2: `AudioSessionState` deltas) | `class AudioSessionState(BaseModel):` | `audio/models.py:179` | 1 |
| `audio/__init__.py` | MODIFY (M2: exports) | `from .models import (` | `audio/__init__.py:15` | 1 |
| `audio/events.py` | CREATE (M2) | — | — | — |
| `audio/narration/__init__.py`, `audio/narration/engine.py`, `audio/narration/lexicon.py`, `audio/narration/templates/en/narration.yaml`, `audio/narration/templates/es/narration.yaml` | CREATE (M3) | — | — | — |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY (M3: package-data for `*.yaml`) | `    "jinja2>=3.1",` | `pyproject.toml:41` | 1 |
| `audio/option_matcher.py`, `audio/commands.py`, `audio/option_refiner.py` | CREATE (M4) | — | — | — |
| `audio/planner.py` | CREATE (M5) | — | — | — |
| `audio/segments.py`, `audio/recordings.py` | CREATE (M6) | — | — | — |
| `services/partial_saves.py` | MODIFY (M7: `remove_keys` after `delete`) | `    async def delete(` | `services/partial_saves.py:145` | 1 |
| `audio/session_store.py` | CREATE (M7) | — | — | — |
| `services/plausibility.py` | CREATE (M8) | — | — | — |
| `services/submission_pipeline.py` | CREATE (M9) | — | — | — |
| `services/validators.py` | MODIFY (M9: envelope detection) | `    def _is_voice_envelope_field(field: FormField) -> bool:` | `services/validators.py:543` | 1 |
| `services/validators.py` | MODIFY (M9: envelope coercion) | `            if field.answer_envelope == "voice":` | `services/validators.py:629` | 1 |
| `api/handlers.py` | MODIFY (M9: validate opt-in) | `    async def validate(self, request: web.Request) -> web.Response:` | `api/handlers.py:1004` | 1 |
| `api/handlers.py` | MODIFY (M9: submit tail → pipeline) | `            if form.persistence is not None:` | `api/handlers.py:1824` | 1 |
| `api/handlers.py` | MODIFY (M13: `optimize_voice` near the client getter) | `    def _get_llm_client(self) -> "AbstractClient | None":` | `api/handlers.py:197` | 1 |
| `api/routes.py` | MODIFY (M9/M11: pipeline + adapter wiring) | `        from .audio_ws import AudioFormWSHandler` | `api/routes.py:480` | 1 |
| `api/routes.py` | MODIFY (M13: optimize route next to validate) | `        f"{tp}/forms/{{form_uid}}/validate",` | `api/routes.py:415` | 1 |
| `api/audio_ws.py` | MODIFY (M11: rewrite class body; keep `:59-100`) | `class AudioFormWSHandler:` | `api/audio_ws.py:102` | 1 |
| `audio/engine.py` | CREATE (M10) | — | — | — |
| `services/sinks/postgres_table.py` | MODIFY (M12: DDL type) | `_DEFAULT_DDL_TYPE = "TEXT"` | `services/sinks/postgres_table.py:79` | 1 |
| `services/sinks/postgres_table.py` | MODIFY (M12: jsonb columns) | `        jsonb_columns = {"context", "extra_data"} | {` | `services/sinks/postgres_table.py:322` | 1 |
| `services/sinks/mapper.py` | MODIFY (M12: envelope serialisation) | `def _extract_value(data: dict[str, Any], column_name: str, field: FormField) -> Any:` | `services/sinks/mapper.py:176` | 1 |
| `packages/parrot-formdesigner/migrations/009_voice_envelope_form_data.sql`, `009_voice_envelope_sink_tables.py`, `010_voice_envelope_report.py` | CREATE (M12) | — | — | — |
| `packages/parrot-formdesigner/migrations/README.md` | MODIFY (M12: new section at end) | `# parrot-formdesigner migrations (FEAT-389)` | `README.md:1` | 1 |
| `renderers/audio.py` | MODIFY (M13: question build + `disabled` on options) | `    def split_into_questions(` | `renderers/audio.py:277` | 1 |
| `extractors/yaml.py` | MODIFY (M13: `hint`, `llm_validation`) | `        description = self._parse_localized(data.get("description")) if "description" in data else None` | `extractors/yaml.py:193` | 1 |
| `tools/create_form.py` | MODIFY (M13: prompt schema) | `          "placeholder": "string (optional)",` | `tools/create_form.py:89` | 1 |
| `renderers/html5.py` | MODIFY (M13: hint) | `        description = _resolve(field.description, locale) if field.description else None` | `renderers/html5.py:714` | 1 |
| `renderers/jsonschema.py` | MODIFY (M13: `x-hint`) | `                        "description": _resolve(item.description, locale) if item.description else None,` | `renderers/jsonschema.py:428` | 1 |
| `renderers/adaptive_card.py`, `renderers/a2ui.py`, `renderers/pdf.py` | MODIFY (M13: hint) | `(unverified — check before use)` field-level description render site per file; form-level anchors at `adaptive_card.py:225`, `a2ui.py:385` are NOT the field site | — | — |
| `tools/edit_toolkit.py` | MODIFY (M13: `hint`, `llm_validation`, `propose_voice_hints`) | `    async def update_field(` | `tools/edit_toolkit.py:318` | 1 |
| `tools/voice_optimizer.py` | CREATE (M13) | — | — | — |
| `docs/audio-form-voice-modes.md` | MODIFY (M14: §7 v2) | `## 7. WebSocket Protocol — Complete Message Reference` | `docs/audio-form-voice-modes.md:407` | 1 |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY (M14: frozen tables) | `## 3. Backend contract` | (section header) | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Engine purity**: `audio/engine.py` has no `await`; I/O is expressed as `Outbound` requests and results come back as events (`*_Done`, `IOFailed`). The AST test in §4 enforces it.
- **Optional heavy deps**: `parrot.voice.*` and `parrot.clients.*` only under `TYPE_CHECKING` or lazy imports inside functions (`api/audio_ws.py:47-54`, `api/handlers.py:209`). `AnswerPlausibilityChecker(client=None)` must construct and return `skipped`.
- **Behaviour-preserving extraction first** (M9): write the parity tests against today's `submit_data` before moving a line; keep FEAT-457 sink exclusivity (never fall back to the generic table), FEAT-188 `dispatch` ordering (`onError` best-effort), FEAT-544 A2UI envelopes.
- **Additive wire**: inbound models `extra="forbid"`; new outbound fields only; v1 names kept; `protocol_version` negotiated in `start_session`.
- **Narration never from the LLM**: YAML + Jinja2 `ImmutableSandboxedEnvironment(undefined=StrictUndefined)`; author prompts via `str.format_map` whitelist.
- **Owner decisions as code**: typed blocks on `FormSchema`; list-valued MULTI_SELECT; `VoiceEvidenceEnvelope` subclass; "[hidden]" in review; shared synthesiser + lock; commands opt-out per field; proposals-only optimiser.
- **Logging** via `logging.getLogger(__name__)`; Pydantic v2; Google-style docstrings; `ruff check` (TID251 bans) on every touched file.

### Known Risks / Gotchas
- **Hot-path refactor** (`handlers.py:1818-1909` → pipeline): mitigated by parity golden tests and by landing M9 before M11 switches the audio path.
- **`FormField` is `extra="forbid"`**: every code path that constructs a `FormField` from external JSON (import tools, operations, tests fixtures, the navigator-svelte designer) must learn `hint`/`llm_validation`; `FormSchema` tolerates unknown keys, so its new blocks are safe for old readers.
- **No TTS**: text-only turns with the same `narration` payload; `prefetch_count = 0`.
- **STT confidence `None`** (Moonshine): gate degrades to `1.0`; `stt_backend` recorded in `context`.
- **Plausibility LLM failure**: `skip` → `status: skipped` and unflagged review; `block` → retryable error, nothing stored. Verdicts for unknown fields dropped; confidence clamped; checker never called with zero eligible fields.
- **Command/option collisions** (an option labelled "Saltar"): exact option wins; collisions enumerated by test and by the optimiser self-test; authors can set `meta.voice.commands: off`.
- **Disconnect during review or during the plausibility call**: snapshot in `finally`; resume re-plans and re-runs plausibility (saved report discarded).
- **Form edited between sessions**: `RESUME_STALE`; unknown `field_uid`s dropped, options re-validated.
- **GROUP children**: `RuleEvaluator.resolve()` iterates `iter_all_fields()` (`:598`) — children inherit the parent's visibility by design here; ledger issue for the evaluator.
- **Subsection rules**: `FormSubsection.depends_on` is not evaluated anywhere (`_apply_section_visibility`, `services/rule_evaluator.py:642`, walks sections only) — §8 Q1; default is HTTP parity (ignored) until decided.
- **v1 compatibility**: v1 inbound parsed with `extra="ignore"` (today's behaviour), v2 with `extra="forbid"`; the integration suite keeps the FEAT-236 fixtures green.
- **ONNX memory**: one shared synthesiser per process behind a lock; prefetch sequential per session; LRU bounded.
- **Migration 009** alters live per-form columns: maintenance window, `--dry-run` first, `010 --downgrade` reversible; CSV/GSheet sinks receive the envelope as a JSON string (like ARRAY today).
- **Orphan recordings** when a session is abandoned without `end_session`: TTL-based cleanup is operational; `010` reports orphans.
- **`fakeredis` is not installed**: use a dict-backed stub or a real localhost Redis with skip-if-unreachable (FEAT-644 conftest pattern).
- **Shared `.venv` in worktrees**: run tests with `PYTHONPATH=packages/parrot-formdesigner/src`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jinja2` | `>=3.1` (already a dependency, `pyproject.toml:41`) | narration templates in a sandboxed environment |
| `pydantic` | v2 (already) | events, configs, verdicts, envelopes |
| `aiohttp` | `>=3.9` (already) | WebSocket adapter |
| `redis` | `>=4.5` (existing extra) | `AudioSessionStore` over the partial-save client; no-op without Redis |
| `asyncpg` | existing migration pattern | migrations 009/010 (`003_migrate_form_data.py` style) |
| `ai-parrot` | `>=1.2.1` (optional extra) | `AbstractClient.ask(structured_output=…)` for plausibility, optimiser, refiner |
| `ai-parrot-integrations[voice]` | existing | `VoiceSynthesizer`, transcriber backends; API unchanged |
| `difflib`, `unicodedata` | stdlib | fuzzy matching and normalisation (`rapidfuzz` only if importable; never required) |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec. Echoed here for the audit trail.

**Proposal decisions (do not re-litigate):**
- [x] Pre-synthesised audio delivery — *Resolved in brainstorm*: WebSocket only; pre-synthesis at `start_session` + `audio_segment` prefetch; no audio in the HTTP manifest.
- [x] Per-field voice configuration — *Resolved in brainstorm*: first-class `FormField.hint`; other settings under `meta["voice"]`.
- [x] Where text + audio live — *Resolved in brainstorm*: `VoiceEvidenceEnvelope` in `FormSubmission.data[field_id]`; audio in blob storage.
- [x] Envelope scope — *Resolved in brainstorm*: every spoken answer, any type; typed/selected answers stay scalars.
- [x] Item-by-item selectors — *Resolved in brainstorm*: list all options with ordinals, then listen; `matched` highlights in the UI.
- [x] `form_data` migration — *Resolved in brainstorm*: per-form `ALTER COLUMN … JSONB USING jsonb_build_object('answer', col)` + legacy normalisation; sink DDL emits JSONB for voice fields.
- [x] Review confirmation — *Resolved in brainstorm*: voice ("ok/sí/enviar") or Send button → `review_confirm`; "cambiar la N" re-asks.
- [x] Extras in scope — *Resolved in brainstorm*: Redis resume, per-form cap (never truncate required), design-time optimiser, separate handoff, migration.

**LLM-assisted validation and hands-free (brainstorm rounds 1–2):**
- [x] Declaration and channels — *Resolved in brainstorm*: `FormField.llm_validation` + `FormSchema.llm_validation` default; every channel.
- [x] Low confidence — *Resolved in brainstorm*: re-ask (audio) / flag (HTTP); never block; persist confidence.
- [x] LLM unavailable — *Resolved in brainstorm*: fail-open with audit by default (`status: skipped`).
- [x] Invocation — *Resolved in brainstorm*: one batched structured-output call at the end of the form.
- [x] Placement — *Resolved in brainstorm*: separate `services/plausibility.py` invoked by the `SubmissionPipeline` after `FormValidator`.
- [x] HTTP surface — *Resolved in brainstorm*: additive `plausibility` block on submit + opt-in `llm_validation: true` on `POST …/validate`.
- [x] Model input — *Resolved in brainstorm*: label/description/hint/type/options/scalar; never sensitive fields, blobs or `data_url`; no cross-field context.
- [x] Hands-free commands — *Resolved in brainstorm*: in scope; classified before the option matcher; `command_ack`; client auto-opens the mic after TTS (VAD + silence).

**Owner review (2026-10-10):**
- [x] Typed vs `meta` blocks — *Resolved in brainstorm*: typed `FormSchema.voice` / `FormSchema.llm_validation`.
- [x] MULTI_SELECT by voice — *Resolved in brainstorm*: stored as a list; display string kept in `form_complete`.
- [x] `sensitive` in review — *Resolved in brainstorm*: narrate "[hidden]", keep the position.
- [x] `/partial` and the audio snapshot — *Resolved in brainstorm*: answers only; snapshot private to the audio channel.
- [x] `VoiceEvidenceEnvelope` shape — *Resolved in brainstorm*: subclass of `VoiceAnswerEnvelope`.
- [x] Runtime LLM option refinement — *Resolved in brainstorm*: off by default; opt-in `voice.llm_refine_options`; always via `confirm_request`.
- [x] Optimiser `apply` — *Resolved in brainstorm*: staging only; the endpoint never writes.
- [x] Migration window / sidecar — *Resolved in brainstorm*: envelope in column; maintenance window + `--dry-run`; `fd_unwrap_voice` + `form_data_scalar`; sidecar rejected.
- [x] GROUP children in `RuleEvaluator` — *Resolved in brainstorm*: evaluator unchanged; planner inherits parent visibility; ledger issue for `iter_fields_recursive`.
- [x] Thresholds and lexicons — *Resolved in brainstorm*: 0.8/0.6 match, 0.7 plausibility, 8 s, 50 fields, all per-form configurable; `en`+`es` in v1, `pt`/`fr` follow-up.
- [x] Synthesiser sharing — *Resolved in brainstorm*: one shared per process + `asyncio.Lock`.
- [x] `on_error: block` — *Resolved in brainstorm*: implement both `skip` (default) and `block`; `block` covers LLM failure only.
- [x] Re-check after `review_edit` — *Resolved in brainstorm*: delta batch for changed fields; one flag per answer version.
- [x] Default plausibility model — *Resolved in brainstorm*: handler's injected client with per-form `llm_validation.model` override.
- [x] Command vs option collisions — *Resolved in brainstorm*: exact option wins; `meta.voice.commands: off` per field; collisions enumerated by test.
- [x] Hands-free end-of-speech — *Resolved in brainstorm*: client-side VAD + `silence_ms`; server reports only `max_recording_seconds`.

**Escalated from design research (§9):**
- [ ] Q1. `FormSubsection.depends_on` (`core/schema.py:222`) is never evaluated: `RuleEvaluator._apply_section_visibility` (`services/rule_evaluator.py:642`) gates only `FormSection.depends_on`, and `resolve()` is the evaluator's only public method, so the audio planner cannot honour subsection rules without an evaluator change. Options: (a) v1 parity — ignore subsection rules on audio as HTTP does today (**default if undecided**); (b) extend `_apply_section_visibility` to walk subsections too, which also fixes HTTP validation and touches FEAT-234 code the owner chose not to change for GROUP children. — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-649-audio-form-interaction-workflow` (from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = imports a symbol defined by the target):
  - M2 → M1 (`FieldVoiceMeta`, `UiCue`, `PlausibilityReport` into `audio/models.py`/`events.py`)
  - M3 → M1 (`FormField.hint`, `FieldVoiceMeta`, `VoiceFormConfig`)
  - M4 → M3 (`Lexicon`, `normalize`), M4 → M2 (`OptionMatch`, `Phase`)
  - M5 → M1, M2 (`VoiceFormConfig`, `AudioAnswer`, `unwrap_voice`); uses existing `RuleEvaluator`
  - M6 → M2 (`AudioSegment` texts/keys); M7 → M2 (`AudioSnapshot` fields mirror `AudioSessionState`)
  - M8 → M1 (`LLMValidationConfig`, `PlausibilityReport`, `llm_validation_enabled`)
  - M9 → M1 (`unwrap_voice`/`wrap_voice`), M9 → M8 (`AnswerPlausibilityChecker`)
  - M10 → M2, M3, M4, M5 (engine composes them)
  - M11 → M6, M7, M9, M10 (adapter performs the I/O the engine requests)
  - M12 → M1 (`is_voice_envelope`, `unwrap_voice`)
  - M13 → M1 (`hint`, `llm_validation`), M3 (narration preview), M4 (`command_option_collisions`)
  - M14 → M2, M11 (documents the implemented wire)
  Modules without an edge between them run concurrently: after M1 lands, {M2, M3, M8, M12} in parallel; then {M4, M5, M6, M7, M9, M13-renderers} in parallel; then M10; then M11; then M14.
- **Shared files** (tasks serialized): `core/schema.py` (M1 only, two anchors — one task); `api/handlers.py` (M9 validate/submit, M13 optimize); `api/routes.py` (M9/M11 wiring, M13 route); `audio/models.py` + `audio/__init__.py` (M2 only); `services/validators.py` (M9 only); `renderers/audio.py` (M13 only); `pyproject.toml` (M3 package-data).
- **Exclusive resources**: none (no extension rebuild, no lockfile change; migrations are files only, never executed by tests against a shared DB). The M9 parity-test task must complete before any task modifies `api/handlers.py:1818-1909`.
- **Cross-feature dependencies**: none open. `git log --since 2026-09-01` on `core/schema.py`, `services/validators.py`, `api/handlers.py`, `api/audio_ws.py` shows only completed FEAT-544/FEAT-488 work; the stale remote branch `claude/form-submission-metadata-TYH8Z` (2026-05-18) touches submissions metadata and must be checked before M9 lands. FEAT-536 (voicebot-liveavatar) is open in another package with no shared files.

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` (codex-cli 0.159.2, reasoning effort high) · Status: completed · Transcript: `sdd/state/FEAT-649/design_research/`
> Brief = brainstorm Problem Statement, Constraints, Recommendation + Option B body and Code Context paths only (no spec draft, no reasoning). All 12 suggestions passed path containment and existence checks; four factual claims were re-verified in code before disposition (S1b, S4, S6, S9).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1a | Make the planner recompute from RuleResolution (architecture) | CONFIRM | Already the M5 design; the review adds the explicit rule that `required` on `AudioQuestion` is the dynamic `RuleResolution.required`, never the static flag. | §3 M5, §5 AC7 |
| S1b | Subsection `depends_on` is not evaluated by `RuleEvaluator` (architecture) | ESCALATE | Verified: `_apply_section_visibility` (`services/rule_evaluator.py:642`) gates only `FormSection.depends_on`; `FormSubsection.depends_on` (`core/schema.py:222`) is ignored on every channel and `resolve()` is the only public method, so the planner cannot evaluate it alone. Owner decided the evaluator stays untouched (GROUP question); subsections need the same call. | §8 Q1 |
| S2 | Split submission into prepare and commit phases (architecture) | CONFIRM | `SubmissionPipeline.validate()` is the pure prepare step (sanitised data + plausibility report); `submit()` is the idempotent commit keyed by the pre-generated `submission_id`; the engine runs prepare at REVIEW and commit on `review_confirm`. | §2 Overview, §3 M9/M10 |
| S3 | Preserve the existing voice envelope, add a typed evidence layer (api) | CONFIRM | Matches the owner decision (subclass) and the unwrap → validate → rewrap rule; the review adds an explicit test that NUMBER/BOOLEAN/SELECT/MULTI_SELECT envelopes coerce through the scalar. | §3 M1/M9, §4, §5 AC8 |
| S4 | Option matching must produce canonical values and skip disabled options (api) | CONFIRM | Verified: `renderers/audio.py:343-349` drops `FieldOption.disabled` (`core/options.py:21`). `AudioQuestion.options` now carries `disabled`; the matcher ignores disabled options and turns a tie between top candidates into `confirm_request` instead of guessing. | §3 M4/M13, §4, §5 AC6 |
| S5 | Expose a public, typed audio snapshot store with CAS (architecture) | CONFIRM | `AudioSnapshot` gains `revision`; `AudioSessionStore.save(expected_revision=…)` is compare-and-set; tenant/user/form-version validated on load; no Redis ⇒ `RESUME_UNAVAILABLE`. | §3 M7, §5 AC16 |
| S6 | Explicit legacy protocol mode before `extra="forbid"`; duplicate handling (risk) | CONFIRM (partial) | v1 (`protocol_version` absent) inbound models parse with `extra="ignore"` — today's handler ignores unknown keys (`api/audio_ws.py:420-431`); v2 is `extra="forbid"`. Duplicates: an answer for a field that is not the cursor is `WRONG_FIELD` and `AudioAnswer.version` makes re-answers explicit — a new message-ID scheme is REJECTED as unnecessary for a single-cursor engine. | §3 M2/M11, §7 |
| S7 | Bound prefetch to the resolved plan and cache identity (architecture) | CONFIRM (partial) | Cache key adds the narration-template revision; questions that become visible after a re-plan are synthesised lazily. The proposal to prefetch only the current + next few questions is REJECTED: the owner decided to push all planned audio at connect (bounded by `max_questions`) and v2 negotiation already gates it. | §3 M6, §5 AC3/AC17 |
| S8 | Centralize sensitive-content and recording lifecycle policy (risk) | CONFIRM | One `is_sensitive(field)` helper (PASSWORD or `meta.voice.sensitive: true`) used by narration, review, plausibility eligibility, logs and `form_complete` (values masked there too); recordings carry the answer version, obey `max_msg_size`/`max_recording_seconds`, overwrite on re-record (deterministic id) and are deleted on failed commit / `end_session`. | §3 M1/M6/M8/M10, §5 AC8/AC15, §7 |
| S9 | Treat `hint` and `llm_validation` as schema-wide contracts (api) | CONFIRM | M13 now covers `extractors/yaml.py` and the `tools/create_form.py` schema prompt as well as every renderer; narration precedence is `hint` > `description`; A2UI exposes `hint` as a `Text` under the control. | §3 M13, §5 AC4 |
| S10 | Specify tabular storage for voice evidence before migrations (risk) | CONFIRM (tests) | The representation is fixed by the owner (envelope in a JSONB column; sidecar rejected). Adopted: tests for the generic `FormSubmissionStorage` path, the per-form sink DDL/INSERT and legacy normalisation. | §3 M12, §4 |
| S11 | Complete dependency injection at the audio route boundary (architecture) | CONFIRM | Already M9/M11; the review adds passing the `AuthenticatedUser` as `AuthContext` to the pipeline from the adapter and keeping `parrot.clients` behind the optional extra. | §3 M9/M11, §7 |
| S12 | Build parity tests around the shared commit contract (testing) | CONFIRM | Adversarial tests added: hidden/required, disabled options, reconnect duplicates, sensitive answers, legacy clients, identical sink payload/event order through HTTP and audio. | §4 |

Summary: **12** confirmed (2 partial) · **0** rejected · **1** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-10 | Jesus Lara (with Claude) | Initial draft from the accepted brainstorm; all 32 brainstorm decisions carried forward |
