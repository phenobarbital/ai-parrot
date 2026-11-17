---
id: F020
query_id: Q037
type: git_log
intent: "Recent history of the client layer - whether usage extraction was touched recently."
executed_at: 2026-10-30T22:40:00Z
duration_ms: 800
parent_id: null
depth: 0
lane: git
merged_from: ['FG-003']
---

# F020 — The client layer already carries cost_usd: FEAT-710 added it to clients/base.py on 2026-10-22

## Summary

25 commits in 90 days. Two campaigns matter and both contradict the
brainstorm's premises. **FEAT-710 parrot-telemetry-event-fanout** (merged
2026-10-22) added `tenant` and `cost_usd` directly to client lifecycle events
in `clients/base.py` (22ff749388), then backfilled `usage.estimated_cost` from
that origin cost (9b08af6b61) — i.e. the client layer *already* emits a priced
usage event. **FEAT-550 token-budget-bedrock** (TASK-3133→3143, 2026-09-11/12)
built `parrot.clients.budget` as a "QuestionBudget Atomic Ledger" with
`BudgetScope`, `BudgetRegistry`, suspension nonces, an AbstractClient budget
gate, and "observational reserve semantics and settled-estimate reporting"
(`clients/budget.py`, d5bc35c02e). So the client layer has both a *token
accounting ledger* and a *cost figure*, neither of which the brainstorm's
"Current state" section mentions. The brainstorm's line "`AbstractClient`
already extracts provider usage per completion" is true but a large
understatement of what is built.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  symbol: `AfterClientCallEvent cost_usd`
  excerpt: |
    9b08af6b61|2026-10-22|feat(parrot-telemetry-event-fanout): TASK-4548 — backfill
                           usage.estimated_cost from the origin cost (AC-3)   -> clients/base.py
    22ff749388|2026-10-22|feat(parrot-telemetry-event-fanout): TASK-4548 — tenant and
                           cost_usd on client events                          -> clients/base.py

- path: `packages/ai-parrot/src/parrot/clients/budget.py`
  symbol: `QuestionBudget / BudgetScope / BudgetRegistry`
  excerpt: |
    d5bc35c02e|2026-09-12|feat(bedrock-token-telemetry): TASK-3186 — Observational reserve
                           semantics and settled-estimate reporting  -> clients/budget.py
    af771d19d8|2026-09-11|feat(token-budget-bedrock): TASK-3133 — QuestionBudget Atomic Ledger
                           and parrot.clients.budget ...
    9502e9e2d6|2026-09-11|feat(token-budget-bedrock): TASK-3134 — BudgetScope, BudgetRegistry,
                           Suspension Nonces and Snapshots
    d9abaf495d|2026-09-11|feat(token-budget-bedrock): TASK-3136 — AbstractClient Budget Gate implementation
    0268092ca8|2026-09-12|feat(token-budget): TASK-3187 — Keep the ordinary SDK client view in the
                           budgeted funnel under observe mode  -> clients/openai_base.py

- path: `packages/ai-parrot/src/parrot/clients/openai_base.py`
  symbol: `invoke() lifecycle telemetry`
  excerpt: |
    1eda9fb6f3|2026-09-19|feat(invoke-telemetry): TASK-3478 — OpenAIBaseClient.invoke()
                           lifecycle telemetry
    08655037b1|2026-10-30|feat(openai-client-fixes): TASK-4894 — adapt OpenAI completion params
    823d5e9a88|2026-10-30|fix(ci): register ai-parrot-squawk and fix two stale OpenAI client tests

## Notes

`clients/base.py` is otherwise quiet (4 commits/90d) — unlike `sdd_coder/engine.py`,
it is a safe file to extend, which matters because CLAUDE.md forbids modifying
`clients/base.py` without discussion.

[cross-lane: type=read, intent=read clients/budget.py and the AbstractClient budget gate — an existing token ledger the usage plane may be able to subscribe to rather than duplicate]
[cross-lane: type=grep, intent=locate CompletionUsage / estimated_cost on AIMessage to see which of the four token counters actually survive today]
