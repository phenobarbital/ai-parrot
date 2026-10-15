---
id: F010
query_id: Q003
type: grep
intent: "Which GoogleModel members are referenced by NAME in source (undeletable without editing the call site)"
executed_at: 2026-10-15T18:00:00Z
parent_id: F002
depth: 2
---

# F010 — 12 enum members are load-bearing by name, one of them an alias

## Summary

A name-level sweep of the three live `src/` trees finds exactly 12
`GoogleModel.<MEMBER>` references. Deleting any of these members turns the
reference into an `AttributeError` **at import time**, not a runtime fallback.
The notable case is `GEMINI_3_FLASH_PREVIEW`, which F002 shows is an *alias*
of `gemini-3.5-flash` — so under a pure-deletion policy an alias is not free to
remove either. The media members (`VEO_*`, `IMAGEN_*`, `LYRIA`) are consumed by
the reel pipeline and are unrelated to the Gemini generation refresh.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 127, 166-172
  symbol: `GoogleModel.GEMINI_FLASH_LATEST`, `GoogleModel.GEMINI_3_5_FLASH`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value
    _default_reformat_model: str = GoogleModel.GEMINI_3_5_FLASH.value

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py`
  lines: 34
  symbol: `GoogleModel.GEMINI_FLASH_LATEST`
  excerpt: |
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-73
  symbol: members referenced by name across `src/`
  excerpt: |
    GoogleModel.GEMINI_2_5_FLASH        GoogleModel.GEMINI_3_1_FLASH_IMAGE
    GoogleModel.GEMINI_2_5_FLASH_TTS    GoogleModel.GEMINI_3_5_FLASH
    GoogleModel.GEMINI_2_5_PRO          GoogleModel.GEMINI_3_FLASH_PREVIEW   <-- alias of gemini-3.5-flash
    GoogleModel.GEMINI_FLASH_LATEST     GoogleModel.IMAGEN_3 / IMAGEN_4
    GoogleModel.VEO_3_1 / _FAST / _LITE

## Notes

Scope of the sweep: `packages/ai-parrot-client-google/src`,
`packages/ai-parrot-server/src`, `packages/ai-parrot/src`. Stale copies under
`packages/*/build/` were excluded; they still import the pre-FEAT-523 path and
are not installed.
