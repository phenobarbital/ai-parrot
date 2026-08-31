---
id: F003
query_id: Q005
type: read
intent: Read dev_flow topology and materialization code to establish node reuse and routing contracts.
executed_at: 2026-08-31T15:19:00+02:00
duration_ms: 180
parent_id: null
depth: 0
---

# F003 - Dev builders do not enable per-run checkpointing

## Summary

The `dev_loop` and `dev_flow` builders instantiate `AgentsFlow` without checkpoint options. Their runners create a fresh `run_id` and `FlowContext`, but execute a shared `self.flow`; therefore the flow's auto-generated `flow_id` is not aligned with the job/run identity. Enabling checkpointing on the shared instance without changing ownership would mix concurrent or repeated jobs under one checkpoint key.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py`
  lines: 419-438
  symbol: `build_dev_loop_flow`
  excerpt: |
    run_id_holder: Dict[str, str] = {}
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow._run_id_holder = run_id_holder
- path: `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py`
  lines: 144-151
  symbol: `build_dev_flow`
  excerpt: |
    run_id_holder: dict[str, str] = {}
    flow = AgentsFlow(name=name, on_node_event=publisher)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
  lines: 1067-1115
  symbol: `DevLoopRunner.run`
  excerpt: |
    rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
    ...
    result = await self.flow.run_flow(ctx)
- path: `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py`
  lines: 94-154
  symbol: `DevFlowRunner.run`
  excerpt: |
    rid = run_id or f"run-{uuid.uuid4().hex[:8]}"
    ...
    result = await self.flow.run_flow(ctx)

