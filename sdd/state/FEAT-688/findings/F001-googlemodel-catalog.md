---
id: F001
query_id: Q001,Q003,Q004
type: read
intent: "Locate and read the GoogleModel catalog in full"
executed_at: 2026-10-15T17:40:00Z
parent_id: null
depth: 0
---

# F001 — GoogleModel / VertexAIModel live in the ai-parrot-client-google satellite

## Summary

The catalogue is a single 102-line pure-data module in the **`ai-parrot-client-google`**
satellite (FEAT-523 folder convention), not in core. It declares two plain
`Enum` classes: `GoogleModel` (53 member names) and `VertexAIModel` (17).
There is **no capability metadata, no deprecation marker and no context-window
field** on any member — the enum maps a NAME to a model-id STRING and nothing
more. `GoogleGenAIClient.models` points at `GoogleModel`, which is how
`LLMFactory` discovers the catalogue.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 1-12
  symbol: `GoogleModel`
  excerpt: |
    """Google provider model catalogue (FEAT-523 folder convention).
    ``GoogleModel`` and ``VertexAIModel`` relocated byte-identical from
    ``parrot/models/google.py`` (TASK-2841). Pure data — no I/O, no imports
    from ``client.py``.
    """
    from enum import Enum
    class GoogleModel(Enum):

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 14-17
  symbol: `GoogleModel.GEMINI_*_LATEST`
  excerpt: |
    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    GEMINI_PRO_LATEST = "gemini-3.1-pro-preview"
    GEMINI_PRO_CUSTOMTOOLS = "gemini-3.1-pro-preview-customtools"
    GEMINI_FLASH_LITE_LATEST = "gemini-3.1-flash-lite"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 18-30
  symbol: `GoogleModel` (3.x series)
  excerpt: |
    # Gemini 3.8 series
    GEMINI_3_8_FLASH = "gemini-3.8-flash"
    # Gemini 3.7 series
    GEMINI_3_7_FLASH = "gemini-3.7-flash"
    GEMINI_3_7_PRO = "gemini-3.7-pro"
    GEMINI_3_7_FLASH_THINKING = "gemini-3.7-flash-thinking"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 76-96
  symbol: `VertexAIModel`
  excerpt: |
    class VertexAIModel(Enum):
        """Note: Gemini 3.x models require location='global' on Vertex AI.
        Preview models additionally require api_version='v1beta1'."""
        GEMINI_3_8_FLASH = "gemini-3.8-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 125-127
  symbol: `GoogleGenAIClient.models`
  excerpt: |
    provider_keys: tuple[str, ...] = ("google",)
    models: type[Enum] = GoogleModel
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value

## Notes

`VertexAIModel` is a strict, smaller subset — it carries its own comment about
`location='global'` and `api_version='v1beta1'`. Any new family added to
`GoogleModel` has to be decided separately for Vertex.
