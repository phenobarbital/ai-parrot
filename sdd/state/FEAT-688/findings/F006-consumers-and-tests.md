---
id: F006
query_id: Q003,Q010,Q013
type: grep
intent: "Find every consumer of GoogleModel and the tests that pin specific model ids"
executed_at: 2026-10-15T17:50:00Z
parent_id: F001
depth: 1
---

# F006 — Small consumer set, but one public HTTP surface enumerates the enum

## Summary

Outside its own package, `GoogleModel` has only a handful of live consumers
(stale copies under `packages/*/build/` excluded). The one that matters is
`handlers/google_generation.py`, which returns `[model.value for model in
GoogleModel]` over HTTP — because of the aliasing in F002 this already publishes
34 ids, not 53, and any enum edit changes that response. Three test modules pin
exact name→value pairs and would fail on removal. Core's `conf.py` deliberately
holds a **literal** fallback string rather than importing the enum.

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

- path: `packages/ai-parrot/tests/test_google_models.py`
  lines: 7-39
  symbol: catalogue assertions
  excerpt: |
    assert GoogleModel.GEMINI_3_8_FLASH.value == "gemini-3.8-flash"
    assert GoogleModel.GEMINI_3_7_FLASH_THINKING.value == "gemini-3.7-flash-thinking"
    assert GoogleModel("gemini-3.5-flash") is GoogleModel.GEMINI_3_5_FLASH

- path: `packages/ai-parrot/tests/clients/test_google_models.py`
  lines: 11-26
  symbol: computer-use + baseline assertions
  excerpt: |
    assert "GEMINI_COMPUTER_USE" in GoogleModel.__members__
    assert GoogleModel.__members__["GEMINI_3_FLASH_COMPUTER_USE"].value == ("gemini-3-flash-preview")
    assert GoogleModel.GEMINI_2_5_PRO.value == "gemini-2.5-pro"

- path: `packages/ai-parrot-server/src/parrot/handlers/models/understanding.py`
  lines: 86
  symbol: model override field
  excerpt: |
    description="GoogleModel override (e.g. 'gemini-3.1-flash-lite-preview').",

- path: `packages/ai-parrot-server/tests/unit/handlers/test_llm_models_catalogue.py`
  lines: 11-19
  symbol: `test_no_enum_imports`
  excerpt: |
    """AC: `grep -n "Model\\b" handlers/llm.py` shows no provider enum names."""
    assert "GoogleModel" not in src

- path: `packages/ai-parrot/src/parrot/bots/flows/result_agent.py`
  lines: 35
  symbol: docstring reference
  excerpt: |
    ``GoogleModel.GEMINI_FLASH_LATEST``) when no ``llm`` is supplied

## Notes

Note the split: Google model *tests* live in `packages/ai-parrot/tests/`, not in
`packages/ai-parrot-client-google/tests/`, a FEAT-523 leftover. The example id
in `understanding.py:86` (`gemini-3.1-flash-lite-preview`) is an alias name, not
a canonical value.
