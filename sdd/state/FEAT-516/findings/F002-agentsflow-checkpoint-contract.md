---
id: F002
query_id: Q002
type: read
intent: Locate existing cache, checkpoint, resume, and persistence abstractions in flow execution code.
executed_at: 2026-08-31T15:18:00+02:00
duration_ms: 250
parent_id: null
depth: 0
---

# F002 - AgentsFlow already checkpoints completed nodes

## Summary

`AgentsFlow` has opt-in, event-driven checkpointing. A resume seeds `FlowContext.completed_tasks`, `results`, and completion order from a checkpoint; the scheduler skips completed nodes and reruns only in-flight, failed, or never-started nodes, giving at-least-once behavior at the node boundary. Redis is the default checkpoint store, with TTL, bounded history, and a per-flow resume lease.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 242-277
  symbol: `AgentsFlow.__init__`
  excerpt: |
    checkpoint: bool = False
    checkpoint_store: Optional[Union[str, CheckpointStore]] = None
    flow_id: Optional[str] = None
- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 1426-1452
  symbol: `AgentsFlow.resume`
  excerpt: |
    for node_id in checkpoint.context.completion_order:
        seed_ctx.mark_completed(node_id, result=decoded_results.get(node_id))
- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 1505-1517
  symbol: `AgentsFlow._run_flow_scheduler`
  excerpt: |
    completed: set[str] = set(ctx.completed_tasks)
    results: dict[str, Any] = dict(ctx.results)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/redis.py`
  lines: 37-61
  symbol: `RedisCheckpointStore`
  excerpt: |
    flowckpt:{flow_id}:latest
    flowckpt:{flow_id}:cp:{checkpoint_id}
    flowckpt:{flow_id}:history

