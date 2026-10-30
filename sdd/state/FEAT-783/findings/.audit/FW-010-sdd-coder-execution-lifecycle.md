---
id: FW-010
query_id: Q002
type: wiki_query
intent: "Orient: the sdd_coder execution lifecycle between coder_begin_execution and coder_end_execution."
executed_at: 2026-10-30T22:41:09Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-010 — The execution lifecycle is owned by `SddCoderEngine` + `ExecutionPool`; `execution_id` was retrofitted by FEAT-559 and is empty on historical records

## Summary

`begin_execution` / `end_execution` live on `SddCoderEngine`
(`flows/dev_loop/sdd_coder/engine.py`) over an `ExecutionPool` (`pool.py`), with persistence and
restart recovery (TASK-3282) and an MCP protocol surface (TASK-3283). `execution_id` is a **later
addition (FEAT-559)**: both `AttemptUsageRow.execution_id` and `OutcomeRow.execution_id` document
"Empty for historical records", so the source's correlation key is not uniformly populated across
existing data and a usage plane must treat `execution_id` as optional.

The engine is also actively churning and has known defects at precisely the boundary a usage
ingestor would hook: `end_execution` settlement, job closure, and attempt outcome.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 1-1
  symbol: `SddCoderEngine.begin_execution` / `.end_execution` / `.run_chunk` / `._select_retry_seat` / `._classify_and_suspend`

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py`
  lines: 1-1
  symbol: `ExecutionPool` / `_effective_key`

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 73-75
  symbol: `AttemptUsageRow.execution_id`
  excerpt: |
    execution_id: str = Field("", max_length=64)
    """FEAT-559: the execution this attempt ran under. Empty for historical records."""

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`
  lines: 91-93
  symbol: `OutcomeRow.execution_id`
  excerpt: |
    execution_id: str = Field("", max_length=64)
    """FEAT-559: the execution this outcome belongs to. Empty for historical records."""

- path: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "Integration tests for execution snapshot persistence and restart recovery (TASK-3282)."

- path: `sdd/tasks/completed/TASK-3283-coder-pool-mcp-protocol.md`
  lines: 1-1
  symbol: MCP surface
  excerpt: |
    TASK-3283: Expose execution lifecycle and suspension tools through MCP

- path: `sdd/tasks/completed/TASK-3278-coder-execution-attribution.md`
  lines: 1-1
  symbol: prior attribution work
  excerpt: |
    TASK-3278: Add execution attribution to telemetry and review history

- path: `sdd/tasks/completed/TASK-3193-engine-telemetry-wiring.md`
  lines: 1-1
  symbol: prior telemetry wiring (score=0.91)
  excerpt: |
    TASK-3193: Wire attempt identity, telemetry capture and outcome events into the engine

## Notes

Open defects at the ingest boundary the source proposes to use:
- `issue:cc372f700a47` — "review_checkpoint prepare: stale outstanding_job_ids blocks settlement
  despite `coder_end_execution` reporting closed". `end_execution` is not a reliable "everything
  finished" signal today.
- `issue:ee4d4879fc89` — "sdd-coder engine reports outcome=merged with 0 commits/0 changed files".
- `issue:700660c7f663` — "engine.py reaches into ExecutionPool private state from multiple methods
  instead of its public API", across `begin_execution`/`suspend_model`/`_select_retry_seat`/
  `_classify_and_suspend` — adding a usage hook here widens an already-flagged encapsulation break.

[cross-lane: type=grep, intent=Locate the exact coder_end_execution body in engine.py and whether an AttemptRecord with provider token fields is in scope there]
