# TASK-5155: Delete the retired 2.5 members, re-pin the catalogue tests, add the src regression guard

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5146, TASK-5147, TASK-5148, TASK-5149, TASK-5150, TASK-5151, TASK-5153
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**, the last step of add-before-delete. Once every by-name reference is rewritten
(TASK-5148/5149) and every src literal is swept (TASK-5147/5150/5151/5153), delete the retired members and
make the retirement un-regressable. Deletion is the public contract FEAT-688 U2 chose: no
`deprecated_models`, no remap. **Blocking live gate (spec AC-12, codex S1)**: before deleting, record
`models.get` evidence for `gemini-4-argon`, `gemini-3.8-flash`, `gemini-3.8-flash-tts` and `gemini-3.8-live`.
A failing id blocks the deletion of its 2.5 predecessor.

## Scope

- Pre-check: `grep -rn 'GoogleModel.GEMINI_2_5_\(FLASH\b\|FLASH,\|FLASH\.\|FLASH_PREVIEW\|PRO\b\|FLASH_TTS\|PRO_TTS\)\|GEMINI_COMPUTER_USE' packages/*/src` → no output. If it prints anything, stop: a dependency task is incomplete.
- `GoogleModel`: delete `GEMINI_2_5_FLASH` (:41), `GEMINI_2_5_FLASH_PREVIEW` (:42), `GEMINI_2_5_PRO` (:45),
  `GEMINI_2_5_FLASH_TTS` (:46), `GEMINI_2_5_PRO_TTS` (:47), `GEMINI_COMPUTER_USE` (:49).
- `VertexAIModel`: delete `GEMINI_2_5_FLASH` (:91) and `GEMINI_2_5_PRO` (:93); keep `GEMINI_2_5_FLASH_LITE` (:92).
- Re-pin both catalogue test modules (45 names / 28 values), the doc-understanding test, and the factory test.
- Create the src regression guard.

**NOT in scope**: the kept flash-lite / flash-image members; `deprecated_models`; `clients/base.py` comments (reviewed exclusion).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | MODIFY | −6 GoogleModel, −2 VertexAIModel members |
| `packages/ai-parrot/tests/test_google_models.py` | MODIFY | retired lists + 45/28 |
| `packages/ai-parrot/tests/clients/test_google_models.py` | MODIFY | drop 2.5 assertions, add negative |
| `tests/unit/test_google_document_understanding.py` | MODIFY | :396 member → GEMINI_3_8_FLASH |
| `packages/ai-parrot/tests/test_llm_factory.py` | MODIFY | `test_list_models_google_excludes_2_5` |
| `packages/ai-parrot/tests/test_no_retired_gemini_defaults.py` | CREATE | src regression guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google.models import GoogleModel, VertexAIModel  # verified: models.py:99 (__all__)
from parrot.clients.factory import LLMFactory                        # verified: tests/test_llm_factory.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/models.py  (line numbers BEFORE TASK-5146 adds 2 lines above :40 — re-grep)
    # Gemini 2.5 series                                         # :40
    GEMINI_2_5_FLASH = "gemini-2.5-flash"                       # :41  (ALSO at :91 in VertexAIModel)
    GEMINI_2_5_FLASH_PREVIEW = "gemini-2.5-flash"               # :42
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"             # :43  KEEP
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite"     # :44  KEEP
    GEMINI_2_5_PRO = "gemini-2.5-pro"                           # :45  (ALSO at :93 in VertexAIModel)
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"       # :46
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"           # :47
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"           # :48  KEEP
    GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"  # :49
    GEMINI_2_5_FLASH_IMAGE_PREVIEW = "gemini-2.5-flash-image"   # :59  KEEP
class VertexAIModel(Enum):                                      # :73
    GEMINI_3_1_FLASH_LITE_IMAGE = "gemini-3.1-flash-lite-image" # :90
    GEMINI_2_5_FLASH = "gemini-2.5-flash"                       # :91  delete
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"             # :92  KEEP
    GEMINI_2_5_PRO = "gemini-2.5-pro"                           # :93  delete
    IMAGEN_3 = "imagen-3.0-generate-002"                        # :94

# tests: test_google_models.py RETIRED_VALUES :41, RETIRED_NAMES :47, alias count :76-77 (51/33 after TASK-5146)
#        tests/clients/test_google_models.py — whole file 26 lines; :10-14 computer-use tests, :25-26 2.5 asserts
#        tests/unit/test_google_document_understanding.py:396  model=GoogleModel.GEMINI_2_5_FLASH,
#        tests/test_llm_factory.py:118  def test_list_models_google_includes_argon():
```

### Does NOT Exist
- ~~`GoogleGenAIClient.deprecated_models`~~ — never add it.
- ~~`GoogleModel.GEMINI_COMPUTER_USE`~~ after this task — the 3.x computer-use aliases (:50-51) remain.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_google_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/clients/test_google_models.py", "action": "MODIFY"},
    {"path": "tests/unit/test_google_document_understanding.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_llm_factory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_no_retired_gemini_defaults.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/models.py#GoogleModel",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/models.py#VertexAIModel",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.list_models"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Run the live gate and save its output to `artifacts/logs/feat-798-live-models.log` — *why*: blocking AC-12.
   ```bash
   for m in gemini-4-argon gemini-3.8-flash gemini-3.8-flash-tts gemini-3.8-live; do
     curl -s -o /dev/null -w "$m %{http_code}\n" "https://generativelanguage.googleapis.com/v1beta/models/$m?key=$GOOGLE_API_KEY"; done
   ```
   (`env/.env` is INI-style: read the single key with grep, never `source` it.)
2. Run the pre-check grep — *why*: an `AttributeError` at import would break every Google user.
3. Delete the members — *why*: spec G2.
4. Re-pin the tests and create the guard.

### `models.py` (MODIFY)
```python
# GoogleModel — delete these 6 lines (the :41 and :45 lines also occur in VertexAIModel: occurrences 2 each).
# Disambiguate: inside GoogleModel they sit directly under `    # Gemini 2.5 series` as the contiguous run
#   GEMINI_2_5_FLASH, GEMINI_2_5_FLASH_PREVIEW, (keep LITE, LITE_PREVIEW), GEMINI_2_5_PRO, GEMINI_2_5_FLASH_TTS,
#   GEMINI_2_5_PRO_TTS, (keep FLASH_IMAGE), GEMINI_COMPUTER_USE
# VertexAIModel — delete the copies that sit between `GEMINI_3_1_FLASH_LITE_IMAGE = ...` and `IMAGEN_3 = ...`,
#   keeping `GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"` between them.
```

### `packages/ai-parrot/tests/test_google_models.py` (MODIFY)
```python
# RETIRED_VALUES — extend with:
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-computer-use-preview-10-2025",
# RETIRED_NAMES — extend with:
    "GEMINI_2_5_FLASH",
    "GEMINI_2_5_FLASH_PREVIEW",
    "GEMINI_2_5_PRO",
    "GEMINI_2_5_FLASH_TTS",
    "GEMINI_2_5_PRO_TTS",
    "GEMINI_COMPUTER_USE",
# alias count (:76-77)
    assert len(GoogleModel.__members__) == 45
    assert len({model.value for model in GoogleModel}) == 28
# FILL IN: update the test_google_model_retired_names_absent docstring ("five" → the new count)
```
**Why**: 51 − 6 names = 45; 33 − 5 values = 28 (`GEMINI_2_5_FLASH_PREVIEW` shares its value with `GEMINI_2_5_FLASH`).

### `packages/ai-parrot/tests/clients/test_google_models.py` (MODIFY)
```python
# DELETE test_gemini_computer_use_exists and test_gemini_computer_use_value (:10-14);
# REPLACE them with:
    def test_retired_computer_use_absent(self):
        """FEAT-798: the 2.5 computer-use preview (shut down 2026-07-28) is gone."""
        assert "GEMINI_COMPUTER_USE" not in GoogleModel.__members__
# DELETE the two 2.5 asserts in test_existing_entries_unchanged (:25-26); keep :24.
```

### `tests/unit/test_google_document_understanding.py` (MODIFY)
```python
# occurrences: 1 (:396)
            model=GoogleModel.GEMINI_3_8_FLASH,
```

### `packages/ai-parrot/tests/test_llm_factory.py` (MODIFY — append after the FEAT-688 block)
```python
def test_list_models_google_excludes_2_5():
    """FEAT-798: retired 2.5 ids are no longer published; flash-lite stays."""
    active = LLMFactory.list_models("google")["active"]
    assert "gemini-2.5-pro" not in active
    assert "gemini-2.5-flash" not in active
    assert "gemini-2.5-flash-lite" in active
```

### `packages/ai-parrot/tests/test_no_retired_gemini_defaults.py` (CREATE)
```python
"""FEAT-798 (spec AC-1, codex S7): no retired gemini-2.5 id in shipped source."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = tuple(sorted((REPO_ROOT / "packages").glob("*/src"))) + (
    REPO_ROOT / "packages" / "ai-parrot-server" / "ui" / "src",
)
SUFFIXES = {".py", ".ts", ".svelte", ".json"}
RETIRED_LITERALS = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-flash-native-audio",
    "gemini-2.5-computer-use",
)
# Whole ids only: gemini-2.5-flash must NOT match gemini-2.5-flash-lite / -image.
RETIRED = re.compile(
    r"gemini-2\.5-(?:pro|flash)(?![-\w])|gemini-2\.5-(?:flash|pro)-preview-tts|gemini-2\.5-flash-native-audio|gemini-2\.5-computer-use"
)
GUARD_EXCLUDED = {
    "packages/ai-parrot/src/parrot/clients/base.py",  # two historical comments (:373, :2143); file is a non-goal
}
# FILL IN: the pricing JSON keeps dated 2.5 *preview* keys on purpose (they price history) —
#          add "packages/ai-parrot/src/parrot/observability/cost/pricing/google.json" to GUARD_EXCLUDED
#          only if the guard trips on those keys; confirm the regex first (the keys end in -preview-05-20, so (?![-\w]) may already skip them)


def test_no_retired_gemini_literal_in_src() -> None:
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if "build" in path.parts or "node_modules" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in GUARD_EXCLUDED:
                continue
            # FILL IN: read utf-8 text and append f"{rel}:{lineno}: {line.strip()}" per RETIRED match
    assert not hits, "retired gemini-2.5 ids in src:\n" + "\n".join(hits)
```

### FILL IN checklist
- [ ] Live gate log saved; any failing id reported and its predecessor kept.
- [ ] `retired_names_absent` docstring count.
- [ ] Guard loop body; `REPO_ROOT` depth (`parents[3]`) verified; pricing-JSON exclusion decided.

---

## Acceptance Criteria

- [ ] `len(GoogleModel.__members__) == 45`, 28 values; the six names are gone; `GoogleModel("gemini-2.5-pro")` raises `ValueError` (spec AC-3).
- [ ] `VertexAIModel` keeps only `GEMINI_2_5_FLASH_LITE` among 2.5 members.
- [ ] `test_no_retired_gemini_literal_in_src` passes (spec AC-1).
- [ ] Live gate evidence in `artifacts/logs/` (spec AC-12).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_google_models.py -q`
- `pytest packages/ai-parrot/tests/clients/test_google_models.py -q`
- `pytest packages/ai-parrot/tests/test_llm_factory.py -q`
- `pytest packages/ai-parrot/tests/test_no_retired_gemini_defaults.py -q`
- `pytest tests/unit/test_google_document_understanding.py -q`

## Test Specification
See the blueprint.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§3 M5, §5 AC-1/3/12, §7 Known Risks).
3. Check dependencies: TASK-5146, 5147, 5148, 5149, 5150, 5151 and 5153 must all be `done`.
4. Re-grep `models.py`: TASK-5146 shifted the line numbers.
5. Mark the task `in-progress` in the index and commit only that file.
6. Implement the Steps in order.
7. Run the Validation Commands with an absolute worktree `PYTHONPATH`.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5155 google-migration verified`, then fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
