# TASK-5149: GoogleAnalysis / GoogleGeneration method defaults off 2.5

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5146
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2** (mixin half). Ten references in the two mixins keep the client satellite tied to
2.5 members: six `GEMINI_2_5_FLASH` method defaults and one `GEMINI_2_5_PRO` in `analysis.py`, a literal
`"gemini-2.5-flash"` in its 503 retry path, and in `generation.py` one `GEMINI_2_5_FLASH` default, the
speech default `GEMINI_2_5_FLASH_TTS` (dies 2026-11-17) and a docstring mention. TASK-5155 deletes those
members, so this task must land first. Replacement: flash → `GEMINI_3_8_FLASH`, pro (image
identification, `:815`) → `GEMINI_4_ARGON`, TTS → `GEMINI_3_8_FLASH_TTS` (created by TASK-5146).

## Scope

- `analysis.py`: defaults at `:64, :139, :631, :1075, :1130, :1185` → `GEMINI_3_8_FLASH`; `:815` → `GEMINI_4_ARGON`;
  503 retry `:911-914` → `GoogleModel.GEMINI_3_8_FLASH.value` with an updated comment.
- `generation.py`: `:405` → `GEMINI_3_8_FLASH`; `:572` → `GEMINI_3_8_FLASH_TTS`; docstring `:2321`.
- Create `packages/ai-parrot-client-google/tests/unit/test_google_default_models.py`.

**NOT in scope**: `client.py` (TASK-5148); `models.py` (TASK-5146/5155); the reel director default in
core `parrot/models/google.py` (TASK-5147).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py` | MODIFY | 7 defaults + retry literal |
| `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` | MODIFY | 2 defaults + docstring |
| `packages/ai-parrot-client-google/tests/unit/test_google_default_models.py` | CREATE | signature-default tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google import GoogleGenAIClient   # verified: test_computer_use_vocabulary.py top import
from parrot.clients.google.models import GoogleModel  # verified: models.py:99
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py  (class GoogleAnalysis, mixed into GoogleGenAIClient:106)
    def analyze_sentiment(self, text: str, model: Union[GoogleModel, str] = GoogleModel.GEMINI_2_5_FLASH, ...)   # def :61, default :64
    def analyze_product_review(..., model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, ...)           # def :135, default :139
    async def document_understanding(..., model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, ...)    # def :627, default :631
    async def image_identification(..., model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_PRO, ...)        # def :808, default :815
        # 503 retry: `model="gemini-2.5-flash",`                                                                 # :914 (comment :911)
    def summarize_text(..., model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, ...)                  # def :1070, default :1075
    def translate_text(..., model: ... = GoogleModel.GEMINI_2_5_FLASH, ...)                                       # def :1125, default :1130
    def extract_key_points(..., model: ... = GoogleModel.GEMINI_2_5_FLASH, ...)                                   # def :1181, default :1185

# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py  (class GoogleGeneration)
    async def create_conversation_script(self, report_data, model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, ...)  # def :402, default :405
    async def generate_speech(self, prompt_data, model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS, ...)         # def :569, default :572
    # docstring :2321  "hardcoded to ``GoogleModel.GEMINI_2_5_FLASH``; now forwarded"
```

### Does NOT Exist
- ~~`GoogleModel.GEMINI_3_8_FLASH_TTS`~~ before TASK-5146 lands — that is why this task depends on it.
- ~~`GoogleModel.GEMINI_4_PRO`~~ — the pro-class successor is `GEMINI_4_ARGON` (models.py:19).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/generation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-google/tests/unit/test_google_default_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py#GoogleAnalysis.analyze_sentiment",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py#GoogleAnalysis.image_identification",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.generate_speech",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/generation.py#GoogleGeneration.create_conversation_script"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the six flash defaults in `analysis.py` — *why*: flash-class per spec §2.
2. Replace `:815` with Argon and the retry literal with 3.8-flash — *why*: pro-class default; the retry stays a cheaper fallback.
3. Edit `generation.py` — *why*: the TTS id dies 2026-11-17.
4. Create the test module.

### `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py` (MODIFY)
```python
# occurrences: 1 (`model: Union[GoogleModel, str] = GoogleModel.GEMINI_2_5_FLASH,` at :64)
#              5 (`model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,` at :139, :631, :1075, :1130, :1185)
# Each of the 6 lines is the only GEMINI_2_5_FLASH default in its method, so a file-wide replace of
# `GoogleModel.GEMINI_2_5_FLASH,` → `GoogleModel.GEMINI_3_8_FLASH,` is safe; post-check count == 0.
```
```python
# occurrences: 1 (:815)
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_4_ARGON,
```
```python
# occurrences: 1 (:914) and its comment at :911
            # then, retry with a short delay on the cheaper flash tier instead of the pro-class model.
            ...
                model=GoogleModel.GEMINI_3_8_FLASH.value,
```

### `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py` (MODIFY)
```python
# occurrences: 1 (:405)
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_8_FLASH,
# occurrences: 1 (:572)
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_8_FLASH_TTS,
# occurrences: 1 (:2321) — docstring
                hardcoded to ``GoogleModel.GEMINI_3_8_FLASH``; now forwarded
```
**Why**: the `:2321` docstring describes the director's old hardcoded default; FEAT-798's guard scans comments too.

### `packages/ai-parrot-client-google/tests/unit/test_google_default_models.py` (CREATE)
```python
"""FEAT-798: Google mixin method defaults no longer name retired 2.5 members."""

import inspect

import pytest

from parrot.clients.google import GoogleGenAIClient
from parrot.clients.google.models import GoogleModel

FLASH_DEFAULTS = (
    "analyze_sentiment",
    "analyze_product_review",
    "document_understanding",
    "summarize_text",
    "translate_text",
    "extract_key_points",
    "create_conversation_script",
)


def _default(method_name: str):
    return inspect.signature(getattr(GoogleGenAIClient, method_name)).parameters["model"].default


@pytest.mark.parametrize("method_name", FLASH_DEFAULTS)
def test_flash_class_defaults_are_3_8_flash(method_name: str) -> None:
    assert _default(method_name) is GoogleModel.GEMINI_3_8_FLASH


def test_image_identification_default_is_argon() -> None:
    assert _default("image_identification") is GoogleModel.GEMINI_4_ARGON


def test_generate_speech_default_is_3_8_tts() -> None:
    assert _default("generate_speech") is GoogleModel.GEMINI_3_8_FLASH_TTS
```

### FILL IN checklist
- [ ] Confirm each method in `FLASH_DEFAULTS` has a parameter literally named `model` (they do per the contract; re-check after edits).

---

## Acceptance Criteria

- [ ] `grep -c 'GEMINI_2_5\|gemini-2\.5' analysis.py generation.py` == 0 (spec AC-4).
- [ ] `generate_speech` default is `GEMINI_3_8_FLASH_TTS`; `image_identification` default is `GEMINI_4_ARGON` (spec AC-6).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-client-google/tests/unit/test_google_default_models.py -q`
- `pytest packages/ai-parrot/tests/test_google_client.py -q`

## Test Specification
See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§2 table, §3 M2).
3. Check dependencies: TASK-5146 must be `done`.
4. Verify the Codebase Contract with `grep -c`.
5. Mark the task `in-progress` in the index and commit only that file.
6. Implement from the blueprint.
7. Run the Validation Commands with an absolute worktree `PYTHONPATH`.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5149 google-migration verified`, then fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
