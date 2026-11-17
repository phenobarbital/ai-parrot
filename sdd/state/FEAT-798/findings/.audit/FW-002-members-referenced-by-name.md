---
id: FW-002
query_id: Q002
type: wiki_page
intent: "Precedent: FEAT-688 finding on enum members that are load-bearing by name — tells us which 2.5 members cannot be deleted without AttributeError."
executed_at: 2026-11-04T01:38:22Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FW-002 — Three 2.5 members are referenced by NAME in live src/ (import-time AttributeError if deleted)

## Summary

Wiki page `file:sdd/state/FEAT-688/findings/F010-members-referenced-by-name.md` (sweep dated 2026-10-15 over `ai-parrot-client-google/src`, `ai-parrot-server/src`, `ai-parrot/src`). Twelve `GoogleModel.<MEMBER>` name references exist; among them three 2.5 members: `GEMINI_2_5_FLASH`, `GEMINI_2_5_FLASH_TTS`, `GEMINI_2_5_PRO`. Deleting any of these is an `AttributeError` at import time, so every call site must be edited in the same commit. The client's own defaults (`_default_model`, `_default_reformat_model`) point at `GEMINI_FLASH_LATEST` / `GEMINI_3_5_FLASH`, not at 2.5. The sweep is three weeks old — a fresh grep is required before deletion.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-73
  symbol: members referenced by name across src/
  excerpt: |
    GoogleModel.GEMINI_2_5_FLASH        GoogleModel.GEMINI_3_1_FLASH_IMAGE
    GoogleModel.GEMINI_2_5_FLASH_TTS    GoogleModel.GEMINI_3_5_FLASH
    GoogleModel.GEMINI_2_5_PRO          GoogleModel.GEMINI_3_FLASH_PREVIEW   <-- alias of gemini-3.5-flash
    GoogleModel.GEMINI_FLASH_LATEST     GoogleModel.IMAGEN_3 / IMAGEN_4
    GoogleModel.VEO_3_1 / _FAST / _LITE

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 127, 166-172
  symbol: `_default_model`, `_default_reformat_model`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py`
  lines: 34
  symbol: `_default_model`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value

## Notes

- F010 lists the members but not the file:line of each 2.5 reference; the codebase lane's Q011 grep must produce them.
- [cross-lane: type=grep, intent=locate the exact call sites of GoogleModel.GEMINI_2_5_FLASH / GEMINI_2_5_PRO / GEMINI_2_5_FLASH_TTS (and the parrot_tools / loaders / pipelines trees, which F010 did not sweep)]
