# TASK-4256: Run the calibration on the real corpus and set the shipped defaults

**Feature**: FEAT-653 — Audio form voice post-processors
**Spec**: `sdd/specs/audio-form-voice-postprocessors.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h, excluding corpus export)
**Depends-on**: TASK-4255, TASK-4253
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (second half), AC16, owner decision §8 Q4. Run the TASK-4255 harness on the
real FieldSync corpus, commit the aggregate report, and set the shipped defaults from its
recommendation.

**Blocked on spec §8 Q8 (owners: Emmanuel / Juan)**: the corpus is the FieldSync recordings plus
the value each rep finally confirmed or typed, exported as the TASK-4255 JSONL. Until it exists,
this task cannot run. A coding agent must not fabricate a corpus or invent defaults. If the
corpus is absent, stop and set the task `done-with-issues` explaining that.

This task is **exclusive** (`parallel: false`). It makes real LLM calls under a request budget,
loads the local faster-whisper model, reads the private corpus, and edits the defaults that other
tasks' tests import.

---

## Scope

- Run `calibrate_voice_postprocessors.py` with `PARROT_TEST_REAL_LLM=1`, the agreed LLM, and a
  `--max-requests` budget.
- Commit `sdd/state/FEAT-653/calibration/report.md` and `report.json` (aggregates only; review
  them for personal data before committing).
- Apply the recommendation:
  - `VoiceFormConfig.llm_refine_threshold` and `llm_refine_timeout_s` in `core/voice.py`;
  - `VoiceFormConfig.stt_confirm_threshold` in `core/voice.py`, **and**
    `AudioSessionConfig.stt_confirm_threshold` in `audio/models.py`.

  The second change is required because `resolve_voice_config` takes the **max** of the form and
  session thresholds (`core/voice.py:115`). The session default (0.6) would otherwise floor any
  lower calibrated value.
- Update the tests that pin the old 0.6 default (`test_audio_models.py:36`) to the new value, and
  justify any deviation from the recommendation in `report.md`.

**NOT in scope**: changing the decision rule (TASK-4255); the STT confidence formula (separate
spec). When that spec lands, this run is repeated.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-653/calibration/report.md` | CREATE | Human report (aggregates) |
| `sdd/state/FEAT-653/calibration/report.json` | CREATE | Machine report (aggregates) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` | MODIFY | Calibrated defaults |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | `AudioSessionConfig.stt_confirm_threshold` default |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py` | MODIFY | Pinned default |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none new; the harness is run as a script
```

### Existing Signatures to Use
```python
# core/voice.py
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)    # :58 (VoiceFormConfig)
    llm_refine_threshold: float = Field(default=0.8, ge=0.0, le=1.0)     # added by TASK-4248
    llm_refine_timeout_s: float = Field(default=4.0, gt=0.0)             # added by TASK-4248
def resolve_voice_config(form, session) -> VoiceFormConfig              # :~100; "stt_confirm_threshold": max(base..., session...) :115
# audio/models.py
class AudioSessionConfig(BaseModel): ... stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)   # :119
# tests/formdesigner/test_audio_models.py:36   assert cfg.stt_confirm_threshold == 0.6
# scripts/calibrate_voice_postprocessors.py (TASK-4255): main(["--corpus", ..., "--out", ..., "--llm", ..., "--max-requests", N])
```

### Does NOT Exist
- ~~A corpus in the repository~~ — never commit it; it is user data.
- ~~Defaults chosen without the report~~ — not allowed (AC16).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-653/calibration/report.md", "action": "CREATE"},
    {"path": "sdd/state/FEAT-653/calibration/report.json", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#VoiceFormConfig",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py#resolve_voice_config",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionConfig"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the corpus exists and was exported per TASK-4255's format; if not, stop (`done-with-issues`).
2. Run the harness — *why*: the defaults must be measured (G9).
3. Review `report.md` / `report.json` for personal data — *why*: they are committed.
4. Update the defaults to the recommendation — *why*: AC16.
5. Update pinned tests; run the validation commands.

### Run
```bash
source .venv/bin/activate
PARROT_TEST_REAL_LLM=1 PYTHONPATH=packages/parrot-formdesigner/src \
  python packages/parrot-formdesigner/scripts/calibrate_voice_postprocessors.py \
  --corpus <secure path>/corpus.jsonl --out sdd/state/FEAT-653/calibration \
  --llm <agreed provider:model> --max-requests <budget>
```

### `core/voice.py` (MODIFY)
```python
# occurrences: 1 each (verified at task start with grep -c on each line)
# FILL IN: set the three defaults to report.json's recommendation values (VoiceFormConfig.stt_confirm_threshold :58,
# llm_refine_threshold, llm_refine_timeout_s) — bounded by AC16; keep ge/le/gt bounds unchanged
```

### `audio/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)' audio/models.py) — :119
# FILL IN: same calibrated stt_confirm_threshold default as core/voice.py (resolve_voice_config takes the max)
```

### `tests/formdesigner/test_audio_models.py` (MODIFY)
```python
# :36 `        assert cfg.stt_confirm_threshold == 0.6`
# FILL IN: update to the calibrated value (only if it changed)
```

### FILL IN checklist
- [ ] corpus present (else `done-with-issues`)
- [ ] report reviewed for personal data
- [ ] defaults updated in both files; pinned test updated

---

## Acceptance Criteria

- [ ] AC16: report committed; shipped defaults equal the recommendation or the deviation is justified in `report.md`.
- [ ] No transcript, value, audio path or user id in the committed report.
- [ ] All audio/voice tests pass with the new defaults.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`

---

## Test Specification

No new tests. The harness tests (TASK-4255) and the default-pinning tests cover this task.

---

## Agent Instructions

1. Work in the feature worktree: `python -m scripts.sdd.ensure_worktree --slug audio-form-voice-postprocessors --feature-id FEAT-653`.
2. Check `Depends-on` tasks are `done`; confirm spec §8 Q8 is resolved and the corpus path is available. **If not, stop.**
3. Set this task `in-progress` in the index and commit only the index.
4. Run, review, update defaults per the blueprint.
5. Run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4256 audio-form-voice-postprocessors verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
