# TASK-4223: FormValidator: accept voice envelopes on any field type (unwrap → validate scalar → re-fold)

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4210
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (`services/validators.py` part), goal G6, AC8, design-research S3. Every spoken
answer — on ANY field type — is stored as a `VoiceEvidenceEnvelope` in `data[field_id]`. Today
`FormValidator` only understands envelopes on TEXT/TEXT_AREA fields that declare
`answer_envelope == "voice"` (FEAT-488, `services/validators.py:543-548`, `:629-640`); an envelope
on a SELECT/BOOLEAN/NUMBER/MULTI_SELECT field is coerced through `str()` or rejected. This task
widens acceptance: an evidence envelope is unwrapped, its `answer` is validated with the field's
normal rules, and the coerced scalar is re-folded into the envelope. FEAT-488's contract
(`VoiceAnswerEnvelope` with `answer: str`, extra forbid) must stay byte-for-byte intact.

---

## Scope

- Add `FormValidator._is_evidence_envelope_value(field, value) -> bool` (staticmethod): True when
  `is_voice_envelope(value)` and the field is NOT a FEAT-488 declared TEXT envelope field (those keep
  today's path).
- In `validate_field()`: right after the REMOTE_RESPONSE/REST early returns, when the value is an
  evidence envelope, validate `value["answer"]` recursively with the same `required` flag and return
  those errors (the transcript-less but audio-backed envelope rules for TEXT stay in the FEAT-488 path).
- In the `validate()` sanitize loop (`coerced = self._coerce_value(...)`, :319): when the value is an
  evidence envelope, coerce the `answer` and re-fold into `VoiceEvidenceEnvelope(**value, answer=coerced).model_dump(mode="json")`.
- In `_coerce_value`'s FEAT-488 branch (:629): when `field.answer_envelope == "voice"` and the dict
  carries evidence keys (`source`, `confidence`, `audio_mime`, `duration_ms`, `language`,
  `plausibility`), validate with `VoiceEvidenceEnvelope` instead of `VoiceAnswerEnvelope` (the base
  is `extra="forbid"` and would reject the evidence fields).
- Keep `_is_voice_envelope_field(field)` unchanged (field-only predicate; its callers at :565/:587
  rely on it). The spec's "widened" predicate is realised by the new value-aware helper.
- Tests: `test_validator_envelope_any_type.py` (spec §4 `test_validator_envelope_any_type`,
  `test_envelope_coercion_number_boolean_select`).

**NOT in scope**: plausibility (never in the validator — spec §2), `SubmissionPipeline` (TASK-4222),
sink/mapper serialisation (TASK-4229), changing `VoiceAnswerEnvelope` (TASK-4210 adds only the subclass).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Envelope acceptance on any field type |
| `packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in services/validators.py:
from pydantic import ValidationError as PydanticValidationError     # services/validators.py:17
from ..core.schema import FormField, FormSchema, FormSection         # services/validators.py:22
from ..core.types import FieldType, LocalizedString                  # services/validators.py:23
from ..core.voice_answer import VoiceAnswerEnvelope                  # services/validators.py:24  ← extend this line
```

#### Provided by dependency tasks (do not exist yet — created by TASK-4210)
```python
from ..core.voice_answer import VoiceEvidenceEnvelope, is_voice_envelope   # TASK-4210 (core/voice_answer.py)
```

### Existing Signatures to Use
```python
# services/validators.py
class FormValidator:                                                         # :200
    async def validate(self, form, data, *, locale="en", auth_context=None, location_vars=None, visit_context=None) -> ValidationResult   # :221-229
    #   sanitize loop: `coerced = self._coerce_value(data.get(field.field_id), field)` (:319), stored when not None (:320-321)
    async def validate_field(self, field, value, *, all_data=None, locale="en", auth_context=None, required=None) -> list[str]   # :351-360
    #   REMOTE_RESPONSE early return (:384-385); REST early return (:387-388); required/empty check (:395-405); coercion (:422)
    @staticmethod
    def _is_voice_envelope_field(field: FormField) -> bool                  # :543-548 (answer_envelope == "voice" and TEXT/TEXT_AREA)
    def _is_empty_dict_answer(self, value, field) -> bool                   # :550
    def _constrainable_text(self, coerced, field) -> str | None             # :572
    def _coerce_value(self, value: Any, field: FormField) -> Any            # :593
    #   FEAT-488 branch :624-640 — `if field.answer_envelope == "voice":` (:629) → VoiceAnswerEnvelope.model_validate(value).model_dump()
# core/voice_answer.py:13  VoiceAnswerEnvelope(BaseModel): answer: str; blob_ref: str | None = None; data_url: str | None = None; extra="forbid"
```

### Does NOT Exist
- ~~`FormValidator(client=...)`~~ / any LLM in `services/validators.py` — keep it deterministic.
- ~~`FormValidator._is_evidence_envelope_value`~~ — created here.
- ~~`ValidationResult.envelopes`~~ — envelopes live in `sanitized_data` only.
- ~~`VoiceEvidenceEnvelope`~~ before TASK-4210 lands.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator.validate_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._is_voice_envelope_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py#FormValidator._coerce_value",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py#VoiceAnswerEnvelope"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- FEAT-488 tests must pass unchanged (AC8): a TEXT field with `answer_envelope="voice"` and a plain
  `{answer, blob_ref, data_url}` dict still returns `VoiceAnswerEnvelope(...).model_dump()`.
- MULTI_SELECT by voice: the envelope's `answer` is a list; validate/coerce it as the list it is
  (G5 — never comma-joined).
- An envelope whose scalar fails validation reports the field's normal error message (no
  envelope-specific wording), so HTTP and audio show the same errors.
- Minimal diff: no refactor of unrelated branches.

### References in Codebase
- `services/validators.py:543-640` — FEAT-488 envelope handling to extend.
- `packages/parrot-formdesigner/tests/unit/` FEAT-488 envelope tests (grep `answer_envelope`) — must stay green.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the import line — *why*: the new helpers come from TASK-4210.
2. Add the value-aware predicate below `_is_voice_envelope_field` — *why*: keep the field-only predicate's callers untouched.
3. Add the unwrap path in `validate_field` and the re-fold in the sanitize loop — *why*: validate the scalar, store the envelope.
4. Branch the FEAT-488 coercion to accept evidence keys — *why*: `VoiceAnswerEnvelope` forbids extras.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -cxF 'from ..core.voice_answer import VoiceAnswerEnvelope' services/validators.py)
# REPLACE line 24 `from ..core.voice_answer import VoiceAnswerEnvelope` (verified: services/validators.py:24) with:
from ..core.voice_answer import VoiceAnswerEnvelope, VoiceEvidenceEnvelope, is_voice_envelope
```
**Why**: the only new symbols this task needs.

### `services/validators.py` (MODIFY — predicate)
```python
# occurrences: 1 (verified: grep -c '    def _is_voice_envelope_field(field: FormField) -> bool:' services/validators.py)
# AFTER — insert below the body of `    def _is_voice_envelope_field(field: FormField) -> bool:` (verified: services/validators.py:543-548)
    _EVIDENCE_KEYS = frozenset({"source", "confidence", "audio_mime", "duration_ms", "language", "plausibility"})

    @classmethod
    def _is_evidence_envelope_value(cls, field: FormField, value: Any) -> bool:
        """Whether `value` is a FEAT-649 spoken-answer envelope on a field outside the FEAT-488 TEXT path.

        FEAT-488 declared TEXT/TEXT_AREA envelope fields keep their own handling; every other field
        type answered by voice carries a VoiceEvidenceEnvelope whose ``answer`` is validated as the scalar.
        """
        return is_voice_envelope(value) and not cls._is_voice_envelope_field(field)
```
**Why**: a value-aware predicate is the "widened" rule of spec M9 without altering the field-only
predicate used by `_is_empty_dict_answer` (:565) and `_constrainable_text` (:587).

### `services/validators.py` (MODIFY — validate_field unwrap)
```python
# occurrences: 1 (verified: grep -c '            return self._validate_rest_field(field, value, label, is_required)' services/validators.py)
# AFTER — insert below `            return self._validate_rest_field(field, value, label, is_required)` (verified: services/validators.py:388)
        # FEAT-649: a spoken answer on any field type arrives as a VoiceEvidenceEnvelope —
        # validate its scalar with this field's normal rules (unwrap → validate → re-fold at sanitize time).
        if self._is_evidence_envelope_value(field, value):
            return await self.validate_field(
                field,
                value.get("answer") if isinstance(value, dict) else value.answer,
                all_data=all_data,
                locale=locale,
                auth_context=auth_context,
                required=required,
            )
```
**Why**: recursion reuses every rule (required, options, bounds, patterns) instead of duplicating them.

### `services/validators.py` (MODIFY — sanitize re-fold)
```python
# occurrences: 1 (verified: grep -c '                    coerced = self._coerce_value(data.get(field.field_id), field)' services/validators.py)
# REPLACE the two lines at services/validators.py:319-321
#   `                    coerced = self._coerce_value(data.get(field.field_id), field)` … `sanitized[field.field_id] = coerced`
# with:
                    raw = data.get(field.field_id)
                    if self._is_evidence_envelope_value(field, raw):
                        envelope = VoiceEvidenceEnvelope.model_validate(raw)
                        scalar = self._coerce_value(envelope.answer, field)
                        # FILL IN: when scalar is None (optional, empty answer) keep the envelope only if it
                        #          references audio (blob_ref) — bounded by AC8 "every spoken answer stored as envelope"
                        sanitized[field.field_id] = envelope.model_copy(update={"answer": scalar}).model_dump(mode="json")
                    else:
                        coerced = self._coerce_value(raw, field)
                        if coerced is not None:
                            sanitized[field.field_id] = coerced
```
**Why**: stored data keeps the evidence while the answer is the coerced scalar (list for
MULTI_SELECT, bool for BOOLEAN, number for NUMBER).

### `services/validators.py` (MODIFY — FEAT-488 coercion accepts evidence keys)
```python
# occurrences: 1 (verified: grep -c '            if field.answer_envelope == "voice":' services/validators.py)
# INSIDE — first statement of the block under `            if field.answer_envelope == "voice":` (verified: services/validators.py:629)
                model = VoiceEvidenceEnvelope if self._EVIDENCE_KEYS & value.keys() else VoiceAnswerEnvelope
# and change `return VoiceAnswerEnvelope.model_validate(value).model_dump()` (:634) to
#            `return model.model_validate(value).model_dump()`
```
**Why**: the base envelope is `extra="forbid"`; a spoken TEXT answer now carries evidence fields.
Plain FEAT-488 dicts still go through `VoiceAnswerEnvelope` (same dump shape as before).

### FILL IN checklist
- [ ] sanitize re-fold — empty optional spoken answer policy; bounded by AC8

---

## Acceptance Criteria

- [ ] Envelope on SELECT/BOOLEAN/NUMBER/MULTI_SELECT validates through the scalar: invalid option / non-number yields the field's normal error; valid answer is re-folded with the coerced scalar (`answer` is a list for MULTI_SELECT) (AC6, AC8).
- [ ] TEXT with `answer_envelope="voice"` and a plain FEAT-488 dict behaves exactly as before; existing FEAT-488 tests pass unchanged (AC8).
- [ ] TEXT voice field with evidence keys validates via `VoiceEvidenceEnvelope` (no "extra inputs" error).
- [ ] No LLM / `parrot.clients` import in `services/validators.py`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` passes.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_feat448_validator_branches.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py
import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


def _env(answer, **kw):
    return {"answer": answer, "blob_ref": "voice-s1-x", "source": "speech", "confidence": 0.9, **kw}


@pytest.fixture
def form() -> FormSchema:
    # FILL IN: SELECT "color" (red/green), MULTI_SELECT "tags", BOOLEAN "ok", NUMBER "age" (min 0),
    #          TEXT "note" with answer_envelope="voice", accept_content_types=["application/json"]
    ...


class TestEnvelopeAnyType:
    async def test_select_envelope_valid_refolds(self, form): ...       # sanitized["color"]["answer"] == "red"
    async def test_select_envelope_invalid_option_errors(self, form): ...
    async def test_multi_select_envelope_list(self, form): ...          # answer stays a list
    async def test_boolean_and_number_coerced(self, form): ...
    async def test_required_envelope_with_empty_answer(self, form): ...

class TestFeat488Unchanged:
    async def test_plain_text_envelope_dump_identical(self, form): ...
    async def test_text_envelope_with_evidence_keys_accepted(self, form): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above (§3 Module 9 validators part, §9 S3, AC8)
3. **Check dependencies** — TASK-4210 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor above; confirm TASK-4210's `is_voice_envelope` semantics
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`, which include the FEAT-488 envelope suite `tests/unit/services/test_validators_rest.py`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4223 audio-form-interaction-workflow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
