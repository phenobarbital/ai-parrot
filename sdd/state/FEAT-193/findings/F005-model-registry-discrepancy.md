---
id: F005
intent: Verify the user's whitelist against the GoogleModel enum
query_ids: [Q007]
---

# F005 — Model registry discrepancy (HIGH-PRIORITY CAVEAT)

The user's claimed whitelist ⟶ registry mismatch is significant.

## Citations

`packages/ai-parrot/src/parrot/models/google.py:9-34` — `GoogleModel` enum
contents (filtered to relevant entries):

```python
class GoogleModel(Enum):
    GEMINI_3_PRO                    = "gemini-3.1-pro-preview"
    GEMINI_3_PRO_PREVIEW            = "gemini-3.1-pro-preview"
    GEMINI_3_FLASH                  = "gemini-3-flash-preview"
    GEMINI_3_FLASH_PREVIEW          = "gemini-3-flash-preview"
    GEMINI_FLASH_LATEST             = "gemini-3-flash-preview"
    GEMINI_3_1_FLASH_LITE_PREVIEW   = "gemini-3.1-flash-lite-preview"
    GEMINI_3_FLASH_LITE_PREVIEW     = "gemini-3.1-flash-lite-preview"
    ...
    GEMINI_2_5_PRO                  = "gemini-2.5-pro"
    GEMINI_PRO_LATEST               = "gemini-3.1-pro-preview"
    GEMINI_FLASH_LITE_LATEST        = "gemini-3.1-flash-lite-preview"
```

## Discrepancy table

| User's source whitelist     | Registry contains?                                  | Behaviour |
|-----------------------------|-----------------------------------------------------|-----------|
| `gemini-3.1-flash-lite`     | NO (`gemini-3.1-flash-lite-preview` exists)         | Either the user's test was actually calling the `-preview` variant via Google's API resolution, or it failed. The combined-mode whitelist should use the **preview** model ID. |
| `gemini-3.5-flash`          | **NOT in enum at all**                              | Unknown. The user's analysis claims this is "fully compatible", but the codebase has no record of this identifier. Either it's a real Google model that hasn't been added to the registry yet, or the test was hitting a different model than intended. |
| `gemini-3.1-pro-preview`    | YES (`GEMINI_3_PRO_PREVIEW`)                        | Safe to whitelist. |

## Notes

- This is the **single material unknown** for FEAT-193: is `gemini-3.5-flash`
  a real model identifier that needs to be added to `GoogleModel`? Or did the
  user's test resolve it to a different model? This must be confirmed with
  the user (Phase 5 Q&A).
- Two ways to gate the combined-mode capability:
  1. **Prefix-based** (matches existing `_is_gemini3_model` pattern) — e.g.
     `startswith('gemini-3.1-pro') or startswith('gemini-3.1-flash-lite')
     or startswith('gemini-3.5-flash')`. Robust to preview-suffix drift.
  2. **Explicit enum membership** — a `frozenset` of model values.
     Stricter, but requires maintenance every time Google releases a model.
  Recommendation: **prefix-based**, consistent with `_is_gemini3_model`.
- The user's analysis flags `gemini-3.1-flash-lite` as "compatible but
  unstable" (AFC infinite-loop risk, SDK warnings). Including it in the
  whitelist by default is questionable — see the proposal's "Open Questions"
  section.
