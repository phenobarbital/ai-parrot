# TASK-5160: Swap retired GoogleModel.GEMINI_2_5_* members out of the tracked examples and guard member names

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (<1h)
**Depends-on**: TASK-5154, TASK-5155
**Assigned-to**: unassigned
**Discovered-from**: `issue:00b3fc295988`

---

## Context

TASK-5155 deleted the retired `GoogleModel` members (`GEMINI_2_5_FLASH`, `GEMINI_2_5_FLASH_PREVIEW`,
`GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO_TTS`). TASK-5154's guard
(`test_no_retired_gemini_in_docs.py`, spec AC-10) only greps string ids, so three tracked examples that
reference the members *by name* slipped through and raise `AttributeError` when run.

## Scope

- `examples/agents/scraper.py`: `GEMINI_2_5_FLASH_PREVIEW` → `GEMINI_3_8_FLASH`.
- `examples/image_analysis/test.py`: `GEMINI_2_5_PRO` → `GEMINI_4_ARGON`.
- `examples/next/google.py`: every (commented-out) `GEMINI_2_5_FLASH` → `GEMINI_3_8_FLASH`.
- `packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py`: also flag the five retired member names.

**NOT in scope**: `GEMINI_2_5_FLASH_LITE[_PREVIEW]` and `GEMINI_2_5_FLASH_IMAGE[_PREVIEW]` — still supported
members; the guard must not match them.

## Files to Modify

- `examples/agents/scraper.py`
- `examples/image_analysis/test.py`
- `examples/next/google.py`
- `packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py`

## Codebase Contract

### Verified Imports
- `from parrot.clients.google.models import GoogleModel` — `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`

### Existing Signatures
- `GoogleModel.GEMINI_4_ARGON = "gemini-4-argon"`, `GoogleModel.GEMINI_3_8_FLASH = "gemini-3.8-flash"`

### Does NOT Exist
- `GoogleModel.GEMINI_2_5_FLASH`, `GEMINI_2_5_FLASH_PREVIEW`, `GEMINI_2_5_PRO`, `GEMINI_2_5_FLASH_TTS`,
  `GEMINI_2_5_PRO_TTS` (removed by TASK-5155; see `RETIRED_NAMES` in `tests/test_google_models.py`)

## Acceptance Criteria

- [x] No file under `docs/`, `examples/`, `plugins/` names a retired `GEMINI_2_5_*` member.
- [x] The guard test fails on a retired member name and does not match `GEMINI_2_5_FLASH_LITE` / `_IMAGE`.
- [x] `test_no_retired_gemini_in_docs.py` and `test_google_models.py` pass.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src pytest packages/ai-parrot/tests/test_no_retired_gemini_in_docs.py packages/ai-parrot/tests/test_google_models.py -q
```

## Completion Note

Filed and implemented by `/sdd-fix issue:00b3fc295988` after the FEAT-798 sdd-worker's review raised it.
Code commit `0a23e9f932`.

- `scraper.py` and `next/google.py` (10 commented-out call sites) → `GEMINI_3_8_FLASH`;
  `image_analysis/test.py` → `GEMINI_4_ARGON`.
- Guard: new `RETIRED_MEMBERS` regex (`GEMINI_2_5_FLASH[_PREVIEW|_TTS]`, `GEMINI_2_5_PRO[_TTS]`) plus a unit
  test proving it spares `GEMINI_2_5_FLASH_LITE*` / `GEMINI_2_5_FLASH_IMAGE*`.
- Mutation check: the regex matches 1/1/10 lines in the three files at the pre-fix base and 0 after.
- Validation: the task's command — 20 passed. `ruff check` clean.
