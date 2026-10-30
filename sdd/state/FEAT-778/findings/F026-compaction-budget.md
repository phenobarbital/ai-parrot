---
id: F026
query_id: Q046
type: read
intent: "Memory compaction budget primitives (ContextBudget / MODEL_WINDOWS) the KnowledgeContext budget should reuse."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FC-027-compaction-budget]
---

# F026 — `memory/compaction/budget.py`: `MODEL_WINDOWS` map, `resolve_window(model)`, `build_default_budget(model, max_turns) -> ContextBudget`, env kill switch, usage calibration (`apply_usage`, `apply_commit`)

## Summary

188 lines (FEAT-525). Per-model context windows and a `ContextBudget` builder already exist, plus provider-reported-token calibration. A `KnowledgeContext.budget_tokens` derived "from the active model" (one of the source's options) can reuse `resolve_window`/`build_default_budget`; the per-layer quota and trim order would be new.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 43-61
  symbol: `MODEL_WINDOWS / resolve_window`
  excerpt: |
    MODEL_WINDOWS: Dict[str, int] = {
    def resolve_window(model: Optional[str]) -> int:

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 81-98
  symbol: `build_default_budget / compaction_disabled_by_env`
  excerpt: |
    def build_default_budget(model: Optional[str], *, max_turns: Optional[int] = None) -> ContextBudget:
    def compaction_disabled_by_env() -> bool:

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 111-167
  symbol: `apply_usage / apply_commit`
  excerpt: |
    def apply_usage(state: CompactionState, prompt_estimate: int, provider_prompt_tokens: Optional[int]) -> CompactionState:
    def apply_commit(state, commit: CompactionCommit, tokenizer: str, provider_prompt_tokens)

## Notes

Token counting lives in `memory/compaction/tokens.py` (Stage 0.5) — not read.
