---
id: F008
query_id: Q013,Q014,Q015
type: grep
intent: Assess the other FEAT-397 holdout clients (widened scope, requested at the Phase-1 gate)
executed_at: 2026-08-03T00:12:00Z
parent_id: null
depth: 0
---

# F008 — Of the four remaining holdouts, only `Gemma4Client` is a near-identical fit

## Summary

Widened-scope survey of the clients FEAT-397 deferred beyond Bedrock:

- **`Gemma4Client`** (`gemma4.py:400+`) ALREADY has a bounded tool loop
  (`for _round in range(MAX_TOOL_ROUNDS)` at 533) that manually sums usage
  field-by-field at 542-546. It needs only `_emit_round_event` call sites and
  a swap to `CompletionUsage.__add__` — the smallest remaining gap, matching
  the FEAT-397 spec's own note (F001).
- **`ClaudeAgentClient`** (`claude_agent.py:231`) has NO client-side tool loop:
  the agent SDK runs turns internally and reports an aggregate via
  `CompletionUsage.from_claude_agent(... num_turns=...)` (`basic.py`). Per-round
  data would have to come from streaming `AssistantMessage`s, not a loop —
  a materially different design.
- **`TransformersClient`** (`hf.py:53`) has no tool loop; it builds a single
  `CompletionUsage` at `hf.py:457` per generation. Per-round is not meaningful.
- **`GeminiLiveClient`** (`live.py:482`) is a voice/streaming client with its
  OWN `LiveCompletionUsage` dataclass (`live.py:61`), not `CompletionUsage`.
  Bringing it in requires reconciling two usage types first.

Separately, `LLMCodeDispatcher` (`flows/dev_loop/dispatchers/llm.py:190`) drives
its own `for turn_index in range(profile.max_turns)` loop calling
`client._chat_completion` (369-377), bypassing `ask()` entirely — so FEAT-397's
in-`ask()` accumulation never runs there for ANY client, Bedrock included.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/gemma4.py`
  lines: 533-546
  symbol: `Gemma4Client` tool loop (manual accumulation, no emission)
  excerpt: |
    for _round in range(MAX_TOOL_ROUNDS):
        parsed, usage, gen_time = self._generate(
    ...
        total_usage = CompletionUsage(
            prompt_tokens=total_usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=total_usage.completion_tokens + usage.completion_tokens,
            total_tokens=total_usage.total_tokens + usage.total_tokens,

- path: `packages/ai-parrot/src/parrot/clients/claude_agent.py`
  lines: 231, 502-507
  symbol: `ClaudeAgentClient`

- path: `packages/ai-parrot/src/parrot/models/basic.py`
  lines: 186-200
  symbol: `CompletionUsage.from_claude_agent`
  excerpt: |
    The agent SDK exposes usage at two levels: a per-turn ``usage`` dict on
    each ``AssistantMessage`` ... and an aggregate ``ResultMessage.usage``
    plus ``ResultMessage.total_cost_usd`` and ``ResultMessage.num_turns``.

- path: `packages/ai-parrot/src/parrot/clients/hf.py`
  lines: 53, 456-457
  symbol: `TransformersClient`

- path: `packages/ai-parrot/src/parrot/clients/live.py`
  lines: 61, 482
  symbol: `GeminiLiveClient`, `LiveCompletionUsage`

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py`
  lines: 190-191, 369-377
  symbol: `LLMCodeDispatcher` (bypasses ask())
  excerpt: |
    for turn_index in range(profile.max_turns):
        response = await self._chat_completion(
    ...
    async def _chat_completion(
    ...
        method = getattr(client, "_chat_completion", None)

## Notes

Recommended split: keep FEAT-404 to Bedrock + Nova (+ optionally Gemma4, which
is cheap and shares the shape). `ClaudeAgentClient`, `TransformersClient`,
`GeminiLiveClient` and the `LLMCodeDispatcher` gap each need their own design
decision and should be separate features, not tasks bolted onto this one.
