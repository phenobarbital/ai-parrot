---
id: FW-007
query_id: Q006
type: wiki_query
intent: "Orient: ConversationMemory report_usage callback - implemented or design only."
executed_at: 2026-10-30T22:39:51Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-007 — The compaction subsystem's usage hook is implemented as `budget.apply_usage`/`apply_commit`, not a `report_usage` callback

## Summary

The source asks whether `ConversationMemory.report_usage` is implemented or design-only. The
answer is: that name does not appear as the surface. FEAT-525 shipped
`memory/compaction/` with Stage 0.5 token counting (`TokenCounter`, `count_turn`) and
`memory/compaction/budget.py` carrying `MODEL_WINDOWS`, `resolve_window(model)`,
`build_default_budget(model, max_turns) -> ContextBudget`, an env kill switch, and **usage
calibration via `apply_usage` / `apply_commit`**. A prior proposal's finding (FEAT-778 F026)
records exactly this API.

Implication for the source's §"Research directives 1": the calibration hook is real but it is a
*context-window* calibration consumer, not a usage *store*. Subscribing a usage plane to it would
inherit a hook that only fires where compaction is active (bot conversations), never for the
dev-loop coder attempts, Claude Code, or Codex. It is the wrong seam.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 1-1
  symbol: `MODEL_WINDOWS` / `resolve_window` / `build_default_budget` / `apply_usage` / `apply_commit`
  excerpt: |
    # per sdd/state/FEAT-778/findings/F026-compaction-budget.md (score=0.27):
    # "memory/compaction/budget.py: MODEL_WINDOWS map, resolve_window(model),
    #  build_default_budget(model, max_turns) -> ContextBudget, env kill switch,
    #  usage calibration (apply_usage, apply_commit)"

- path: `packages/ai-parrot/src/parrot/memory/compaction/tokens.py`
  lines: 1-1
  symbol: `TokenCounter` / `count_turn`
  excerpt: |
    # "Stage 0.5 token counting for conversation turns (FEAT-525)."

- path: `packages/ai-parrot/src/parrot/memory/compaction/__init__.py`
  lines: 1-1
  symbol: package
  excerpt: |
    # "Per-turn conversation compaction (FEAT-525)."

- path: `packages/ai-parrot/src/parrot/memory/abstract.py`
  lines: 1-1
  symbol: `ConversationMemory`
  excerpt: |
    # the add_turn template method (TASK-2826: normalize -> count -> offload -> one write)

- path: `sdd/specs/per-turn-conversation-compaction.spec.md`
  lines: 1-1
  symbol: spec
  excerpt: |
    # FEAT-525 — Deterministic Stages (0 / 0.5 / 1)

## Notes

[cross-lane: type=grep, intent=grep -rn "report_usage" across packages/ to confirm the name is absent from the codebase entirely]
