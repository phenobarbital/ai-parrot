---
id: FC-003
query_id: Q012
type: read
intent: "Read the GoogleModel / VertexAIModel catalogue: list the 2.5 members, their aliases, and the Gemini 4 Argon members as they stand today."
executed_at: 2026-11-04T01:39:51Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-003 — GoogleModel carries 9 gemini-2.5 members (3 aliases) + GEMINI_COMPUTER_USE; VertexAIModel carries 3; Argon is a single member

## Summary

`models.py` (99 lines) is pure data. `GoogleModel` has one Gemini 4 member, `GEMINI_4_ARGON = "gemini-4-argon"` (line 19), then 3.8/3.7/3.6/3.5/3.1 families, then a 2.5 block at lines 41-48 (`GEMINI_2_5_FLASH`, `_FLASH_PREVIEW` alias, `_FLASH_LITE`, `_FLASH_LITE_PREVIEW` alias, `_PRO`, `_FLASH_TTS`, `_PRO_TTS`, `_FLASH_IMAGE`), `GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"` (49) and `GEMINI_2_5_FLASH_IMAGE_PREVIEW` alias (59). `VertexAIModel` keeps `GEMINI_2_5_FLASH/_FLASH_LITE/_PRO` at lines 91-93. The request names only pro/flash; the catalogue also has 2.5 flash-lite, TTS, image and computer-use ids whose deprecation status is not established by the codebase.

**Merged from FW-008 (wiki lane):** `wikitoolkit query` top hit `file:packages/ai-parrot-client-google/src/parrot/clients/google/models.py` (1.00) → `sym:…#GoogleModel` (0.90, L11-70). The current enum carries a "Gemini 2.5 series" block of eleven names on 2.5 ids: `GEMINI_2_5_FLASH` / `GEMINI_2_5_FLASH_PREVIEW` (both `gemini-2.5-flash`), `GEMINI_2_5_FLASH_LITE` / `GEMINI_2_5_FLASH_LITE_PREVIEW` (both `gemini-2.5-flash-lite`), `GEMINI_2_5_PRO` (`gemini-2.5-pro`), `GEMINI_2_5_FLASH_TTS` (`gemini-2.5-flash-preview-tts`), `GEMINI_2_5_PRO_TTS` (`gemini-2.5-pro-preview-tts`), `GEMINI_2_5_FLASH_IMAGE` (`gemini-2.5-flash-image`), and `GEMINI_COMPUTER_USE` (`gemini-2.5-computer-use-preview-10-2025`). The request names only `gemini-2.5-{pro,flash}`; the other 2.5 ids (flash-lite, TTS, image, computer-use) are a scope decision. `GEMINI_4_ARGON` and the 3.x family (3.8 → 3.1) are present. `wikitoolkit related` on the file shows references from three examples, five test modules and no further src/ module (name-level src consumers are in FW-002).

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-19
  symbol: `GoogleModel`
  excerpt: |
    class GoogleModel(Enum):
        """Enum for Google AI models."""
        GEMINI_FLASH_LATEST = "gemini-flash-latest"
        GEMINI_PRO_LATEST = "gemini-3.1-pro-preview"
        GEMINI_PRO_CUSTOMTOOLS = "gemini-3.1-pro-preview-customtools"
        GEMINI_FLASH_LITE_LATEST = "gemini-3.1-flash-lite"
        # Gemini 4.x series (Argon)
        GEMINI_4_ARGON = "gemini-4-argon"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 41-49
  symbol: `GoogleModel.GEMINI_2_5_*`
  excerpt: |
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_PREVIEW = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"
    GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 59-60
  symbol: `GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW`
  excerpt: |
    GEMINI_2_5_FLASH_IMAGE_PREVIEW = "gemini-2.5-flash-image"
    GEMINI_FLASH_IMAGE = "gemini-3.1-flash-image"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 73-93
  symbol: `VertexAIModel`
  excerpt: |
    class VertexAIModel(Enum):
        ...
        GEMINI_2_5_FLASH = "gemini-2.5-flash"
        GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
        GEMINI_2_5_PRO = "gemini-2.5-pro"

<!-- merged from FW-008 -->
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-18
  symbol: `GoogleModel` (head + Argon)
  excerpt: |
    class GoogleModel(Enum):
        GEMINI_FLASH_LATEST = "gemini-flash-latest"
        GEMINI_PRO_LATEST = "gemini-3.1-pro-preview"
        GEMINI_FLASH_LITE_LATEST = "gemini-3.1-flash-lite"
        # Gemini 4.x series (Argon)
        GEMINI_4_ARGON = "gemini-4-argon"
        # Gemini 3.8 series
        GEMINI_3_8_FLASH = "gemini-3.8-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 37-48
  symbol: `GoogleModel` Gemini 2.5 series block
  excerpt: |
    # Gemini 2.5 series
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_PREVIEW = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "gemini-2.5-flash-lite"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"
    GEMINI_2_5_FLASH_IMAGE = "gemini-2.5-flash-image"
    GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 49-51
  symbol: computer-use aliases
  excerpt: |
    GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"
    GEMINI_3_5_FLASH_COMPUTER_USE = "gemini-3.5-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: n/a
  symbol: `VertexAIModel` (sym page 0.56)
  excerpt: |
    Enum for Vertex AI models. — untouched by FEAT-688 (U5); may carry its own 2.5 ids

- path: `packages/ai-parrot/tests/clients/test_google_models.py`
  lines: n/a
  symbol: `TestGoogleModelComputerUseEntries.test_existing_entries_unchanged` (0.94)
  excerpt: |
    Ensure existing model entries are not broken.  (asserts GEMINI_2_5_PRO per FW-003)

- path: `examples/agents/scraper.py`
  lines: n/a
  symbol: references models.py (wiki_related)
  excerpt: |
    examples/forms/form_agent.py and examples/pageindex/pageindex_compliance_agent.py also reference GoogleModel

- path: `tests/unit/test_google_document_understanding.py`
  lines: n/a
  symbol: `TestDocumentUnderstanding.test_model_enum_accepted`
  excerpt: |
    GoogleModel enum values are accepted for the model parameter.

## Notes

- Plain `Enum` → duplicate values are silent aliases (`GEMINI_2_5_FLASH_PREVIEW`, `GEMINI_2_5_FLASH_LITE_PREVIEW`, `GEMINI_2_5_FLASH_IMAGE_PREVIEW`). Iteration (`list_models`, FC-012) yields canonical members only.
- There are no 4.x members other than `GEMINI_4_ARGON` — no 4.x "flash"/"lite" tier exists in the catalogue to replace `gemini-2.5-flash` one-to-one.

[merged-from: FW-008] - Alias trap (FEAT-688 §7): `GEMINI_2_5_FLASH_PREVIEW` and `GEMINI_2_5_FLASH_LITE_PREVIEW` are aliases; `test_google_model_alias_count` pins 49 names / 31 values and will fail on any deletion — update it in the same task.
- [cross-lane: type=grep, intent=does VertexAIModel carry gemini-2.5 ids, and does any src/ consumer reference them by name]
- [cross-lane: type=read, intent=line-exact read of models.py (the wiki excerpt has no line numbers for the 2.5 block)]
