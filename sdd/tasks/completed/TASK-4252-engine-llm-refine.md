# TASK-4252: Engine — optional LLM refine hand-off (RefineValue / on_value_refined)

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4251
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 2 and §3 Module 7, second half. When `llm_refine` is in effect for a
typed-family, non-sensitive field, the engine hands the answer to the LLM post-processor.

The engine is pure and never awaits, so the hand-off is an I/O request (design research S6):
1. The engine parks the rules result and emits `RefineValue`.
2. The adapter (TASK-4253) awaits `LLMValueRefiner` under a timeout and feeds back `ValueRefined`.
3. `on_value_refined` re-normalizes the LLM string with the same rules normalizer. A usable
   result becomes the candidate (`refined_by="llm"`); otherwise the rules result stands.
4. Either way the candidate goes through `_gate` (TASK-4251).

The LLM never overrides the STT rule or `confirm: "always"`.

Owner decisions: it runs on **every** spoken answer of an enabled field (§8 Q7); it is never
enabled on TEXT/TEXT_AREA (§8 Q3); sensitive fields never reach it (S8).

---

## Scope

- `REFINABLE_TYPES` gating, plus `_llm_refine_enabled(field, meta)`: `meta.llm_refine`, falling
  back to `cfg.llm_refine_values`. False for sensitive fields and for types outside
  `REFINABLE_TYPES`; a field-level `llm_refine: true` on another type logs one warning per field.
- At the TASK-4251 insertion point in the free-form block: when enabled, store a private pending
  refine and return `out + [RefineValue(...)]`.
- `on_value_refined(ev)`, registered in `_handlers` as `"_value_refined"`:
  - drop a stale reply (no pending refine, field or `request_id` mismatch, cursor moved);
  - otherwise re-normalize and `_gate`.
- Write `test_audio_engine_llm_refine.py`.

**NOT in scope**: performing the LLM call or the timeout (adapter, TASK-4253); the refiner
itself (TASK-4249).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py` | MODIFY | Refine hand-off + `on_value_refined` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_llm_refine.py` | CREATE | Engine tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .normalize import REFINABLE_TYPES        # TASK-4245 (re-exported from normalize/base.py)
from .events import RefineValue, ValueRefined  # TASK-4248 — add to the existing `from .events import (...)` block (engine.py:20-71)
import uuid                                    # stdlib, for request_id
from dataclasses import dataclass              # stdlib, for the private pending record
```

### Existing Signatures to Use
```python
# audio/engine.py after TASK-4251
self._handlers = {..., "_plausibility_done": self.on_plausibility_done, ...}   # :155 (anchor, 1 occurrence)
def _normalize_ctx(self) -> NormalizeContext            # TASK-4251 (ctx.now in client tz)
def _gate(self, evidence, candidate, *, refined_by, llm_confidence) -> list[Outbound]   # TASK-4251
# free-form block (TASK-4251) contains the marker line:
#   `        # (TASK-4252 inserts the optional LLM refine hand-off here)`
#   with locals in scope: field, q (AudioQuestion; q.label: str), meta, sensitive, out, evidence, candidate, refined_by, ev
def normalize_spoken(field_type, text, *, ctx) -> NormalizeResult | None   # TASK-4245
# core/voice.py (TASK-4248): FieldVoiceMeta.llm_refine: bool | None; VoiceFormConfig.llm_refine_values: bool
# events.py (TASK-4248): RefineValue(field_id, request_id, transcript, candidate, field_type: str, label, today)
#   ValueRefined(type="_value_refined", field_id, request_id, status: "ok"|"failed"|"unavailable", value: str|None, confidence: float|None)
```

### Does NOT Exist
- ~~`Phase.REFINING`~~ — the pending refine is a private attribute, never snapshotted. `_resume` already drops `pending` and re-plans (engine.py:1085-1090), so a crash mid-refine resumes like a crash mid-confirm.
- ~~`await` in the engine~~ — the LLM call happens in the adapter.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_llm_refine.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#AudioFormSession.on_transcript"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add imports, the `_PendingRefine` record and `self._refining` — *why*: the rules result must be kept to fall back on.
2. Add `_llm_refine_enabled` — *why*: one policy point (Q3, S8, AC14).
3. Insert the hand-off at the TASK-4251 marker — *why*: refine runs after rules, before the gate.
4. Add and register `on_value_refined` — *why*: re-normalize, never trust LLM output (AC6).
5. Tests.

### `audio/engine.py` (MODIFY) — record + init
Module level (below the existing module constants such as `_REVIEW_FIELD`, engine.py:90):
```python
@dataclass
class _PendingRefine:
    """An answer parked while the LLM post-processor runs (never snapshotted)."""

    evidence: AudioAnswer
    rules: NormalizeResult
    rules_by: str | None
    request_id: str
```
In `__init__`, next to `self._resume_snap` (engine.py:132):
```python
        self._refining: _PendingRefine | None = None
        self._refine_warned: set[str] = set()
```

### `audio/engine.py` (MODIFY) — policy
```python
    def _llm_refine_enabled(self, field: FormField, meta: FieldVoiceMeta) -> bool:
        """meta.llm_refine if not None else cfg.llm_refine_values; False for sensitive fields and for any type
        outside REFINABLE_TYPES = {EMAIL, PHONE, NUMBER, INTEGER, DATE, TIME, DATETIME}."""
        wanted = meta.llm_refine if meta.llm_refine is not None else self.cfg.llm_refine_values
        if not wanted or is_sensitive(field):
            return False
        if field.field_type not in REFINABLE_TYPES:
            # FILL IN: warn once per field_id (self._refine_warned) only when meta.llm_refine is True; return False
            return False
        return True
```
Import `FieldVoiceMeta` from `..core.voice` (it already imports `VoiceFormConfig, field_voice_meta, is_sensitive` at engine.py:17).

### `audio/engine.py` (MODIFY) — hand-off
```python
# occurrences: 1 (verified after TASK-4251: grep -c '# (TASK-4252 inserts the optional LLM refine hand-off here)' engine.py)
# REPLACE that marker line with:
        if self._llm_refine_enabled(field, meta):
            request_id = uuid.uuid4().hex
            self._refining = _PendingRefine(evidence=evidence, rules=candidate, rules_by=refined_by, request_id=request_id)
            return out + [
                RefineValue(
                    field_id=ev.field_id,
                    request_id=request_id,
                    transcript=ev.text,
                    candidate=candidate.value,
                    field_type=field.field_type.value,
                    label=q.label,
                    today=self._normalize_ctx().now.date().isoformat(),
                )
            ]
```

### `audio/engine.py` (MODIFY) — feedback
```python
# occurrences: 1 (verified: grep -c '            "_plausibility_done": self.on_plausibility_done,' engine.py)
# AFTER — insert below `            "_plausibility_done": self.on_plausibility_done,` (verified: engine.py:155)
            "_value_refined": self.on_value_refined,
```
```python
    def on_value_refined(self, ev: ValueRefined) -> list[Outbound]:
        """Drop when stale (no in-flight refine, field or request_id mismatch); else re-normalize and _gate."""
        pending = self._refining
        if pending is None or ev.request_id != pending.request_id or ev.field_id != pending.evidence.field_id:
            return []
        self._refining = None
        if self.state.cursor != ev.field_id:
            return []
        field = self._fields[ev.field_id]
        if ev.status == "ok" and ev.value is not None:
            renorm = normalize_spoken(field.field_type, ev.value, ctx=self._normalize_ctx())
            # FILL IN: renorm not None and renorm.status != "rejected" → return self._gate(pending.evidence, renorm,
            # refined_by="llm", llm_confidence=ev.confidence if ev.confidence is not None else 0.0)
        # FILL IN: fall back → self._gate(pending.evidence, pending.rules, refined_by=pending.rules_by, llm_confidence=None)
        raise NotImplementedError
```

### `tests/formdesigner/test_audio_engine_llm_refine.py` (CREATE)
```python
"""FEAT-653 TASK-4252 — engine LLM refine hand-off."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.events import AnswerAccepted, AnswerRejected, ConfirmRequest, RefineValue, ValueRefined
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig

# Reuse the builders from the TASK-4251 test module (same package, plain import).
from .test_audio_engine_postprocess import _build, _f, _tr  # FILL IN: if relative import fails under the
# package's pytest config, copy _build/_f/_tr here verbatim instead


def _cfg(**kw) -> VoiceFormConfig:
    return VoiceFormConfig(max_questions=None, llm_refine_values=True, **kw)


def _vr(req: RefineValue, status: str = "ok", value: str | None = None, confidence: float | None = None) -> ValueRefined:
    return ValueRefined(type="_value_refined", field_id=req.field_id, request_id=req.request_id,
                        status=status, value=value, confidence=confidence)


def test_refine_emitted_and_high_confidence_accepts() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    out = s.handle(_tr("email", "john at gmail"))
    req = next(o for o in out if isinstance(o, RefineValue))
    assert req.candidate == "john@gmail" and req.field_type == "email" and req.today == "2026-10-12"
    out = s.handle(_vr(req, value="john@gmail.com", confidence=0.95))
    assert next(o for o in out if isinstance(o, AnswerAccepted)).value == "john@gmail.com"
    ans = s.state.answers["email"]
    assert ans.normalized_by == "llm" and ans.llm_confidence == 0.95


def test_low_llm_confidence_confirms() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = next(o for o in s.handle(_tr("email", "john at gmail")) if isinstance(o, RefineValue))
    cr = next(o for o in s.handle(_vr(req, value="john@gmail.com", confidence=0.3)) if isinstance(o, ConfirmRequest))
    assert cr.value == "john@gmail.com" and cr.refined_by == "llm"


def test_llm_never_overrides_low_stt() -> None:
    s = _build([_f("n", FieldType.NUMBER)], cfg=_cfg())
    req = next(o for o in s.handle(_tr("n", "twenty five", confidence=0.1)) if isinstance(o, RefineValue))
    assert any(isinstance(o, ConfirmRequest) for o in s.handle(_vr(req, value="25", confidence=0.99)))


@pytest.mark.parametrize("status,value", [("failed", None), ("unavailable", None), ("ok", "not an email")])
def test_fallback_to_rules(status: str, value: str | None) -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = next(o for o in s.handle(_tr("email", "john at gmail")) if isinstance(o, RefineValue))
    out = s.handle(_vr(req, status=status, value=value, confidence=0.9))
    assert next(o for o in out if isinstance(o, AnswerRejected)).code == "INVALID_EMAIL"  # rules result was rejected


def test_stale_reply_ignored() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = next(o for o in s.handle(_tr("email", "john at gmail")) if isinstance(o, RefineValue))
    stale = req.model_copy(update={"request_id": "other"})
    assert s.handle(_vr(stale, value="x@y.io", confidence=0.99)) == []


def test_text_and_sensitive_never_refined() -> None:
    s = _build([_f("name", FieldType.TEXT, meta={"voice": {"llm_refine": True}})], cfg=_cfg())
    assert not any(isinstance(o, RefineValue) for o in s.handle(_tr("name", "en Manuel")))
    # FILL IN: an EMAIL field with meta {"voice": {"sensitive": True}} under _cfg() → no RefineValue, and any
    # ConfirmRequest/AnswerRejected it produces carries value None


def test_field_opt_out_overrides_form() -> None:
    # FILL IN: _cfg() + field meta {"voice": {"llm_refine": False}} → no RefineValue; and form default False +
    # field meta {"voice": {"llm_refine": True}} on PHONE → RefineValue emitted
    ...
```

### FILL IN checklist
- [ ] `_llm_refine_enabled` warn-once branch
- [ ] `on_value_refined` re-normalize + fallback
- [ ] test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] AC6, AC7, AC14 hold (exactly one `RefineValue` per enabled spoken answer; sensitive and TEXT never refined; fallback on failure).
- [ ] The LLM never auto-accepts against low STT confidence or `confirm: "always"` (AC3).
- [ ] TASK-4251 tests and the existing engine tests still pass; `test_engine_has_no_await` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_llm_refine.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_turns.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Read the spec; check `Depends-on` tasks are `done` in `sdd/tasks/index/audio-form-voice-postprocessors.json`.
3. Verify the Codebase Contract (the marker line from TASK-4251 must exist exactly once).
4. Set this task `in-progress` in the index and commit only the index.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed name or path.
6. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4252 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5, sequential fallback loop)
**Date**: 2026-10-12
**Notes**: _llm_refine_enabled, RefineValue hand-off, on_value_refined (stale drop, re-normalize, fallback). 14 new tests + engine suites pass; ruff clean.

**Deviations from spec**: none
