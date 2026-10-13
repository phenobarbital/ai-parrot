# TASK-4258: `option_pause_ms` voice config (form default + per-field override)

**Feature**: FEAT-654 — Voice Form hands-free barge-in and per-option narration segments
**Spec**: `sdd/specs/voice-form-barge-in.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4257
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, config part (G3; AC4). The per-option narration (TASK-4259) inserts a
`pause:<option_pause_ms>` gap between enumerated options. The gap is configured at form level
(`VoiceFormConfig.option_pause_ms`, default **500 ms — provisional**, spec §8 Q-A, calibrated
in the end-to-end run) and per field (`meta.voice.option_pause_ms`). This task only adds the
two config fields and their validation tests; the narrator consumes them in TASK-4259.

Depends on TASK-4257 only because both modify `core/voice.py` (serialized, lower id first).

---

## Scope

- Add `option_pause_ms: int | None = None` to `FieldVoiceMeta` (per-field override).
- Add `option_pause_ms: int = Field(default=500, ge=0)` to `VoiceFormConfig`.
- Tests: default 500, `ge=0` rejects negatives, `FieldVoiceMeta(option_pause_ms=250)` parses,
  and `field_voice_meta` accepts `meta.voice.option_pause_ms` **without** the unknown-key warning.

**NOT in scope**: using the value in `Narrator` (TASK-4259), docs (TASK-4261),
`resolve_voice_config` tightening rules (unchanged — the pause is not a threshold/cap).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` | MODIFY | two new fields |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` | MODIFY | config tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig, field_voice_meta  # core/voice.py:35,50,82
from parrot_formdesigner.core.schema import FormField   # used by test_audio_engine_turns.py:48
from parrot_formdesigner.core.types import FieldType    # core/types.py
from pydantic import ValidationError
```

### Existing Signatures to Use
```python
# core/voice.py:35-48
class FieldVoiceMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt: str | None = None
    enumerate: Literal["auto", "always", "never", "count_only"] = "auto"
    confirm: Literal["auto", "always", "never"] = "auto"
    pause_ms: int | None = None
    ui_cue: UiCue | None = None
    match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    skip_in_review: bool = False
    commands: Literal["on", "off"] = "on"
    sensitive: bool = False

# core/voice.py:50-68 (excerpt)
class VoiceFormConfig(BaseModel):
    enabled: bool = True
    max_questions: int | None = Field(default=10, ge=1)
    hint_pause_ms: int = Field(default=600, ge=0)
    enumerate_options: bool = True
    ...
    max_recording_seconds: int = Field(default=60, ge=1)

# core/voice.py:82 — warns once per call for keys not in FieldVoiceMeta.model_fields
def field_voice_meta(field: FormField, *, logger: logging.Logger | None = None) -> FieldVoiceMeta
```

### Does NOT Exist
- ~~`VoiceFormConfig.option_pause_ms`~~ / ~~`FieldVoiceMeta.option_pause_ms`~~ — created by this task.
- ~~`HandsFreeConfig.option_pause_ms`~~ — the pause is NOT a hands-free setting.
- ~~`StartSession.option_pause_ms`~~ — no per-session override.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#FieldVoiceMeta",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#VoiceFormConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#field_voice_meta"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `FieldVoiceMeta.option_pause_ms` has NO `Field(ge=0)` in the skeleton; add `Field(default=None, ge=0)` so a negative per-field value is invalid — `field_voice_meta` then falls back to defaults with a warning (existing behaviour, never raises).
- `0` is valid at both levels (TASK-4259: no `pause:` keys, still one segment per item).

---

## Implementation Blueprint

### Steps (in order)
1. Add the per-field override to `FieldVoiceMeta` — *why*: `field_voice_meta` builds its unknown-key set from `model_fields`, so adding the field is what silences the warning.
2. Add the form default to `VoiceFormConfig` next to `hint_pause_ms` — *why*: keeps the pause settings together.
3. Write the tests — *why*: AC4 precedence is exercised in TASK-4259; here we pin parsing/validation.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    sensitive: bool = False' core/voice.py)
# AFTER — insert below `    sensitive: bool = False` (verified: core/voice.py:48)
    option_pause_ms: int | None = Field(default=None, ge=0)  # per-field gap between enumerated options (ms)

# occurrences: 1 (verified: grep -cF '    hint_pause_ms: int = Field(default=600, ge=0)' core/voice.py)
# AFTER — insert below `    hint_pause_ms: int = Field(default=600, ge=0)` (verified: core/voice.py:56)
    option_pause_ms: int = Field(default=500, ge=0)  # gap between enumerated options (ms); provisional, spec §8 Q-A
```
**Why**: spec §2 Data Models. Line numbers shift by TASK-4257's +7 docstring lines — trust the `grep -c`, not the number.

### `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` (MODIFY — append)
```python
def test_voice_form_config_option_pause_default():
    import pytest
    from pydantic import ValidationError

    from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig

    assert VoiceFormConfig().option_pause_ms == 500
    with pytest.raises(ValidationError):
        VoiceFormConfig(option_pause_ms=-1)
    assert FieldVoiceMeta(option_pause_ms=250).option_pause_ms == 250
    # FILL IN: FieldVoiceMeta().option_pause_ms is None; VoiceFormConfig(option_pause_ms=0) is valid — AC4


def test_field_voice_meta_accepts_option_pause_without_warning(caplog):
    from parrot_formdesigner.core.schema import FormField
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.core.voice import field_voice_meta

    field = FormField(field_id="c", field_type=FieldType.SELECT, label="C", meta={"voice": {"option_pause_ms": 250}})
    # FILL IN: with caplog at WARNING, field_voice_meta(field).option_pause_ms == 250 and no "unknown meta.voice keys" record — AC4
```
**Why**: spec §4 `test_voice_form_config_option_pause_default`. A SELECT `FormField` may require `options` — if construction fails, add `options=[FieldOption(value="a", label="A")]` (`from parrot_formdesigner.core.options import FieldOption`, verified test_audio_engine_turns.py:47).

### FILL IN checklist
- [ ] `None` default / `0` valid assertions — AC4
- [ ] caplog assertion (no unknown-key warning) — AC4

---

## Acceptance Criteria

- [ ] `VoiceFormConfig().option_pause_ms == 500`; negatives rejected; `0` accepted (AC4)
- [ ] `FieldVoiceMeta.option_pause_ms` parses via `field_voice_meta` with no unknown-key warning
- [ ] TASK-4257 tests still pass
- [ ] `ruff check` clean on the touched files

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_narration_engine.py -q`

---

## Test Specification

See the blueprint test blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug voice-form-barge-in --feature-id FEAT-654 --spec sdd/specs/voice-form-barge-in.spec.md --index sdd/tasks/index/voice-form-barge-in.json`)
2. **Read the spec** (§2 Data Models, §3 Module 2, §5 AC4, §8 Q-A)
3. **Check dependencies** — TASK-4257 must be `"done"`
4. **Verify the Codebase Contract** — re-run every `grep -c`; 0 means STOP and report drift
5. **Update status** → `"in-progress"` and commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — Validation Commands one file at a time (`-p no:xdist`)
8. **Commit the code** — stage only the files listed above
9. **Close** with `scripts/sdd/close_task.sh TASK-4258 voice-form-barge-in verified`
10. **Fill in the Completion Note** and commit

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
