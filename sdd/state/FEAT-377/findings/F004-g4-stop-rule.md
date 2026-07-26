---
id: F004
query: "G4 — Explicit stop rule for parallelism"
type: code_review
verdict: PARTIALLY_TRUE
---

## G4: Stop rule — partially explicit

**Verdict: PARTIALLY_TRUE**

### Evidence supporting the claim

1. **`agent_builder.py:204-232`** — `DEV_LOOP_DEV_AGENTS` is a static JSON
   env var. Configuration, not a dynamic decision.

2. **`development.py:123-133`** — pool-vs-single decision is purely config:
   if `pool_cfg is None`, falls back to single-agent. No runtime analysis.

### Evidence partially refuting

3. **`task_scheduler.py:166-182`** (`next_wave()`) IS a dynamic policy:
   returns only tasks whose dependencies are satisfied. Kahn's algorithm
   for cycle detection + topological ordering. Fan-out degree per wave
   is determined by the dependency graph, not just configuration.

4. **`development.py:235-340`** — pool iterates `while True: wave = scheduler.next_wave()`,
   so actual concurrency is dynamically bounded by task dependencies.

### Gap

The decision to USE a pool at all (fan-out vs sequential) remains static.
A small deterministic policy in `_resolve_pool_config` could automate this.
