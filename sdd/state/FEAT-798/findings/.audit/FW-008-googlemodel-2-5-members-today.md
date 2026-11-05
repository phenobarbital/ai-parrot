---
id: FW-008
query_id: Q008
type: wiki_query
intent: "Orient: which modules reference the 2.5 enum members or ids according to the graph (consumers outside the client package)."
executed_at: 2026-11-04T01:40:08Z
duration_ms: 5000
parent_id: null
depth: 1
---

# FW-008 — GoogleModel today holds 11 members on 2.5-generation ids (8 distinct values); references cluster in tests and examples

## Summary

`wikitoolkit query` top hit `file:packages/ai-parrot-client-google/src/parrot/clients/google/models.py` (1.00) → `sym:…#GoogleModel` (0.90, L11-70). The current enum carries a "Gemini 2.5 series" block of eleven names on 2.5 ids: `GEMINI_2_5_FLASH` / `GEMINI_2_5_FLASH_PREVIEW` (both `gemini-2.5-flash`), `GEMINI_2_5_FLASH_LITE` / `GEMINI_2_5_FLASH_LITE_PREVIEW` (both `gemini-2.5-flash-lite`), `GEMINI_2_5_PRO` (`gemini-2.5-pro`), `GEMINI_2_5_FLASH_TTS` (`gemini-2.5-flash-preview-tts`), `GEMINI_2_5_PRO_TTS` (`gemini-2.5-pro-preview-tts`), `GEMINI_2_5_FLASH_IMAGE` (`gemini-2.5-flash-image`), and `GEMINI_COMPUTER_USE` (`gemini-2.5-computer-use-preview-10-2025`). The request names only `gemini-2.5-{pro,flash}`; the other 2.5 ids (flash-lite, TTS, image, computer-use) are a scope decision. `GEMINI_4_ARGON` and the 3.x family (3.8 → 3.1) are present. `wikitoolkit related` on the file shows references from three examples, five test modules and no further src/ module (name-level src consumers are in FW-002).

## Citations

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

- Alias trap (FEAT-688 §7): `GEMINI_2_5_FLASH_PREVIEW` and `GEMINI_2_5_FLASH_LITE_PREVIEW` are aliases; `test_google_model_alias_count` pins 49 names / 31 values and will fail on any deletion — update it in the same task.
- [cross-lane: type=grep, intent=does VertexAIModel carry gemini-2.5 ids, and does any src/ consumer reference them by name]
- [cross-lane: type=read, intent=line-exact read of models.py (the wiki excerpt has no line numbers for the 2.5 block)]
