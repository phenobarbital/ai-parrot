---
id: F026
query_id: Q004
type: wiki_query
intent: "Orient: clients/budget.py and budget_scope.py - possible existing token accounting the plane could reuse."
executed_at: 2026-10-30T22:39:51Z
duration_ms: 0
parent_id: null
depth: 1
lane: wiki
merged_from: ['FW-006']
---

# F026 — `parrot.clients.budget` (FEAT-550) is an atomic token ledger with `BudgetScope`/`BudgetRegistry`, already bound around the sdd-coder turn loop

## Summary

`clients/budget.py` and `clients/budget_scope.py` implement FEAT-550's `QuestionBudget` atomic
ledger plus `BudgetScope`, `BudgetRegistry`, suspension nonces and snapshot transfer. It is not a
passive counter: it enforces, raises `BudgetError` through tools / ToolManager / model switching,
and has a documented `observe` vs enforce mode. TASK-3190 ("Bind one observational budget scope
around the turn loop") wired it into the dev-loop, which is why `AttemptUsageRow` (FW-002) carries
`ledger_input_tokens`, `ledger_settled_estimate_input_tokens`, `ledger_uncertain_tokens`,
`ledger_overrun_tokens`, `ledger_counting_methods` and `enforcement: str = "observe"`.

This directly answers the source's open question "Should `sdd-worker` read the plane mid-run to
enforce a per-spec token budget, or is reporting enough for v1?" — a mid-run enforcement mechanism
already exists at the client layer; what it lacks is a *per-spec* scope, not an enforcement path.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/budget.py`
  lines: 1-1
  symbol: `parrot.clients.budget` entry module
  excerpt: |
    # TASK-3133: "QuestionBudget Atomic Ledger and parrot.clients.budget Entry Module"

- path: `packages/ai-parrot/src/parrot/clients/budget_scope.py`
  lines: 1-1
  symbol: `BudgetScope` / `BudgetRegistry`
  excerpt: |
    # TASK-3134: "BudgetScope, BudgetRegistry, Suspension Nonces and Snapshot Transfer"

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 65-71
  symbol: `AttemptUsageRow` ledger counters
  excerpt: |
    ledger_settled_estimate_input_tokens: Optional[int] = None
    ledger_released_estimate_tokens: Optional[int] = None
    ledger_uncertain_tokens: Optional[int] = None
    ledger_overrun_tokens: Optional[int] = None
    ledger_counting_methods: List[str] = Field(default_factory=list)
    enforcement: str = Field("observe", max_length=16)

- path: `packages/ai-parrot/tests/unit/clients/test_token_budget.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-550 M1 — policy validation and record semantics (spec §4 'Policy validation')."

- path: `packages/ai-parrot/tests/unit/clients/test_token_budget_scope.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-550 M2 — resume/snapshot and registry lifecycle"

- path: `packages/ai-parrot/tests/unit/tools/test_token_budget_propagation.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-550 M3 — BudgetError propagation through tools, manager and model switching"

- path: `sdd/specs/token-budget-bedrock.spec.md`
  lines: 1-1
  symbol: spec
  excerpt: |
    # FEAT-550 — the governing spec for this subsystem

## Notes

Known defect in this area: `issue:8d6136b63a8c` — "test_disabled_binds_no_scope reads ambient
DEV_LOOP_CODER_TELEMETRY instead of pinning it", which confirms that the budget scope binding and
the telemetry sink share the `DEV_LOOP_CODER_TELEMETRY` switch noted in FW-002.

[cross-lane: type=read, intent=Read clients/budget_scope.py to find whether a scope carries an arbitrary label that could hold feat_id/task_id]
