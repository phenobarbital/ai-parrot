---
id: F023
query_id: Q001
type: wiki_query
intent: "Orient: where and how does AbstractClient extract provider token usage today, and is there a normalised Usage object."
executed_at: 2026-10-30T22:37:36Z
duration_ms: 0
parent_id: null
depth: 0
lane: wiki
merged_from: ['FW-001']
---

# F023 — A normalised `CompletionUsage` already exists, with per-provider factories and OTel-GenAI field aliases

## Summary

The source's premise that usage is "extracted per completion" but has no home is wrong in the
client layer: `CompletionUsage` is a fully-built, unified usage model with a factory per provider
(`from_openai`, `from_groq`, `from_claude`, `from_claude_agent`, `from_bedrock`, `from_gemini`,
`from_grok`), a field-wise `__add__` for multi-round tool-use accumulation, and `input_tokens` /
`output_tokens` properties whose docstrings explicitly name the **OTel GenAI** vocabulary.
`AIMessage.total_usage()` already aggregates it across all rounds of a generating call. A usage
plane therefore does NOT need a new extraction path — it needs a *sink* and a *correlation key*.

Wiki pages: `sym:...models/basic.py#CompletionUsage` (score=1.00 on the FEAT-404 finding page),
`file:packages/ai-parrot/src/parrot/models/basic.py` (score=0.48).

## Citations

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 48-312
  symbol: `CompletionUsage`
  excerpt: |
    class CompletionUsage(...):
        """Unified completion usage tracking across different LLM providers."""

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 104-112
  symbol: `CompletionUsage.input_tokens` / `CompletionUsage.output_tokens`
  excerpt: |
    # "Alias for :attr:`prompt_tokens` (OTel GenAI ``input_tokens``)."
    # "Alias for :attr:`completion_tokens` (OTel GenAI ``output_tokens``)."

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 273-312
  symbol: `CompletionUsage.__add__`
  excerpt: |
    # "Field-wise sum for multi-round tool-use accumulation."

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 115-271
  symbol: `from_openai` L115-121 · `from_groq` L124-134 · `from_claude` L137-144 · `from_bedrock` L147-165 · `from_gemini` L168-182 · `from_grok` L245-271

- path: `packages/ai-parrot/src/parrot/models/responses.py`
  lines: 287-299
  symbol: `AIMessage.total_usage`
  excerpt: |
    # "Total token usage across all rounds of the generating call."

- path: `packages/ai-parrot/tests/test_completion_usage.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "Tests for CompletionUsage's bidirectional token vocabulary."

## Notes

A known defect is already filed against this surface: `sdd/state/FEAT-404/findings/F005-bedrock-usage-extraction-and-cache-token-hazard.md`
("`CompletionUsage.from_bedrock` exists, but its `extra_usage` shape loses cache tokens under `__add__`").
That is directly load-bearing for the source's four-counter cost model.

[cross-lane: type=read, intent=Read models/basic.py L48-312 to enumerate which of the four counters (input/output/cache_read/cache_creation) are first-class fields vs. carried in extra_usage]
