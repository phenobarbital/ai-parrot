---
id: F002
query_id: Q004
type: read
intent: "Verify how duplicate values behave in the GoogleModel enum"
executed_at: 2026-10-15T17:42:00Z
parent_id: F001
depth: 1
---

# F002 — 19 of GoogleModel's 53 names are silent Enum aliases

## Summary

`GoogleModel` is a plain `Enum`, so members sharing a value become **aliases**
of the first (canonical) member, not distinct members. An AST count over
`models.py` gives **53 assigned names but only 34 distinct values** — 19 names
collapse. Consequences: iteration (`for m in GoogleModel`) yields 34 members,
`GoogleModel(<value>)` always returns the canonical member, and
`alias.name` reports the canonical name. This is load-bearing for anything that
enumerates the catalogue, and it is the mechanism by which old 3.x names were
previously "retired" — remapped onto a live id rather than deleted.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 31-40
  symbol: `GoogleModel` (alias block)
  excerpt: |
    # Aliases for 3.x models mapped to active GA equivalents
    GEMINI_3_PRO = "gemini-3.1-pro-preview"
    GEMINI_3_PRO_PREVIEW = "gemini-3.1-pro-preview"
    GEMINI_3_FLASH = "gemini-3.5-flash"
    GEMINI_3_FLASH_PREVIEW = "gemini-3.5-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 50-52
  symbol: `GEMINI_3_5_FLASH_COMPUTER_USE`
  excerpt: |
    GEMINI_COMPUTER_USE = "gemini-2.5-computer-use-preview-10-2025"
    GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"
    GEMINI_3_5_FLASH_COMPUTER_USE = "gemini-3.5-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 11-73
  symbol: `GoogleModel` (AST-measured aliasing)
  excerpt: |
    # measured via ast over models.py:
    # GoogleModel: 53 members, 34 distinct values
    #   'gemini-3.1-pro-preview'  canonical=GEMINI_PRO_LATEST
    #       aliases=[GEMINI_3_1_PRO_PREVIEW, GEMINI_3_PRO, GEMINI_3_PRO_PREVIEW]
    #   'gemini-3.5-flash'        canonical=GEMINI_3_5_FLASH
    #       aliases=[GEMINI_3_FLASH, GEMINI_3_FLASH_PREVIEW, GEMINI_3_5_FLASH_COMPUTER_USE]
    #   'gemini-3.1-flash-lite'   canonical=GEMINI_FLASH_LITE_LATEST  (+3 aliases)
    #   ... 11 aliased values in total; VertexAIModel: 17 members, 17 distinct (no aliases)

## Notes

`GEMINI_3_5_FLASH_COMPUTER_USE` is an alias of `GEMINI_3_5_FLASH`, so
`GoogleModel.GEMINI_3_5_FLASH_COMPUTER_USE.name` returns `"GEMINI_3_5_FLASH"`.
Any new 4.x name assigned an already-present value will disappear the same way.
