# TASK-4251: Engine — rules post-processor, decision matrix, typed email, timezone, provenance

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4245, TASK-4246, TASK-4247, TASK-4248, TASK-4250
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (steps 1, 3–6 and the decision matrix) and §3 Module 7, first half. This task
wires the deterministic post-processors into the pure engine's free-form speech path. It replaces
today's "store `ev.text` raw" block (`engine.py:426-441`) with:
- rules normalization;
- the §2 **decision matrix**, which yields reject / confirm / accept;
- provenance (`normalized_by`, `llm_confidence`) carried through `state.pending` → `_accept`, so it
  survives a confirmation (design research S8).

It also adds typed-answer EMAIL validation, records the client timezone on start/resume, and
gives the engine an injectable clock.

The LLM refine step is TASK-4252. This task leaves exactly one insertion point for it (see the
blueprint).

---

## Scope

- Add an optional `clock` dependency and `_normalize_ctx()`.
- `on_start` and `_resume` record `ev.timezone` in `state.timezone` (never from the snapshot).
- Replace the free-form block with: rules (`meta.normalize`) → `_gate(...)`.
- Add `_gate()`, which implements the decision matrix exactly.
- `_request_confirm` and `_accept` gain `refined_by` / `normalized_by` and `llm_confidence`
  keyword args; `on_confirm` forwards them from `state.pending`.
- `ConfirmRequest.value` / `refined_by` are set only for post-processed candidates.
  `AnswerRejected.value` carries the rejected candidate. Both are omitted for sensitive fields.
- `on_text`: a non-empty invalid typed EMAIL → `AnswerRejected(code="INVALID_EMAIL")`.
- Write `test_audio_engine_postprocess.py`.

**NOT in scope**: `RefineValue` / `on_value_refined` / `_llm_refine_enabled` (TASK-4252); the
adapter (TASK-4253); the option path and commands (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | Normalization, gate, provenance, timezone, typed email |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_postprocess.py` | CREATE | Engine tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside audio/engine.py (relative, matching the file's style)
from .normalize import NormalizeContext, NormalizeResult, normalize_spoken, validate_typed   # TASK-4245
from datetime import datetime, timezone                                                      # stdlib
from zoneinfo import ZoneInfo                                                                # stdlib
# already imported in engine.py: logging, Any, Callable (:11-12), FieldType (:16),
#   field_voice_meta, is_sensitive (:17), AnswerRejected, ConfirmRequest (:20-71), AudioAnswer (via .models :72-80)
```

### Existing Signatures to Use
```python
# audio/engine.py
_SENSITIVE_MASK                                     # module constant used by on_transcript/_request_confirm
_ANSWERING_PHASES = (Phase.ASKING, Phase.CONFIRMING)   # :88
class AudioFormSession:
    def __init__(self, *, form, manifest, cfg, narrator, lexicon, state, llm_cfg: LLMValidationConfig | None) -> None   # :104-113
        self.llm_cfg = llm_cfg                                                    # :121
    def on_start(self, ev: StartSession) -> list[Outbound]   # :169; `self.state.locale = ev.locale` :175
    def on_transcript(self, ev: TranscriptReady) -> list[Outbound]   # :348
        # local names in scope at the free-form block: field, q, meta (FieldVoiceMeta), sensitive, out, evidence, confirm_pref
        # evidence = AudioAnswer(field_id, value=None, source="speech", confidence=ev.confidence,
        #     raw_transcript=None if sensitive else ev.text, audio_mime, audio_bytes_len, duration_ms, stt_language=ev.language)  # :368-379
        # `        # Free-form answer` :426 … `        )` :441 — the block this task replaces
    def _request_confirm(self, evidence, value, transcript, matched, alternatives) -> list[Outbound]   # :442-462
        # self.state.pending = evidence.model_copy(update={"value": value, "matched": matched})   # :452
    def _accept(self, field_id, value, *, source, confidence=None, raw=None, matched=None, evidence=None)   # :464
        # builds AudioAnswer(field_id=..., field_uid=..., value=..., source=..., confidence=..., raw_transcript=raw, matched=..., version=..., **extra)   # :485-494
    def on_text(self, ev: AnswerText) -> list[Outbound]                        # :523
        # `        if self.planner.effective_required(ev.field_id) and not ev.value.strip():` :528 (unique)
    def on_confirm(self, ev: ConfirmAnswer) -> list[Outbound]                  # :566; accept call :589-597 ends `                evidence=pending,` :597
    def _resume(self, ev: StartSession) -> list[Outbound]                      # :1048; `self.state.locale = ev.locale` :1083
    self.narrator.render(key) -> str    # keys "invalid_email" / "invalid_value" added by TASK-4244
# audio/models.py (TASK-4248): AudioAnswer.normalized_by, .llm_confidence; AudioSessionState.timezone
# audio/events.py (TASK-4248): ConfirmRequest.value, .refined_by; AnswerRejected.value; StartSession.timezone
# core/voice.py: FieldVoiceMeta.confirm: Literal["auto","always","never"] (:42), .normalize (TASK-4248); VoiceFormConfig.stt_confirm_threshold (:58), .llm_refine_threshold (TASK-4248)
```

### Does NOT Exist
- ~~`Phase.REFINING`~~ — not added.
- ~~`asyncio` / `await` in engine.py~~ — forbidden (`test_engine_has_no_await`, test_audio_engine_turns.py:57).
- ~~`ConfirmAnswer.value`~~ — "yes" stores `state.pending.value`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_postprocess.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession.on_transcript",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession._request_confirm",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession._accept",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession.on_text",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession.on_confirm",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession._resume"
  ]
}
```

---

## Implementation Notes

### Decision matrix (spec §2 — implement exactly, nothing else)
- "STT low" = `(1.0 if evidence.confidence is None else evidence.confidence) < cfg.stt_confirm_threshold`
  and `meta.confirm != "never"`.
- "LLM low" = `refined_by == "llm"` and `(llm_confidence or 0.0) < cfg.llm_refine_threshold`.

| candidate.status | outcome |
|---|---|
| `rejected` | `AnswerRejected(code="INVALID_EMAIL" if EMAIL else "INVALID_VALUE", error=narrator.render("invalid_email"/"invalid_value"), value=None if sensitive else candidate.value)`; phase and cursor unchanged (like `NO_MATCH`) |
| `confirm` | `_request_confirm(...)`, even when `meta.confirm == "never"` |
| `accepted` | confirm if `meta.confirm == "always"` or STT low or LLM low; else `_accept(...)` |

`ConfirmRequest.value` / `refined_by` are set **only when `refined_by` is not None**. Option-path
and raw-text confirmations keep today's wire shape exactly, so existing tests stay green.

---

## Implementation Blueprint

### Steps (in order)
1. Imports + `clock` param + `_normalize_ctx` — *why*: relative dates need "now" in the client timezone, and tests need a fixed clock.
2. Timezone on start/resume — *why*: resume gets a fresh `start_session`; never trust a snapshot for it (spec correction table).
3. Extend `_request_confirm` / `_accept` / `on_confirm` — *why*: provenance must survive "yes" (S8).
4. Add `_gate` and replace the free-form block — *why*: single decision point (S9).
5. Typed EMAIL validation in `on_text` — *why*: G2 / AC2.
6. Tests.

### `audio/engine.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c '^from .session_store import AudioSnapshot' engine.py)
# AFTER — insert below `from .session_store import AudioSnapshot` (verified: engine.py:85)
from .normalize import NormalizeContext, NormalizeResult, normalize_spoken, validate_typed
```
Add `from datetime import datetime, timezone` and `from zoneinfo import ZoneInfo` to the stdlib
import group (after `import logging`, engine.py:11).

### `audio/engine.py` (MODIFY) — constructor + context
```python
# occurrences: 1 (verified: grep -c '        llm_cfg: LLMValidationConfig | None,' engine.py)
# AFTER — insert below `        llm_cfg: LLMValidationConfig | None,` (verified: engine.py:113)
        clock: Callable[[], datetime] | None = None,
```
```python
# occurrences: 1 (verified: grep -c '        self.llm_cfg = llm_cfg' engine.py)
# AFTER — insert below `        self.llm_cfg = llm_cfg` (verified: engine.py:121)
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))
```
Add as a method (next to `_is_empty`):
```python
    def _normalize_ctx(self) -> NormalizeContext:
        """now = clock() in ZoneInfo(state.timezone) when valid, else UTC with timezone_known=False."""
        now = self._clock()
        tz_name = self.state.timezone
        if tz_name:
            try:
                return NormalizeContext(lexicon=self.lexicon, now=now.astimezone(ZoneInfo(tz_name)), timezone_known=True)
            except Exception:  # noqa: BLE001 — invalid/unknown zone: degrade, never fail the turn
                self.logger.debug("invalid session timezone %r; using UTC", tz_name)
        return NormalizeContext(lexicon=self.lexicon, now=now.astimezone(timezone.utc), timezone_known=False)
```

### `audio/engine.py` (MODIFY) — timezone on start and resume
```python
# occurrences: 2 (verified: grep -c '        self.state.locale = ev.locale' engine.py) — :175 (on_start) and :1083 (_resume)
# Apply to BOTH occurrences: insert below each `        self.state.locale = ev.locale`
        self.state.timezone = ev.timezone
```
**Why**: both are intended. `_resume` must take the timezone from the new `start_session`, never
from `AudioSnapshot`.

### `audio/engine.py` (MODIFY) — provenance through confirm
```python
# _request_confirm (verified :442): add keyword-only params after `alternatives: list[OptionMatch],`
        *,
        refined_by: str | None = None,
        llm_confidence: float | None = None,
# occurrences: 1 (verified: grep -c 'self.state.pending = evidence.model_copy(update={"value": value, "matched": matched})' engine.py)
# REPLACE engine.py:452 with:
        self.state.pending = evidence.model_copy(
            update={"value": value, "matched": matched, "normalized_by": refined_by, "llm_confidence": llm_confidence}
        )
# In the ConfirmRequest(...) built right below, add (only when post-processed — keeps legacy wire shape):
                value=None if (sensitive or refined_by is None) else value,
                refined_by=refined_by,
```
```python
# _accept (verified :464): add keyword-only params after `evidence: AudioAnswer | None = None,`
        normalized_by: str | None = None,
        llm_confidence: float | None = None,
# occurrences: 1 (verified: grep -c '            raw_transcript=raw,' engine.py)
# AFTER — insert below `            raw_transcript=raw,` inside the AudioAnswer(...) (verified: engine.py:492)
            normalized_by=normalized_by,
            llm_confidence=llm_confidence,
```
```python
# occurrences: 1 (verified: grep -c '                evidence=pending,' engine.py)
# AFTER — insert below `                evidence=pending,` in on_confirm (verified: engine.py:597)
                normalized_by=pending.normalized_by,
                llm_confidence=pending.llm_confidence,
```

### `audio/engine.py` (MODIFY) — gate + free-form block
Add the method (after `_request_confirm`):
```python
    def _gate(
        self,
        evidence: AudioAnswer,
        candidate: NormalizeResult,
        *,
        refined_by: str | None,
        llm_confidence: float | None,
    ) -> list[Outbound]:
        """Single reject/confirm/accept decision: the §2 decision matrix, nothing else."""
        field = self._fields[evidence.field_id]
        meta = field_voice_meta(field, logger=self.logger)
        sensitive = is_sensitive(field)
        transcript = evidence.raw_transcript or ""
        # FILL IN: the matrix in Implementation Notes — rejected → [AnswerRejected(...)]; confirm →
        # self._request_confirm(evidence, candidate.value, transcript, None, [], refined_by=..., llm_confidence=...);
        # accepted → confirm-or-_accept(evidence.field_id, candidate.value, source="speech", confidence=evidence.confidence,
        # raw=evidence.raw_transcript, evidence=evidence, normalized_by=refined_by, llm_confidence=llm_confidence)
        raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c '        # Free-form answer' engine.py)
# REPLACE engine.py:426-441 (from `        # Free-form answer` through the closing `        )` of the final _accept call) with:
        # Free-form answer — FEAT-653 typed post-processors, then the decision matrix
        if not ev.text.strip():
            return out + [AnswerRejected(field_id=ev.field_id, error="Empty transcript", code="EMPTY")]
        result = normalize_spoken(field.field_type, ev.text, ctx=self._normalize_ctx()) if meta.normalize else None
        candidate = result if result is not None else NormalizeResult.accepted(ev.text)
        refined_by = "rules" if result is not None else None
        # (TASK-4252 inserts the optional LLM refine hand-off here)
        return out + self._gate(evidence, candidate, refined_by=refined_by, llm_confidence=None)
```
**Why**: with `normalize` off or an unhandled type, the candidate is the raw text with
`refined_by=None`. The matrix then reduces exactly to today's FEAT-649 behaviour, which keeps
all existing engine tests green.

### `audio/engine.py` (MODIFY) — typed email
```python
# occurrences: 1 (verified: grep -c '        if self.planner.effective_required(ev.field_id) and not ev.value.strip():' engine.py)
# AFTER the 2-line `if ...: return [AnswerRejected(... code="REQUIRED")]` that follows this anchor (verified: engine.py:528-529), insert:
        code = validate_typed(self._fields[ev.field_id].field_type, ev.value)
        if code is not None:
            return [AnswerRejected(field_id=ev.field_id, error=self.narrator.render("invalid_email"), code=code)]
```

### `tests/formdesigner/test_audio_engine_postprocess.py` (CREATE)
```python
"""FEAT-653 TASK-4251 — engine: typed post-processors, decision matrix, provenance, timezone."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.engine import AudioFormSession
from parrot_formdesigner.audio.events import (
    AnswerAccepted,
    AnswerRejected,
    AnswerText,
    ConfirmAnswer,
    ConfirmRequest,
    PlanReady,
    StartSession,
    TranscriptReady,
)
from parrot_formdesigner.audio.models import AudioFormManifest, AudioSessionState
from parrot_formdesigner.audio.narration.engine import Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.renderers.audio import AudioFormRenderer
from parrot_formdesigner.services.rule_evaluator import RuleResolution

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # Monday


def _build(fields: list[FormField], *, tz: str | None = "America/New_York", locale: str = "en",
           cfg: VoiceFormConfig | None = None) -> AudioFormSession:
    """Same construction as test_audio_engine_turns._build, with a fixed clock and the given fields."""
    form = FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s1", title="S", fields=fields)])
    questions = AudioFormRenderer().split_into_questions(form, locale=locale)
    manifest = AudioFormManifest(form_uid=str(form.form_uid), title="F", total_questions=len(questions),
                                 questions=questions, ws_endpoint="/ws", locale=locale)
    state = AudioSessionState(session_id="sess", form_uid=str(form.form_uid), user_id="u", manifest=manifest)
    s = AudioFormSession(form=form, manifest=manifest, cfg=cfg or VoiceFormConfig(max_questions=None),
                         narrator=Narrator(locale), lexicon=load_lexicon(locale), state=state, llm_cfg=None,
                         clock=lambda: NOW)
    s.handle(StartSession(type="start_session", form_uid=str(form.form_uid), locale=locale, protocol_version=2, timezone=tz))
    plan, delta = asyncio.run(s.planner.replan(s.state.answers, locale=locale, resolution=RuleResolution()))
    s.handle(PlanReady(type="_plan_ready", plan=plan, delta=delta.model_dump()))
    return s


def _tr(field_id: str, text: str, confidence: float | None = 0.95) -> TranscriptReady:
    return TranscriptReady(type="_transcript", field_id=field_id, text=text, confidence=confidence,
                           audio_mime="audio/webm", audio_bytes_len=3)


def _f(fid: str, ft: FieldType, **kw) -> FormField:
    return FormField(field_id=fid, field_type=ft, label=fid.title(), required=True, **kw)


class TestFreeFormNormalization:
    def test_phone_stored_canonical_with_provenance(self) -> None:
        s = _build([_f("phone", FieldType.PHONE)])
        out = s.handle(_tr("phone", "0,4,12,523,573"))
        acc = next(o for o in out if isinstance(o, AnswerAccepted))
        assert acc.value == "0412523573"
        ans = s.state.answers["phone"]
        assert ans.raw_transcript == "0,4,12,523,573" and ans.normalized_by == "rules"

    def test_text_field_unchanged(self) -> None:
        s = _build([_f("name", FieldType.TEXT)])
        out = s.handle(_tr("name", "en Manuel"))
        assert next(o for o in out if isinstance(o, AnswerAccepted)).value == "en Manuel"
        assert s.state.answers["name"].normalized_by is None


class TestDecisionMatrix:
    def test_rejected_email_reasks_with_candidate(self) -> None:
        s = _build([_f("email", FieldType.EMAIL)])
        out = s.handle(_tr("email", "john at gmail"))
        rej = next(o for o in out if isinstance(o, AnswerRejected))
        assert rej.code == "INVALID_EMAIL" and rej.value == "john@gmail"
        assert "email" not in s.state.answers and s.state.cursor == "email"

    def test_confirm_status_confirms_even_with_never(self) -> None:
        s = _build([_f("t", FieldType.TIME, meta={"voice": {"confirm": "never"}})])
        out = s.handle(_tr("t", "three thirty"))
        cr = next(o for o in out if isinstance(o, ConfirmRequest))
        assert cr.value == "03:30" and cr.refined_by == "rules"

    def test_low_stt_confirms_accepted_value(self) -> None:
        s = _build([_f("n", FieldType.NUMBER)])
        out = s.handle(_tr("n", "twenty five", confidence=0.2))
        assert next(o for o in out if isinstance(o, ConfirmRequest)).value == 25

    def test_provenance_survives_confirm(self) -> None:
        s = _build([_f("n", FieldType.NUMBER)])
        s.handle(_tr("n", "twenty five", confidence=0.2))
        s.handle(ConfirmAnswer(type="confirm_answer", field_id="n", confirmed=True))
        assert s.state.answers["n"].value == 25 and s.state.answers["n"].normalized_by == "rules"

    def test_relative_date_without_timezone_confirms(self) -> None:
        s = _build([_f("d", FieldType.DATE)], tz=None)
        out = s.handle(_tr("d", "tomorrow"))
        assert isinstance(next(o for o in out if isinstance(o, ConfirmRequest)), ConfirmRequest)


class TestTypedAndResume:
    def test_typed_email_rejected_typed_phone_kept(self) -> None:
        s = _build([_f("email", FieldType.EMAIL), _f("phone", FieldType.PHONE)])
        out = s.handle(AnswerText(type="answer_text", field_id="email", value="john at gmail"))
        assert next(o for o in out if isinstance(o, AnswerRejected)).code == "INVALID_EMAIL"
        # FILL IN: answer email correctly by text, advance the plan, then answer_text phone "0,4,12" → stored as typed

    def test_timezone_recorded_and_resume_takes_new_value(self) -> None:
        s = _build([_f("d", FieldType.DATE)], tz="America/New_York")
        assert s.state.timezone == "America/New_York"
        # FILL IN: snapshot() → AudioFormSession.from_snapshot(...) (see test_audio_engine_review_resume.py for the
        # resume construction) → handle StartSession(resume_session_id=..., timezone="Europe/Madrid") →
        # state.timezone == "Europe/Madrid"; a spoken answer's normalized_by survives the snapshot round trip

    def test_submission_envelope_carries_provenance(self) -> None:
        # FILL IN: answer a PHONE by voice, then s._submission_data()["phone"]["normalized_by"] == "rules"
        ...
```

### FILL IN checklist
- [ ] `_gate` — exactly the Implementation Notes matrix (AC3)
- [ ] remaining test bodies (typed phone kept, resume timezone + provenance, submission envelope)

---

## Acceptance Criteria

- [ ] AC1/AC3/AC5 behaviours above hold; `rejected` values are never stored or offered as "yes".
- [ ] All existing engine tests pass unmodified (`test_audio_engine_turns.py`, `test_audio_engine_review_resume.py`), including `test_engine_has_no_await`.
- [ ] `ruff check` clean on engine.py.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_postprocess.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract (re-run every `grep -c` anchor; line numbers shift as you edit — apply edits bottom-up or re-grep).
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4251 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
