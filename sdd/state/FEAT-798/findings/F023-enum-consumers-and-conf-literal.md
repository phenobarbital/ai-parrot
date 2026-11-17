---
id: F023
query_id: Q003
type: wiki_page
intent: "Precedent: FEAT-688 finding on enum consumers and the public /models HTTP surface."
executed_at: 2026-11-04T01:38:22Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F023 — Enum edits are a public API change (/models) and three test modules pin 2.5 values; conf.py holds a literal fallback

## Summary

Wiki page `file:sdd/state/FEAT-688/findings/F006-consumers-and-tests.md`. `handlers/google_generation.py:42-44` returns `[model.value for model in GoogleModel]` over HTTP, so removing 2.5 members shrinks a public payload. `packages/ai-parrot/tests/clients/test_google_models.py:11-26` asserts `GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"` and `packages/ai-parrot/tests/test_google_models.py:7-39` pins other name→value pairs — both must change with the enum. Core `conf.py:446-454` deliberately holds a **literal** Google fallback (`"gemini-flash-latest"`) with no enum import (FEAT-523 decision), so a conf.py default change is a string edit, not an enum reference. Google model tests live under `packages/ai-parrot/tests/`, not in the client satellite.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/google_generation.py`
  lines: 42-44
  symbol: `list_models`
  excerpt: |
    from parrot.clients.google.models import GoogleModel
    return [model.value for model in GoogleModel]

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 446-454
  symbol: Google default-model fallback
  excerpt: |
    # FEAT-523 (TASK-2841): GoogleModel relocated out of parrot.models.google.
    # end state (literal fallback, no GoogleModel import) — applied here instead
    # "gemini-flash-latest" is GoogleModel.GEMINI_FLASH_LATEST.value, verified

- path: `packages/ai-parrot/tests/clients/test_google_models.py`
  lines: 11-26
  symbol: computer-use + baseline assertions
  excerpt: |
    assert "GEMINI_COMPUTER_USE" in GoogleModel.__members__
    assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"

- path: `packages/ai-parrot/tests/test_google_models.py`
  lines: 7-39
  symbol: catalogue assertions
  excerpt: |
    assert GoogleModel.GEMINI_3_8_FLASH.value == "gemini-3.8-flash"
    assert GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH

- path: `packages/ai-parrot/src/parrot/bots/flows/result_agent.py`
  lines: 35
  symbol: docstring reference
  excerpt: |
    ``GoogleModel.GEMINI_FLASH_LATEST``) when no ``llm`` is supplied

## Notes

- `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"` is also a 2.5-generation id (see F003); whether Google's 2.5 deprecation covers it is unknown from the codebase.
- [cross-lane: type=grep, intent=confirm conf.py line numbers still hold after FEAT-796 and list every Google default there]
