---
id: F022
query_id: Q022
type: grep
intent: Verify Gemini ThinkingConfig usage already exists somewhere — confirms the brainstorm's structured-output pattern is real.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F022 — `ThinkingConfig(include_thoughts=False)` already in use inside `parrot/clients/google/client.py`

## Summary

The Google GenAI client at `packages/ai-parrot/src/parrot/clients/google/client.py`
imports `ThinkingConfig` from `google.genai.types` (line 25) and instantiates
it with `include_thoughts=False` at line 1966 / 1972 / 1977. There is also a
`thinking_budget=0` variant used in `parrot/clients/google/analysis.py`
(lines 572, 1129). The brainstorm's plan to use
`ThinkingConfig(include_thoughts=False)` in summarizers is consistent with the
existing pattern — no new dependency or workaround needed.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 25-37
  symbol: import with fallback
  excerpt: |
    from google.genai.types import (
        ...,
        ThinkingConfig,
        ...
    )
    # except: ThinkingConfig = None  # type: ignore[assignment]

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 1957-1977
  symbol: example usage
  excerpt: |
    thinking_config = ThinkingConfig(...)
    thinking_config = ThinkingConfig(
        ...,
        include_thoughts=False,
    )
    thinking_config = ThinkingConfig(
        ...,
        include_thoughts=False,
    )

- path: `packages/ai-parrot/src/parrot/clients/google/analysis.py`
  lines: 572, 1129
  symbol: alternate (thinking_budget=0) variant
  excerpt: |
    config_args["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    ...
    thinking_config=types.ThinkingConfig(thinking_budget=0),

## Notes

- Confirmed. Spec can cite line 1966 of `client.py` as the canonical pattern.
- Note the two flavours: `include_thoughts=False` (don't surface chain-of-thought)
  vs. `thinking_budget=0` (disable thinking entirely). The brainstorm uses the
  former; both are valid.
