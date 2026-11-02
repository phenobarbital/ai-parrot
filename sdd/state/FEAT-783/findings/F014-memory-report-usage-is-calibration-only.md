---
id: F014
query_id: Q028
type: grep
intent: "Confirm whether report_usage exists in the memory/compaction subsystem or is design-only."
executed_at: 2026-10-30T23:06:00Z
duration_ms: 300
parent_id: null
depth: 0
lane: codebase
merged_from: ['FC-014', 'FW-007']
---

# F014 — CONFIRMED: `ConversationMemory.report_usage` is implemented, and it is a calibration hook — not a usage store

## Summary

The source asks whether `report_usage` is "implemented or still design". It is
**implemented** at `memory/abstract.py:561-593`, with a test at
`tests/unit/memory/compaction/test_memory_template.py:240`. Its contract confirms the
source's own caveat exactly: it "fold[s] one (estimate, provider) observation into the
calibration state, **without writing a turn**", taking `estimated_prompt_tokens` and
`provider_prompt_tokens` and merging them through `apply_usage` into a `CompactionState`
stored under `history.metadata["compaction"]`.

It is therefore unusable as a usage source for a per-spec plane: it keeps only *prompt*
tokens (no output, no cache), it stores a rolling calibration state rather than records, it
is keyed by `(user_id, session_id, chatbot_id)` with no `feat_id`/`task_id`, and the whole
value is overwritten on each call. The source's instinct ("a calibration hook, not a usage
store") is right; the correct conclusion is that the usage plane should **not** subscribe to
it, and should use `AfterClientCallEvent`/`UsageRecord` instead (FC-007).

## Citations

- path: `packages/ai-parrot/src/parrot/memory/abstract.py`
  lines: 561-575
  symbol: `ConversationMemory.report_usage`
  excerpt: |
    async def report_usage(
        self, user_id: str, session_id: str, *,
        estimated_prompt_tokens: int,
        provider_prompt_tokens: Optional[int],
        chatbot_id: Optional[str] = None,
    ) -> None:
        """Fold one (estimate, provider) observation into the calibration state, without writing a turn.

- path: `packages/ai-parrot/src/parrot/memory/abstract.py`
  lines: 586-593
  symbol: `report_usage` body
  excerpt: |
    history = await self.get_history(user_id, session_id, chatbot_id)
    if history is None:
        return
    prev = history.metadata.get("compaction")
    state = CompactionState.from_dict(prev) if prev else CompactionState(tokenizer=self.token_counter.name)
    state = apply_usage(state, estimated_prompt_tokens, provider_prompt_tokens)
    history.metadata["compaction"] = state.to_dict()
    await self.update_history(history)

- path: `packages/ai-parrot/tests/unit/memory/compaction/test_memory_template.py`
  lines: 240-243
  symbol: `test_report_usage_updates_calibration_without_writing_turn`
  excerpt: |
    async def test_report_usage_updates_calibration_without_writing_turn():
        ...
        await m.report_usage("u", "s", estimated_prompt_tokens=100, provider_prompt_tokens=150, chatbot_id="bot")

- path: `packages/ai-parrot/src/parrot/memory/compaction/budget.py`
  lines: 6
  symbol: `module docstring`
  excerpt: |
    (TASK-2826) and ``report_usage`` use.

## Notes

- `token_counter` is pluggable per memory instance (`abstract.py:351-387`, default from
  `get_default_counter()`), so "estimated" tokens are tokenizer-dependent and not
  comparable across agents without recording the tokenizer name — `CompactionState` does
  store `tokenizer=`, which a reconciliation report would need to carry.


---

## Merged from FW-007 (wiki lane)

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
