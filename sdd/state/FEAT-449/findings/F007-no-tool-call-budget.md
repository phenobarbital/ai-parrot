---
id: F007
query_id: Q007
type: grep
intent: Determine whether per-execution tool-call budgets are enforceable in ToolManager (the design requires code-enforced CENDOJ caps, not prompt caps)
executed_at: 2026-08-23T00:21:58Z
depth: 0
parent_id: null
---

# F007 — The interception seam exists (TOOL_CALL guardrail, runs first in execute_tool) but NO counting/rate-limit guardrail exists

## Summary

The source requires CENDOJ call budgets "enforced in code via the ToolManager, not by prompt".
The seam for that is real: `ToolManager.execute_tool()` runs a `GuardrailStage.TOOL_CALL`
pipeline (FEAT-406) as its **first** step, before `GrantGuard`/`ConfirmationGuard`, and a
guardrail there can BLOCK a call. However, a grep for `rate_limit|max_calls|call_count|quota|
budget` across the entire `bots/guardrails/` tree returns **0 matches** — the shipped
guardrails are `moderation`, `pbac`, `prompt_injection`, `secrets`, and PBAC is
policy ALLOW/DENY, not counter-based. A per-execution call budget is therefore new work, but
it is a small, well-defined new `Guardrail` subclass on an existing extension point rather
than a change to ToolManager.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 1519, 1573-1610
  symbol: `ToolManager.execute_tool`
  excerpt: |
    async def execute_tool(
        # === TOOL_CALL guardrail pipeline (FEAT-406) ===
        if self._tool_call_pipeline is not None and self._tool_call_pipeline.has_guardrails:
            from ..bots.guardrails.base import GuardrailContext, GuardrailStage
        # === End TOOL_CALL guardrail pipeline ===

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 1-14
  symbol: `PBACToolCallGuardrail`
  excerpt: |
    """PBACToolCallGuardrail — policy-driven tool-call denial (FEAT-406).
    Guard-chain position (resolved spec review Q8): this guardrail runs FIRST in
    ToolManager.execute_tool(), before GrantGuard/ConfirmationGuard — a
    policy-doomed call should never interrupt a human for confirmation or
    consume a grant.

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/`
  excerpt: |
    legacy_pipeline.py  moderation.py  pbac.py  prompt_injection.py  secrets.py

- path: `packages/ai-parrot/src/parrot/bots/guardrails/`
  excerpt: |
    $ grep -rniE "rate.?limit|max_calls|call_count|quota|budget" --include=*.py . | wc -l
    0

- path: `packages/ai-parrot/src/parrot/bots/guardrails/base.py`
  lines: 15-30
  symbol: `GuardrailStage`
  excerpt: |
    class GuardrailStage(str, Enum):
        TOOL_CALL: Before tool execution; intercepts the call before guards/body.
        TOOL_CALL = "tool_call"

## Notes

Spawned F008. Note the name collision trap: `parrot/tools/compression/budget.py` exists but is
a *latency* budget router for compression codecs, unrelated to tool-call counting.
