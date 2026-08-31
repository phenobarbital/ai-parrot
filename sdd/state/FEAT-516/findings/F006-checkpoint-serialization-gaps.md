---
id: F006
query_id: Q003
type: read
intent: Read the AgentsFlow executor to identify lifecycle hooks and safe cache interception points.
executed_at: 2026-08-31T15:22:00+02:00
duration_ms: 190
parent_id: null
depth: 0
---

# F006 - Current generic serialization cannot faithfully restore dev shared state

## Summary

Checkpoint results use `FlowStateSerializer`, but only `AIMessage` is registered by default; unregistered Pydantic models degrade to strings. `ResearchOutput` and `DevelopmentOutput` are not registered. `FlowContext.to_snapshot` copies `shared_data` directly even though dev runners place Pydantic briefs and a live `SessionHost` in it, and `AgentsFlow.resume` restores that dict without rebinding live objects.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py`
  lines: 61-79
  symbol: `FlowStateSerializer.__init__`
  excerpt: |
    self._registry: dict[str, type[BaseModel]] = {}
    self.register(AIMessage)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py`
  lines: 123-137
  symbol: `FlowStateSerializer._encode_value`
  excerpt: |
    if isinstance(value, BaseModel):
        ...
        return {"__type__": "lossy", "__repr__": repr(value)}
- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 298-320
  symbol: `FlowContext.to_snapshot`
  excerpt: |
    results_safe, results_lossy = serializer.to_safe_with_meta(self.results)
    ...
    shared_data=dict(self.shared_data)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py`
  lines: 1080-1085
  symbol: `DevLoopRunner.run`
  excerpt: |
    "bug_brief": brief,
    "run_id": rid,
    "session_host": host,

