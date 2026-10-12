---
type: feature
base_branch: dev
projects: [parrot-formdesigner, docs]
tags: [audio-forms, voice, hands-free, barge-in, narration, tts]
---

# Feature Specification: Voice Form hands-free barge-in and per-option narration segments

**Feature ID**: FEAT-654
**Date**: 2026-10-12
**Author**: Jesus Lara
**Status**: draft
**Target version**: next parrot-formdesigner minor after FEAT-649 / FEAT-653

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

A user filling an audio form (FEAT-649, protocol v2) often knows the answer before the
question has finished playing. Two situations make waiting for the end of the narration
feel slow:

1. **Known answer.** The user hears the label ("What is your name?") and wants to answer
   immediately, without waiting for the hint and the rest of the narration.
2. **Multi-choice enumeration.** A SELECT / MULTI_SELECT question with many options is
   narrated as *"There are 6 options: 1, Alpha. 2, Beta. 3, …"*. The user hears the option
   they want and would like to say it right away instead of listening to the remaining
   items.

The server side already supports this: `AudioFormSession.on_audio_frame`
(`audio/engine.py:334`) accepts a binary recording as soon as the phase is `ASKING` or
`CONFIRMING` and a cursor exists, the phase becomes `ASKING` the moment the `question` is
emitted (`audio/engine.py:223`), and the cursor only advances on `answer_accepted`. In
protocol v2 narration segments are pre-synthesised and pushed ahead (`prefetch`), so
playback is entirely client-side. A recording sent in the middle of the narration is
transcribed against the current question today, with no gating change needed.

What is missing is the **contract**:

- The hands-free resolution carried by FEAT-649
  (`sdd/specs/audio-form-interaction-workflow.spec.md:1095`) and the navigator-svelte
  handoff (`sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md:94`)
  say the client "auto-opens the mic **after** TTS". Nothing tells a client that it may,
  or should, keep the microphone armed with VAD *during* playback and cancel playback when
  the user starts talking. Barge-in is therefore not implemented by any client and a form
  author has no way to turn it off (speaker-phone setups without echo cancellation would
  self-trigger).
- The options narration is **one** segment, `q:<uid>:options`, holding the intro and every
  item (`audio/narration/engine.py:134-151`). A client can stop playback mid-segment, but
  there is no explicit gap between items for the user to speak into, and no clean boundary
  to stop at. The documented key grammar (`docs/audio-form-voice-modes.md:806-815`) has
  only `label | hint | options` segment kinds.

### Goals

- G1. Make barge-in an explicit, form-configurable part of the hands-free contract:
  `hands_free.barge_in` (default `true`) is sent in `session_started` next to
  `auto_record` and `silence_ms`.
- G2. Document the client-side rules for barge-in (mic armed with VAD during playback,
  speech onset cancels playback and pending `pause:` timers, record until `silence_ms` of
  silence or `max_recording_seconds`, send one complete container frame as today) together
  with the acoustic-echo guidance a client needs to make it work on speakers.
- G3. Narrate enumerated options as **one segment per option** with an explicit
  `pause:<option_pause_ms>` gap between consecutive items, so that a user can answer in a
  gap and a client can stop at an item boundary. The gap is configurable at form level
  (`VoiceFormConfig.option_pause_ms`) and per field (`meta.voice.option_pause_ms`).
- G4. Keep every existing behaviour intact: `count_only`, `never`, `enumerate_options:
  false` and BOOLEAN questions keep their single segment; protocol v1 / `prefetch: false`
  keeps one concatenated `question.audio`; the segment cache keys are unchanged; the
  `repeat` command still replays the full `audio_keys` list; `NarrationPlan.text` is the
  same sentence as before.
- G5. Add a regression test that pins the server behaviour barge-in relies on: a binary
  recording received right after `question` (before any client-side playback could have
  ended) is transcribed against the cursor field.
- G6. Update `docs/audio-form-voice-modes.md` and the navigator-svelte handoff so a frontend
  team can implement barge-in and per-option playback from the docs alone.

### Non-Goals (explicitly out of scope)

- **Server-side VAD or streaming audio.** The WebSocket keeps accepting one complete
  container per answer (`api/audio_ws.py:527-566`). No PCM streaming, no Silero / webrtcvad
  on the server, no partial `MediaRecorder` chunks.
- **Interrupting the narration server-side.** The server never learns that playback was
  cut short; no `playback_interrupted` message, no analytics.
- **Per-session override of `barge_in` from `start_session`.** The flag is form-level
  (`FormSchema.voice.hands_free`) in this feature.
- **Changing option matching.** The option matcher, ordinals and command classification are
  untouched; a transcript recorded mid-enumeration goes through the same pipeline.
- **The navigator-svelte client itself.** The frontend lives in another repository; this
  spec fixes the wire contract and the docs it will be built from.
- **FEAT-653 scope** (spoken-value normalization, `ConfirmRequest.value`) — a sibling
  feature on the same files; see Worktree Strategy for the merge order.

---

## 2. Architectural Design

### Overview

Three small, additive changes on parrot-formdesigner plus documentation:

1. **`HandsFreeConfig.barge_in: bool = True`** (`core/voice.py:19`). Because
   `SessionStarted.hands_free` embeds the model directly (`audio/events.py:293`), the flag
   reaches the wire with no engine change. Semantics (client policy):
   - `true`: while narration segments play, the microphone stays armed with VAD. On speech
     onset the client stops playback, discards the remaining `audio_keys` (including pending
     `pause:` timers), records until `silence_ms` of silence or `max_recording_seconds`, and
     sends one complete container frame. The server transcribes it against the current
     cursor exactly as it does for a post-narration recording.
   - `false`: the client arms the microphone only after the last segment of the question
     has finished (today's documented behaviour). A push-to-talk control must still allow an
     early answer.
   - `barge_in` is only meaningful when `auto_record` is `true`; a client that does not
     auto-record ignores it.

2. **Per-option narration segments** (`audio/narration/engine.py:134-172`). For an
   enumerated SELECT / MULTI_SELECT / DYNAMIC_SELECT question the plan becomes:

   ```
   q:<uid>:label
   [pause:<hint_pause_ms>  q:<uid>:hint]            # unchanged
   q:<uid>:options_intro                             # "There are 3 options:"
   q:<uid>:opt:1                                     # "1, Alpha."
   pause:<option_pause_ms>
   q:<uid>:opt:2                                     # "2, Beta."
   pause:<option_pause_ms>
   q:<uid>:opt:3                                     # "3, Gamma."
   ```

   The pause sits **between** consecutive items only (no pause after the intro, none after
   the last item — the hands-free mic opens there anyway). `option_pause_ms` comes from
   `FieldVoiceMeta.option_pause_ms` when set, else `VoiceFormConfig.option_pause_ms`
   (default 500). A value of `0` emits no `pause:` keys but keeps one segment per item.
   `count_only`, `enumerate: never`, `enumerate_options: false` and BOOLEAN keep the single
   `q:<uid>:options` segment. `NarrationPlan.text` stays the space-joined sentence of all
   non-pause segments, so `question.narration.text`, the review and the LLM prompts do not
   change. Option numbering follows the enumerated (non-disabled) list, as today.

3. **Wire and compatibility glue** (`api/audio_ws.py`, `audio/events.py`):
   - `_segment_kind()` maps `…:options_intro` → `"options"` and `…:opt:<n>` → `"option"`;
     `AudioSegment.kind` documents the new value.
   - The protocol v1 / inline grouping in `_do_synthesize` (`api/audio_ws.py:946`) accepts
     the new keys so `question.audio` keeps containing the whole narration, in order.
   - The segment cache (`audio/segments.py`) is text-hashed per key; no change.

4. **Documentation** (`docs/audio-form-voice-modes.md`, the navigator-svelte handoff,
   `packages/parrot-formdesigner/CHANGELOG.md`): a form-level voice settings table (today
   `FormSchema.voice` is not documented anywhere under `docs/`), the extended `hands_free`
   object, the new segment kinds and key grammar, and a new "Barge-in" section with the
   client rules, the echo-cancellation guidance and a sequence diagram for both use cases.

### Component Diagram
```
FormSchema.voice (VoiceFormConfig)
   ├── hands_free: HandsFreeConfig{auto_record, silence_ms, barge_in}   ──► SessionStarted.hands_free ──► client policy
   └── option_pause_ms  ──┐
FormField.meta.voice ─────┼──► FieldVoiceMeta{…, option_pause_ms}
                          ▼
Narrator.plan_question ──► NarrationPlan{text, audio_keys[], segments{}}
   │  keys: q:<uid>:label · pause:<hint> · q:<uid>:hint · q:<uid>:options_intro · q:<uid>:opt:<n> · pause:<opt> …
   ▼
AudioFormSession._synthesize_request / _question  (unchanged — forwards plan.segments / plan)
   ▼
AudioFormWSHandler._do_synthesize
   ├── v2: AudioSegment{key, kind: options|option|…} + binary frame per key   ──► client plays audio_keys in order
   └── v1/inline: group q:<uid>:* texts (incl. options_intro, opt:<n>) ──► question.audio (one blob)

Client (barge-in, hands_free.barge_in=true):
   play segment ──► VAD onset? ──► stop playback, drop pending keys/pauses ──► record ──► silence_ms ──► 1 binary frame
   ──► AudioFormWSHandler._process_binary ──► AudioReceived ──► engine.on_audio_frame (phase ASKING, cursor) ──► Transcribe
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HandsFreeConfig` (`core/voice.py:19`) | extends | `barge_in: bool = True` |
| `VoiceFormConfig` (`core/voice.py:50`) | extends | `option_pause_ms: int = 500` |
| `FieldVoiceMeta` (`core/voice.py:35`) | extends | `option_pause_ms: int \| None = None` (per-field override; parsed by `field_voice_meta`, unknown-key warning unaffected) |
| `Narrator._options_text` / `plan_question` (`audio/narration/engine.py:134,153`) | modifies | per-option segments + pauses; `_options_text` keeps serving the single-segment cases |
| `SessionStarted.hands_free` (`audio/events.py:293`) | uses | carries the new flag automatically (v2 only, as today) |
| `AudioSegment.kind` (`audio/events.py:302`) | extends | new value `"option"` |
| `AudioFormWSHandler._segment_kind` (`api/audio_ws.py:901`) | modifies | new key suffixes |
| `AudioFormWSHandler._do_synthesize` v1 grouping (`api/audio_ws.py:946`) | modifies | accept `options_intro` / `opt:<n>` keys |
| `AudioFormSession.on_audio_frame` (`audio/engine.py:334`) | unchanged, tested | barge-in regression test only |
| `AudioSegmentCache` (`audio/segments.py`) | unchanged | key = sha1(text) per segment |
| `docs/audio-form-voice-modes.md`, handoff doc, CHANGELOG | modifies | see Module 3 |

### Data Models
```python
# core/voice.py (extended)
class HandsFreeConfig(BaseModel):
    auto_record: bool = True
    silence_ms: int = Field(default=1200, ge=0)
    barge_in: bool = True            # NEW — mic armed during playback; speech onset cancels playback

class FieldVoiceMeta(BaseModel):
    ...
    pause_ms: int | None = None
    option_pause_ms: int | None = None   # NEW — per-field override of VoiceFormConfig.option_pause_ms

class VoiceFormConfig(BaseModel):
    ...
    hint_pause_ms: int = Field(default=600, ge=0)
    option_pause_ms: int = Field(default=500, ge=0)   # NEW — gap between enumerated options
```

Wire (v2 `session_started`, additive):
```json
{"type": "session_started", "protocol_version": 2,
 "hands_free": {"auto_record": true, "silence_ms": 1200, "barge_in": true},
 "max_recording_seconds": 60, "prefetch_count": 4}
```

Wire (v2 `audio_segment`, new kind):
```json
{"type": "audio_segment", "key": "q:3f2a…:opt:2", "mime": "audio/wav", "kind": "option", "text": "2, Beta."}
```

### New Public Interfaces

No new classes or functions. New fields on existing Pydantic models (above), a new
segment-key grammar and a new `AudioSegment.kind` value. `NarrationPlan`, `Narrator.render`,
`Narrator.plan_review` and every engine handler keep their signatures.

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `barge_in` config flag | yes | field name, default, position in `HandsFreeConfig`, wire behaviour via `SessionStarted` already fixed; tests enumerated | — |
| M2: per-option narration segments | yes | key grammar, pause placement, config precedence, single-segment cases, `_segment_kind` mapping, v1 grouping rule all fixed in §2 / skeletons | — |
| M3: documentation | yes | exact sections and tables to add/modify listed; content derives from §2 | — |

### Module 1: `barge_in` hands-free flag
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` (modify)
- **Responsibility**: add `HandsFreeConfig.barge_in` with default `True`; verify it reaches
  `session_started.hands_free` for protocol v2 and is omitted for v1 (existing behaviour of
  `hands_free=None`). Add the barge-in server regression test (G5).
- **Depends on**: nothing (existing `SessionStarted` embeds the model).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # core/voice.py  (modifies packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py:19-23)
  class HandsFreeConfig(BaseModel):  # verified: core/voice.py:19
      """Client hands-free behaviour: auto-open mic after TTS, end-of-speech silence, barge-in.

      ``barge_in`` (default True) tells the client to keep the microphone armed with VAD while
      narration segments play and to cancel playback on speech onset. It is a client policy:
      the server already accepts a recording at any time during ASKING/CONFIRMING.
      """

      auto_record: bool = True                      # verified: core/voice.py:22
      silence_ms: int = Field(default=1200, ge=0)   # verified: core/voice.py:23
      barge_in: bool = True                         # NEW
  ```
  Regression test (no production code): a session in `Phase.ASKING` right after the first
  `question` handles `AudioReceived` and returns a `Transcribe(field_id=<cursor>)` — the
  server-side premise of barge-in (`audio/engine.py:334-346`).

### Module 2: per-option narration segments
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py`,
  `audio/narration/engine.py`, `audio/events.py`, `api/audio_ws.py` (modify)
- **Responsibility**: `option_pause_ms` config (form + per-field); `plan_question` emits
  `q:<uid>:options_intro`, `q:<uid>:opt:<n>` and `pause:<option_pause_ms>` keys for
  enumerated select questions; `_segment_kind` and the v1 inline grouping understand the
  new keys; `AudioSegment.kind` documents `"option"`.
- **Depends on**: Module 1 only through the shared file `core/voice.py` (no symbol
  dependency).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # core/voice.py  (modifies core/voice.py:35-48 and :50-69)
  class FieldVoiceMeta(BaseModel):  # verified: core/voice.py:35
      ...
      pause_ms: int | None = None                 # verified: core/voice.py:43
      option_pause_ms: int | None = None          # NEW — per-field gap between enumerated options (ms)

  class VoiceFormConfig(BaseModel):  # verified: core/voice.py:50
      ...
      hint_pause_ms: int = Field(default=600, ge=0)      # verified: core/voice.py:56
      option_pause_ms: int = Field(default=500, ge=0)    # NEW — default gap between enumerated options (ms)

  # audio/narration/engine.py  (modifies audio/narration/engine.py:134-172)
  class Narrator:  # verified: audio/narration/engine.py:104
      def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None:
          """Single-segment options narration (boolean prompt / count-only / enumeration disabled) or None.

          Returns None also when the options ARE enumerated — that case is handled by
          ``_option_segments``. Verified: audio/narration/engine.py:134.
          """

      def _option_segments(
          self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta
      ) -> tuple[list[str], dict[str, str]] | None:
          """Per-option narration for an enumerated select question, or None when not enumerated.

          Returns ``(keys, segments)`` where keys are
          ``q:<uid>:options_intro, q:<uid>:opt:1, pause:<ms>, q:<uid>:opt:2, …`` (pause only between
          consecutive items; omitted when the effective ``option_pause_ms`` is 0) and segments map
          each non-pause key to its rendered text (``options_intro`` / ``option_item`` templates).
          Effective pause = ``meta.option_pause_ms`` if not None else ``cfg.option_pause_ms``.
          Disabled options are skipped and numbering follows the enumerated list, as today.
          """

      def plan_question(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> NarrationPlan:
          """label → ``pause:<ms>`` → hint → options (single segment) | options_intro + opt:<n> with pauses.

          ``text`` is the space-joined text of every non-pause segment in key order (unchanged
          contract). Verified: audio/narration/engine.py:153.
          """

  # audio/events.py  (modifies audio/events.py:302)
  class AudioSegment(_Wire):  # verified: audio/events.py:298
      kind: str  # "question" | "hint" | "options" | "option" | "system" | "review"

  # api/audio_ws.py  (modifies api/audio_ws.py:901-910 and :946)
  class AudioFormWSHandler:  # verified: api/audio_ws.py:228
      @staticmethod
      def _segment_kind(key: str) -> str:
          """Header ``kind`` for a narration segment key.

          ``review:*`` → review; ``*:hint`` → hint; ``*:options`` and ``*:options_intro`` → options;
          ``q:<uid>:opt:<n>`` → option; other ``q:*`` → question; else system.
          """
      # _do_synthesize inline grouping (api/audio_ws.py:946): a key belongs to field <uid> when
      # parts[0] == "q" and (len(parts) == 3 and parts[2] in ("label", "hint", "options", "options_intro")
      # or len(parts) == 4 and parts[2] == "opt"); texts are joined in item.keys order.
  ```

### Module 3: Documentation
- **Path**: `docs/audio-form-voice-modes.md`,
  `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md`,
  `packages/parrot-formdesigner/CHANGELOG.md` (modify)
- **Responsibility**: make the barge-in and per-option contract implementable from the docs.
  Concretely, in `docs/audio-form-voice-modes.md`:
  - **§6**: add a subsection "Form-level voice settings (`FormSchema.voice`)" with a table of
    `VoiceFormConfig` keys relevant to the client (`hands_free.auto_record`,
    `hands_free.silence_ms`, `hands_free.barge_in`, `hint_pause_ms`, `option_pause_ms`,
    `max_recording_seconds`, `enumerate_options`) and the `meta.voice` per-field overrides
    (`pause_ms`, `option_pause_ms`, `enumerate`).
  - **§7.3 `audio_segment`** (`:806-815`): key grammar
    `q:<uid>:label | hint | options | options_intro | opt:<n>`, `pause:<ms>`, `sys:*`,
    `review:*`; `kind` list gains `option`; example JSON for an `opt:<n>` segment; fix the
    example whose `kind` reads `"label"` (the real value is `question`).
  - **§7.3 `session_started` table** (`:936`): `hands_free` → `{auto_record, silence_ms, barge_in}`.
  - **New §7.6 "Barge-in (hands-free interruption)"**: the client rules of §2 Overview item 1,
    the two use cases, a sequence diagram (playback → VAD onset → stop → record → binary frame
    → `transcription` → `answer_accepted` / `confirm_request`), the acoustic guidance
    (`getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}})`, raise the VAD
    energy threshold while playback is active, prefer a headset on speaker-phone devices,
    set `barge_in: false` when AEC is unavailable), and the note that the server never learns
    playback was interrupted.
  - **§7.4 / §12 FAQ**: one line each on how commands and option answers behave when spoken
    mid-enumeration (unchanged pipeline; an exact option match still beats a command).
  - **§1 "What changed"** style table or a short "FEAT-654" note at the top of §7.3.
  In the handoff doc: lines 21, 57, 58 and 94 updated to the new `hands_free` object, the
  `option` kind and the barge-in policy. In the CHANGELOG: an "Unreleased" entry.
- **Depends on**: Module 1 and Module 2 (names and defaults).
- **Interface Skeleton**: not applicable (documentation); the section list above is the
  contract.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_hands_free_config_barge_in_default` | M1 | `HandsFreeConfig()` has `barge_in is True`; `HandsFreeConfig(barge_in=False)` round-trips through `model_dump()` |
| `test_session_started_wire_carries_barge_in` | M1 | `SessionStarted(hands_free=HandsFreeConfig()).to_wire()["hands_free"]["barge_in"] is True`; v1 (`hands_free=None`) omits the key |
| `test_engine_accepts_audio_right_after_question` | M1 | engine in `ASKING` immediately after the first `question`: `handle(AudioReceived)` → `[Transcribe(field_id=cursor)]`, `_last_audio` set (`test_audio_engine_turns.py`) |
| `test_voice_form_config_option_pause_default` | M2 | `VoiceFormConfig().option_pause_ms == 500`; `ge=0` rejects negatives; `FieldVoiceMeta(option_pause_ms=250)` parses; `field_voice_meta` accepts `meta.voice.option_pause_ms` without the unknown-key warning |
| `test_plan_question_enumerated_per_option_keys` | M2 | 3 options (one disabled) → `audio_keys == [label, options_intro, opt:1, pause:500, opt:2]`; `segments[opt:1] == "1, Alpha."`; `segments[opt:2] == "2, Beta."`; no `q:<uid>:options` key; `text` equals the previous concatenated sentence |
| `test_plan_question_option_pause_precedence` | M2 | `VoiceFormConfig(option_pause_ms=300)` → `pause:300`; `FieldVoiceMeta(option_pause_ms=50)` wins → `pause:50`; `option_pause_ms=0` → no `pause:` keys, still one segment per item |
| `test_plan_question_single_segment_cases_unchanged` | M2 | `count_only`, `enumerate="never"`, `enumerate_options=False`, BOOLEAN keep exactly today's keys (`q:<uid>:options` or none); update of `test_plan_question_options_rules` |
| `test_plan_question_hint_then_options_order` | M2 | hint + enumerated options: `[label, pause:<hint>, hint, options_intro, opt:1, pause:<opt>, opt:2]` |
| `test_segment_kind_new_keys` | M2 | `_segment_kind("q:u:options_intro") == "options"`, `_segment_kind("q:u:opt:3") == "option"`, existing mappings unchanged |
| `test_do_synthesize_v2_emits_option_segments` | M2 | with a fake synthesizer, `Synthesize` for an enumerated question sends one `audio_segment` header (+ binary) per `opt:<n>` key with `kind: "option"` and never for `pause:` keys (`test_audio_ws_adapter.py`) |
| `test_do_synthesize_v1_inline_groups_option_keys` | M2 | inline mode: the `v1:<uid>` text is `label + hint + options_intro + opt:1 + opt:2` joined in order (single `question.audio`), unchanged from the previous concatenation |
| `test_question_narration_v2_prefetch_includes_option_keys` | M2 | v2 integration (`test_audio_ws_v2_integration.py`): `question.narration.audio_keys` for a select question contains `opt:<n>` keys and the prefetched `audio_segment` headers cover them |

### Integration Tests
| Test | Description |
|---|---|
| `test_barge_in_flow_v2` | v2 WS session with a select question: client receives `session_started.hands_free.barge_in == true`, the `audio_segment` headers for `options_intro` / `opt:1..n`, sends a binary recording before "playing" anything, gets `transcription` + `answer_accepted` for that field; the next `question` follows. Fake transcriber returns an option label. |

### Test Data / Fixtures
```python
# test_narration_engine.py already provides `_q(**kw)` (line 29) building an AudioQuestion
# with a fresh field_uid; reuse it with field_type="select" and an options list.
# test_audio_ws_adapter.py / test_audio_ws_v2_integration.py already provide fake
# synthesizer / transcriber environments (reuse; do not add new fixtures unless missing).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `HandsFreeConfig` has `barge_in: bool = True`; v2 `session_started.hands_free`
  carries `auto_record`, `silence_ms` and `barge_in`; v1 sessions omit `hands_free` as today.
- [ ] AC2. A binary recording received while the engine is in `ASKING` right after a
  `question` (no client playback assumed) is transcribed for the cursor field — pinned by
  `test_engine_accepts_audio_right_after_question`.
- [ ] AC3. For an enumerated select question `plan_question` emits `q:<uid>:options_intro`,
  then `q:<uid>:opt:<n>` for each enabled option with `pause:<option_pause_ms>` **between**
  consecutive items only; `NarrationPlan.text` is unchanged from the previous single-segment
  sentence.
- [ ] AC4. `option_pause_ms` precedence is `meta.voice.option_pause_ms` > form
  `voice.option_pause_ms` > default 500; a value of 0 removes the pauses but keeps one
  segment per option; negative values are rejected by validation.
- [ ] AC5. `count_only`, `enumerate: never`, `enumerate_options: false` and BOOLEAN
  questions produce exactly the same keys and texts as before this feature.
- [ ] AC6. v2 `audio_segment` headers for the new keys carry `kind: "options"` (intro) and
  `kind: "option"` (items); `pause:` keys never produce a segment.
- [ ] AC7. Protocol v1 / `prefetch: false` sessions still receive one `question.audio` blob
  whose text is the full narration in order, including the per-option texts.
- [ ] AC8. `AudioSegmentCache` keys and the `_SYNTH_LOCK` path are untouched (no change in
  `audio/segments.py`); the `repeat` command keeps replaying the full `audio_keys`.
- [ ] AC9. `docs/audio-form-voice-modes.md` contains the form-level voice settings table,
  the extended `hands_free` object, the new key grammar and `option` kind, and a "Barge-in"
  section with client rules, echo-cancellation guidance and a sequence diagram covering both
  use cases (known answer, mid-enumeration answer).
- [ ] AC10. The navigator-svelte handoff and the parrot-formdesigner CHANGELOG mention the
  new flag, the new kind and the barge-in policy.
- [ ] AC11. All tests in §4 pass:
  `PYTHONPATH=packages/parrot-formdesigner/src pytest packages/parrot-formdesigner/tests/formdesigner -k "narration or hands_free or barge or segment_kind or audio_ws" -q`;
  `ruff check` clean on the touched files.
- [ ] AC12. No breaking change: every existing test in `test_narration_engine.py`,
  `test_audio_ws_adapter.py`, `test_audio_ws_v2_integration.py` and
  `test_audio_engine_turns.py` passes after the intended update of
  `test_plan_question_options_rules`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

Paths below are relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`
(`P/`) unless stated otherwise. Verified against commit `d5f208317` (dev, 2026-10-12).

### Verified Imports
```python
from parrot_formdesigner.core.voice import HandsFreeConfig, FieldVoiceMeta, VoiceFormConfig, field_voice_meta  # P/core/voice.py:19,35,50,84
from parrot_formdesigner.core.types import FieldType                                   # used at P/audio/narration/engine.py:13
from parrot_formdesigner.audio.models import AudioQuestion, NarrationPlan, Phase       # P/audio/models.py:122,68,43
from parrot_formdesigner.audio.narration.engine import Narrator, NARRATION_KEYS         # P/audio/narration/engine.py:104,20
from parrot_formdesigner.audio.events import SessionStarted, AudioSegment, Question, AudioReceived, Transcribe, Synthesize  # P/audio/events.py:287,298,306 (+ events used by engine.py:27)
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler                        # P/api/audio_ws.py:228
from parrot_formdesigner.audio.segments import AudioSegmentCache                       # P/audio/segments.py:21
```

### Existing Class Signatures
```python
# P/core/voice.py
class HandsFreeConfig(BaseModel):                       # line 19
    auto_record: bool = True                            # line 22
    silence_ms: int = Field(default=1200, ge=0)         # line 23

class FieldVoiceMeta(BaseModel):                        # line 35  (model_config = ConfigDict(extra="ignore"), line 38)
    prompt: str | None = None
    enumerate: Literal["auto", "always", "never", "count_only"] = "auto"
    confirm: Literal["auto", "always", "never"] = "auto"
    pause_ms: int | None = None                         # line 43
    ui_cue: UiCue | None = None
    match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    skip_in_review: bool = False
    commands: Literal["on", "off"] = "on"
    sensitive: bool = False

class VoiceFormConfig(BaseModel):                       # line 50
    enabled: bool = True
    max_questions: int | None = Field(default=10, ge=1)
    hint_pause_ms: int = Field(default=600, ge=0)       # line 56
    enumerate_options: bool = True
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    option_match_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    ...
    hands_free: HandsFreeConfig = Field(default_factory=HandsFreeConfig)   # line 66
    tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: str | None = None
    max_recording_seconds: int = Field(default=60, ge=1)                   # line 69

def field_voice_meta(field: FormField, *, logger: logging.Logger | None = None) -> FieldVoiceMeta:   # line 84
    # unknown keys → ONE warning (line 94-96) — adding option_pause_ms to the model removes it from "unknown"

# P/core/schema.py
class FormSchema(...):
    voice: VoiceFormConfig | None = None                # line 489

# P/audio/models.py
class Phase(str, Enum): ...                             # line 43 (IDLE, PLANNING, ASKING, CONFIRMING, ACCEPTING, REVIEW, …)
class NarrationPlan(BaseModel):                         # line 68
    text: str
    audio_keys: list[str] = Field(default_factory=list)
    segments: dict[str, str] = Field(default_factory=dict)   # key -> text to synthesise
class AudioQuestion(BaseModel):                         # line 122  (field_uid: UUID, field_type: str, label, hint, description, options: list[dict] | None, prompt, required, sensitive, …)

# P/audio/narration/engine.py
NARRATION_KEYS: frozenset[str]                          # line 20  (includes "options_intro", "option_item", "options_count_only", "boolean_prompt")
_SELECT_TYPES = {SELECT, MULTI_SELECT, DYNAMIC_SELECT}  # line 74
class Narrator:                                         # line 104
    def __init__(self, locale: str, *, templates_dir: Path | None = None) -> None   # line 107
    def render(self, key: str, **ctx: Any) -> str                                    # line 124
    def system_phrases(self) -> dict[str, str]                                       # line 130
    def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None   # line 134
    def plan_question(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> NarrationPlan   # line 153
    def plan_review(self, items: list[ReviewItemData], cfg: VoiceFormConfig) -> NarrationPlan   # line 174
# templates: P/audio/narration/templates/{en,es}/narration.yaml lines 6-9:
#   options_intro: "There are {{ count }} options:" | option_item: "{{ ordinal }}, {{ label }}." | options_count_only | boolean_prompt

# P/audio/engine.py
_ANSWERING_PHASES = (Phase.ASKING, Phase.CONFIRMING)    # line 88
class AudioFormSession:
    def handle(self, event: InboundEvent) -> list[Outbound]                 # line 158
    def on_plan_ready(self, ev: PlanReady) -> list[Outbound]                # line 180  (SessionStarted built at 207-215 with hands_free=self.cfg.hands_free if v2 else None)
    def _synthesize_request(self, field_ids: list[str], *, include_system: bool) -> Synthesize   # line 270 (texts.update(plan.segments))
    def _question(self, field_id: str) -> Question                          # line 295 (narration=self.narrator.plan_question(...) if v2 else None, line 319)
    def on_audio_frame(self, ev: AudioReceived) -> list[Outbound]           # line 334 (phase gate 343-344; returns [Transcribe(field_id=cursor, …)] line 346)

# P/audio/events.py
class SessionStarted(_Wire):                            # line 287
    hands_free: HandsFreeConfig | None = None           # line 293
    max_recording_seconds: int | None = None
    prefetch_count: int | None = None
class AudioSegment(_Wire):                              # line 298
    key: str; mime: str
    kind: str  # "question" | "hint" | "options" | "system" | "review"   # line 302
    text: str
class Question(_Wire):                                  # line 306
    audio: str | None = None  # base64 — only v1 or prefetch=False       # line 317
    narration: NarrationPlan | None = None                                # line 324

# P/api/audio_ws.py
_MIN_AUDIO_BYTES                                        # line ~116 (single complete container per answer)
class AudioFormWSHandler:                               # line 228
    async def _process_binary(self, ws, ctx, audio: bytes) -> None        # line 527 (sniff, size guard, AudioReceived)
    @staticmethod
    def _segment_kind(key: str) -> str                                    # line 901-910
    async def _synth_items(self, ctx, items: dict[str, str]) -> dict[str, bytes]   # line 913 (skips "pause:" keys, line 931)
    async def _do_synthesize(self, ws, ctx, item: Synthesize) -> None     # line 938 (inline grouping line 943-957; v2 header+bytes 959-968)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `HandsFreeConfig.barge_in` | `SessionStarted.hands_free` | model embedding (no code) | `P/audio/events.py:293`, `P/audio/engine.py:212` |
| `VoiceFormConfig.option_pause_ms` / `FieldVoiceMeta.option_pause_ms` | `Narrator.plan_question` | `cfg` / `meta` args | `P/audio/narration/engine.py:153`, callers `P/audio/engine.py:277,319` |
| per-option keys | `AudioFormSession._synthesize_request` | `plan.segments` dict order | `P/audio/engine.py:278` |
| per-option keys | `AudioFormWSHandler._do_synthesize` | `item.keys` / `_segment_kind` | `P/api/audio_ws.py:946,966` |
| per-option keys | `AudioSegmentCache.ensure` | text-hashed cache key (unchanged) | `P/audio/segments.py:33-41` |

### Does NOT Exist (Anti-Hallucination)
- ~~`HandsFreeConfig.barge_in`~~, ~~`VoiceFormConfig.option_pause_ms`~~,
  ~~`FieldVoiceMeta.option_pause_ms`~~ — created by this feature.
- ~~`Narrator._option_segments`~~ — created by Module 2.
- ~~`AudioSegment.kind == "option"`~~ and keys ~~`q:<uid>:options_intro`~~ /
  ~~`q:<uid>:opt:<n>`~~ — created by Module 2; today only `label|hint|options` exist.
- ~~`Phase.NARRATING`~~ / ~~`Phase.PLAYING`~~ — no such phase; the engine is in `ASKING`
  while the client plays.
- ~~`start_session.hands_free`~~ / ~~`start_session.barge_in`~~ — no per-session override
  (`StartSession` has no such field; `AudioSessionConfig` does not carry hands-free).
- ~~`PlaybackInterrupted`~~ / ~~`playback_interrupted`~~ wire message — out of scope.
- ~~server-side VAD~~ (`parrot.voice.vad`, `silero`, `webrtcvad`) — nothing of the kind
  exists in parrot-formdesigner; `FasterWhisperBackend` only passes `vad_filter=True` to
  Whisper for a complete file (`packages/ai-parrot-integrations/src/parrot/voice/transcriber/faster_whisper_backend.py:151`).
- ~~streaming / chunked audio frames~~ — `_process_binary` rejects partial containers.
- ~~`VoiceSegmentCache` / `VoiceRecorder` Python classes~~ — these names are frontend
  (Svelte) components in the handoff doc, not server code.
- ~~`docs/audio-form-voice-modes.md` form-level `voice:` table~~ — does not exist yet;
  Module 3 adds it.

### Edit Sites (Blueprint Anchors)

Verified against: `d5f208317`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `P/core/voice.py` | MODIFY | `    silence_ms: int = Field(default=1200, ge=0)` | `core/voice.py:23` | 1 |
| `P/core/voice.py` | MODIFY | `    pause_ms: int | None = None` | `core/voice.py:43` | 1 |
| `P/core/voice.py` | MODIFY | `    hint_pause_ms: int = Field(default=600, ge=0)` | `core/voice.py:56` | 1 |
| `P/audio/narration/engine.py` | MODIFY | `    def _options_text(self, q: AudioQuestion, cfg: VoiceFormConfig, meta: FieldVoiceMeta) -> str | None:` | `narration/engine.py:134` | 1 |
| `P/audio/narration/engine.py` | MODIFY | `        options_text = self._options_text(q, cfg, meta)` | `narration/engine.py:167` | 1 |
| `P/audio/events.py` | MODIFY | `    kind: str  # "question" | "hint" | "options" | "system" | "review"` | `events.py:302` | 1 |
| `P/api/audio_ws.py` | MODIFY | `    def _segment_kind(key: str) -> str:` | `audio_ws.py:901` | 1 |
| `P/api/audio_ws.py` | MODIFY | `                if len(parts) == 3 and parts[0] == "q" and parts[2] in ("label", "hint", "options"):` | `audio_ws.py:946` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py` | MODIFY | `def test_plan_question_options_rules():` | `test_narration_engine.py:89` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | `#### \`audio_segment\`` | `:806` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | `| \`hands_free\` | \`{auto_record: bool, silence_ms: int}\` | omitted when hands-free is not configured |` | `:936` | 1 |
| `docs/audio-form-voice-modes.md` | MODIFY | `### 7.4 Hands-free commands` | `:961` | 1 |
| `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` | MODIFY | `- **Hands-free is a client policy**` | `:94` | 1 |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | (top "Unreleased" section — `(unverified — check before use)`) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Pydantic v2 models with `Field(..., ge=0)` validation, as the neighbouring fields do.
- Keep `plan_question`'s contract: `segments` insertion order == `audio_keys` order minus
  `pause:` keys. `_synthesize_request` relies on `dict` order to build `Synthesize.keys`, and
  the v1 inline grouping joins texts in that order.
- Narration texts come only from `narration.yaml` templates (`options_intro`, `option_item`);
  no new template keys are needed, so `NARRATION_KEYS` is untouched.
- `pause:` keys are never synthesised (`_synth_items` already skips them) and never cached.
- Tests: reuse `_q()` in `test_narration_engine.py` and the fake synthesizer / transcriber
  harnesses in `test_audio_ws_adapter.py` and `test_audio_ws_v2_integration.py`. Run with
  `PYTHONPATH=packages/parrot-formdesigner/src` from a worktree.
- Docs: the file is bilingual-agnostic English; keep the section numbering of the existing
  TOC and add the new entries to the TOC at the top.

### Known Risks / Gotchas
- **Acoustic echo self-triggering VAD.** With `barge_in: true` and the mic open during
  playback, the form's own TTS can trip the client VAD on speaker-phone devices. This is why
  the flag exists and why the docs must prescribe `echoCancellation: true`, a raised energy
  threshold during playback and `barge_in: false` as the escape hatch. The server cannot
  mitigate this.
- **Short interrupted recordings.** A false VAD onset followed by silence produces a tiny
  container; `_process_binary` already rejects it with `EMPTY_AUDIO` (`< _MIN_AUDIO_BYTES`).
  Clients should treat `EMPTY_AUDIO` after a barge-in as "resume playback where it stopped",
  and the docs must say so.
- **Longer enumeration.** Per-option pauses lengthen the narration of long option lists
  (`n-1` × `option_pause_ms`). Authors can set `option_pause_ms: 0` per field or at form
  level; with barge-in the user usually cuts the list short anyway.
- **v1 grouping regression.** Forgetting to extend the `parts[2] in (...)` rule at
  `audio_ws.py:946` silently drops the options from `question.audio` for v1 clients — covered
  by `test_do_synthesize_v1_inline_groups_option_keys`.
- **`_segment_kind` fallthrough.** `q:<uid>:opt:<n>` ends with a number, so a naive
  `endswith(":options")` check misses it; match on the `:opt:` segment explicitly.
- **Existing test breakage is intentional.** `test_plan_question_options_rules` asserts the
  single `q:<uid>:options` key for the enumerated case; it must be rewritten (not deleted)
  into the single-segment-cases test plus the new per-option tests.
- **Parallel feature on the same files.** FEAT-653 (`audio-form-voice-postprocessors`)
  modifies `core/voice.py`, `audio/events.py`, `audio/engine.py` and
  `docs/audio-form-voice-modes.md`. The regions differ (post-processing config / confirm
  value vs. hands-free / narration), so a rebase should merge cleanly, but whichever branch
  lands second must rebase on `origin/dev` before `/sdd-done`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; pydantic, jinja2 and pyyaml are already used by the narration engine. |

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-654
  (`.claude/worktrees/feat-FEAT-654-voice-form-barge-in`, from `origin/dev`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M1 and M2 have **no symbol dependency** on each other, but both modify
    `P/core/voice.py` (M1 edits `HandsFreeConfig`, M2 edits `FieldVoiceMeta` and
    `VoiceFormConfig`) — their tasks touching that file are serialized; the rest of M2
    (narration, events, audio_ws, tests) can run concurrently with M1.
  - M3 → M1 and M2 (documents the names and defaults they introduce).
- **Shared files**: `P/core/voice.py` (M1, M2).
- **Exclusive resources**: none (no migrations, no lockfile, no extension rebuild).
- **Cross-feature dependencies**: none blocking. FEAT-653 (`audio-form-voice-postprocessors`,
  approved, in progress) touches the same files in different regions; see §7 Known Risks for
  the rebase rule.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should the server detect end-of-speech (VAD) itself? — *Resolved by the user,
  2026-10-12*: no; barge-in is a client policy, the server keeps one-complete-container
  per answer. (Reaffirms FEAT-649 §8 "Hands-free end-of-speech".)
- [x] Should the interruption and the multi-choice gap be in the same spec? — *Resolved by
  the user, 2026-10-12*: yes, both in FEAT-654.
- [x] Where does the pause go? — *Decided in this spec*: between consecutive option items
  only; none after the intro, none after the last item.
- [ ] Default `option_pause_ms`: 500 ms is proposed; confirm against a real device test with
  the navigator-svelte renderer (a longer gap makes the enumeration slower, a shorter one
  gives the VAD less room). — *Owner: Jesus Lara*
- [ ] Should `barge_in` be exposed as a `start_session` override in a later iteration (per
  device capability, e.g. no AEC)? — *Owner: Jesus Lara* (not blocking; form-level only now)

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: — · Status: skipped (no accepted brainstorm or
> proposal exists for this slug; the spec was written from the user's notes and the verified
> code anchors in §6) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-12 | Jesus Lara | Initial draft (barge_in flag, per-option narration segments, docs) |
