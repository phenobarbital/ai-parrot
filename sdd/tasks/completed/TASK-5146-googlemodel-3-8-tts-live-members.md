# TASK-5146: GoogleModel additions — GEMINI_3_8_FLASH_TTS and GEMINI_3_8_LIVE

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1**. The sweep points the speech default at `gemini-3.8-flash-tts` and the Live
default at `gemini-3.8-live`; neither id exists in `GoogleModel` today. Add-before-delete (spec §2
rule 1): this task only **adds** members, so TASK-5149 can reference `GEMINI_3_8_FLASH_TTS` by name
before TASK-5155 deletes the 2.5 members. Both ids resolved on the live API on 2026-11-04 (proposal F029).

## Scope

- Add `GEMINI_3_8_FLASH_TTS = "gemini-3.8-flash-tts"` and `GEMINI_3_8_LIVE = "gemini-3.8-live"` to `GoogleModel`.
- Add `test_google_model_enum_has_3_8_tts_and_live` to `packages/ai-parrot/tests/test_google_models.py`.
- Re-pin `test_google_model_alias_count` to the intermediate count **51 names / 33 values**
  (49/31 + 2 new distinct values) — because the alias-count test is in the Validation Contract and
  must stay green between this task and TASK-5155, which re-pins it to 45/28.

**NOT in scope**: deleting any 2.5 member (TASK-5155); `VertexAIModel` (TASK-5155);
`GoogleVoiceModel` in `parrot/models/google.py` (TASK-5147); any default that uses the new members (TASK-5149).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | MODIFY | +2 members in `GoogleModel` |
| `packages/ai-parrot/tests/test_google_models.py` | MODIFY | new-member test; alias count 51/33 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google.models import GoogleModel  # verified: tests/test_google_models.py:5; models.py:99 __all__
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/models.py
class GoogleModel(Enum):                                              # line 11 — plain Enum: duplicate values become silent aliases
    GEMINI_3_1_FLASH_TTS_PREVIEW = "gemini-3.1-flash-tts-preview"     # line 37
    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"               # line 38 (alias of :37)
    GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"   # line 39
    # Gemini 2.5 series                                               # line 40

# packages/ai-parrot/tests/test_google_models.py
def test_google_model_enum_has_gemini_4_argon():                      # line 56
def test_google_model_alias_count():                                  # line 74
    assert len(GoogleModel.__members__) == 49                         # line 76
    assert len({model.value for model in GoogleModel}) == 31          # line 77
```

### Does NOT Exist
- ~~`GoogleModel.GEMINI_3_8_FLASH_TTS`~~, ~~`GoogleModel.GEMINI_3_8_LIVE`~~ — created by THIS task.
- ~~`GoogleModel.GEMINI_4_FLASH`~~ / any 4.x flash or lite member — Google serves none.
- ~~`GoogleModel.GEMINI_3_8_FLASH_LITE_TTS`~~ — live upstream but not requested; do not add.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_google_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/models.py#GoogleModel"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Both values are new (no existing member carries them), so the names add 2 and the distinct values add 2.
- Keep the file's newest-first grouping: TTS next to the 3.1 TTS lines, Live next to the 3.1 Live line.

---

## Implementation Blueprint

### Steps (in order)
1. Insert `GEMINI_3_8_FLASH_TTS` below line 38 — *why*: keeps TTS members together.
2. Insert `GEMINI_3_8_LIVE` below line 39 — *why*: keeps Live members together.
3. Update `test_google_models.py` — *why*: the alias-count guard would fail otherwise.

### `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"' models.py)
# AFTER — insert below `    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"` (verified: models.py:38)
    GEMINI_3_8_FLASH_TTS = "gemini-3.8-flash-tts"
```
```python
# occurrences: 1 (verified: grep -c 'GEMINI_3_1_FLASH_LIVE_PREVIEW = ' models.py)
# AFTER — insert below `    GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"` (verified: models.py:39)
    GEMINI_3_8_LIVE = "gemini-3.8-live"
```
**Why**: spec M1 interface skeleton. Values are the exact live ids (F029).

### `packages/ai-parrot/tests/test_google_models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_google_model_enum_has_gemini_4_argon' test_google_models.py)
# AFTER — insert below the body of `test_google_model_enum_has_gemini_4_argon` (verified: :56-59)


def test_google_model_enum_has_3_8_tts_and_live():
    """FEAT-798: the 3.8 TTS and Live successors are reachable by name and by value."""
    assert GoogleModel.GEMINI_3_8_FLASH_TTS.value == "gemini-3.8-flash-tts"
    assert GoogleModel.GEMINI_3_8_LIVE.value == "gemini-3.8-live"
    # FILL IN: assert GoogleModel("gemini-3.8-flash-tts") is GoogleModel.GEMINI_3_8_FLASH_TTS and the same for live
```
```python
# occurrences: 1 each (verified: test_google_models.py:76, :77) — REPLACE
    assert len(GoogleModel.__members__) == 51
    assert len({model.value for model in GoogleModel}) == 33
```
**Why**: intermediate count; TASK-5155 re-pins to 45/28 after the deletions.

### FILL IN checklist
- [ ] Value-lookup assertions in `test_google_model_enum_has_3_8_tts_and_live`.

---

## Acceptance Criteria

- [ ] `GoogleModel.GEMINI_3_8_FLASH_TTS.value == "gemini-3.8-flash-tts"`; `GoogleModel.GEMINI_3_8_LIVE.value == "gemini-3.8-live"`.
- [ ] `len(GoogleModel.__members__) == 51`, 33 distinct values.
- [ ] No other line of `models.py` changes (`git diff` shows exactly 2 added lines).
- [ ] `ruff check` clean on both files.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_google_models.py -q`
- `pytest packages/ai-parrot/tests/clients/test_google_models.py -q`

Run inside the worktree with an absolute `PYTHONPATH=<wt>/packages/ai-parrot/src:<wt>/packages/ai-parrot-client-google/src`.

## Test Specification
See the blueprint block for `test_google_models.py`.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§2 Overview, §3 M1, §6).
3. Check dependencies: none.
4. Verify the Codebase Contract: re-run every `grep -c` before editing.
5. Mark the task `in-progress` in `sdd/tasks/index/google-migration.json` and commit only that file.
6. Implement from the blueprint and complete every `# FILL IN:`.
7. Run the Validation Commands.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5146 google-migration verified`, then fill the Completion Note and commit.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator)
**Date**: 2026-11-04
**Verification**: verified
**Notes**: Merged via engine (gpt-5.6-terra). Merge-tier validation green for this task's targets.

**Deviations from spec**: none
