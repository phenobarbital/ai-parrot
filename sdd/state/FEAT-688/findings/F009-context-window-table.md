---
id: F009
query_id: Q011
type: grep
intent: "Find model-window / token-budget tables keyed by Gemini model"
executed_at: 2026-10-15T17:53:00Z
parent_id: null
depth: 0
---

# F009 — The compaction budget keys Gemini by bare prefix, so a 4.x id inherits 1M

## Summary

The FEAT-525 per-turn compaction budget resolves a context window per model
from a prefix table. Gemini has exactly **one** entry — the bare prefix
`"gemini-"` mapped to 1 048 576 tokens — so any new `gemini-4…` id is matched
automatically and inherits a 1M window with no edit required. This is benign if
Argon's real window is 1M or larger, and silently wrong (over-budget history,
truncation at the provider instead of at the compactor) if it is smaller.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 51
  symbol: `MODEL_WINDOWS`
  excerpt: |
    "gemini-": 1_048_576,

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/budget.py`
  lines: 1-24
  symbol: `GenerationBudget`
  excerpt: |
    """Shared generation budget primitive for the deterministic E2E gate (FEAT-581, M6).
    a per-run, in-process guard that the (not-yet-created) live E2E actor and an
    optional ``GoogleGenAIClient`` hook use to cap nonstreaming Google generation
    calls without any provider SDK access of its own.

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/client.py`
  lines: 132-143
  symbol: `_invoke_max_tokens` / `_default_max_tokens`
  excerpt: |
    # Gemini bills reasoning tokens against max_output_tokens, and the Gemini 3.x
    # Pro family is thinking-only (see _requires_thinking) so reasoning cannot be
    # switched off.
    _invoke_max_tokens: int = 16384
    _default_max_tokens: Optional[int] = None

## Notes

`client.py:132-143` documents a 65535 output-token ceiling for the 3.x family
and deliberately sends no `max_output_tokens` so the provider applies its own
cap. If a 4.x family changes that ceiling the comment goes stale but no code
breaks — the `None` default is already generation-agnostic.
