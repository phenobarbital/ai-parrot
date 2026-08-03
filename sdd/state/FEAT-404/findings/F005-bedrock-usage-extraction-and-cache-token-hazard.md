---
id: F005
query_id: Q007
type: read
intent: Locate how Bedrock/Nova currently parse Converse usage so accumulation reuses existing extraction, and check the merge semantics
executed_at: 2026-08-03T00:09:00Z
parent_id: null
depth: 0
---

# F005 — `CompletionUsage.from_bedrock` exists, but its `extra_usage` shape loses cache tokens under `__add__`

## Summary

`CompletionUsage.from_bedrock()` (`models/basic.py:147`) already parses the
Converse camelCase payload (`inputTokens`/`outputTokens`) and preserves
`cacheReadInputTokens`/`cacheWriteInputTokens` in `extra_usage`. It is already
used by `BedrockConverseBase.invoke()` at `bedrock.py:1208`, so the extraction
helper needs no new code. **Hazard:** `CompletionUsage.__add__`
(`models/basic.py:273`) documents `extra_usage` as a *shallow merge where the
right-hand operand wins on key conflicts* — so accumulating N rounds
would leave `cacheReadInputTokens`/`cacheWriteInputTokens` equal to the LAST
round's values, not the sum, while `prompt_tokens`/`completion_tokens` DO sum.
Unlike other providers, `from_bedrock` puts these two counters in
`extra_usage` as first-class numbers, so this is a Bedrock-specific
correctness question the spec must resolve explicitly.

## Citations

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 147-168
  symbol: `CompletionUsage.from_bedrock`
  excerpt: |
    @classmethod
    def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":
        """Create from AWS Bedrock Converse API usage dict. ..."""
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        return cls(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            extra_usage={
                "cacheReadInputTokens": usage.get("cacheReadInputTokens", 0),
                "cacheWriteInputTokens": usage.get("cacheWriteInputTokens", 0),
            }
        )

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 273-293
  symbol: `CompletionUsage.__add__`
  excerpt: |
    def __add__(self, other: Any) -> "CompletionUsage":
        """Field-wise sum for multi-round tool-use accumulation.
        Semantics:
            - ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``:
              plain integer sum.
            ...
            - ``extra_usage``: shallow merge; the right-hand operand wins
              on key conflicts.

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 66
  symbol: `CompletionUsage` (docstring)
  excerpt: |
    ``extra_usage["rounds"]`` (set by the caller, not by ``__add__``

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 1208
  symbol: `BedrockConverseBase.invoke` (existing from_bedrock call site)
  excerpt: |
    usage = CompletionUsage.from_bedrock(result.get("usage", {}))

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 628-629
  symbol: `BedrockConverseBase.ask` (docstring already promises cache counters)
  excerpt: |
    ``cacheWriteInputTokens`` in ``CompletionUsage.extra_usage``
    (already surfaced by ``CompletionUsage.from_bedrock()``,

## Notes

Three candidate resolutions for the spec: (a) accept last-round-wins and
document it; (b) sum the two cache counters explicitly in the Bedrock loop
after `__add__`; (c) teach `__add__` to sum numeric `extra_usage` keys —
option (c) has cross-client blast radius and should probably be rejected.
`ask()`'s own docstring at 628-629 advertises these counters, which raises the
stakes on getting the multi-round value right.
