---
id: F008
query_id: Q008
type: read
intent: Verify WorkingMemory store_result and ArtifactRef integration
executed_at: 2026-09-21T22:12:00Z
depth: 0
parent_id: null
---

# F008 — WorkingMemoryToolkit.store_result exists

## Summary

`WorkingMemoryToolkit.store_result` in `tools/working_memory/tool.py` stores intermediate results (text, dict, list, AIMessage, bytes). `InMemoryArtifactStore` and `SpillHandler.spill` provide durable storage. `ArtifactRef` is the published value in FlowContext — payloads go to working memory, only refs travel through the flow. The delegate node's post-dispatch path (`wm.store_result(key) -> ArtifactRef`) is identical to PlanToolNode's.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit.store_result`
  excerpt: |
    def store_result(self, ...):
        """Store any intermediate result (text, dict, list, AIMessage, bytes, etc.)"""

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/artifacts.py`
  symbol: `InMemoryArtifactStore`
  excerpt: |
    class InMemoryArtifactStore:
        """Initialize an empty store."""

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/artifacts.py`
  symbol: `SpillHandler.spill`
  excerpt: |
    def spill(self, ...):
        """Write a value to durable storage and return its reference."""

## Notes

The proposal's dispatch-to-store pipeline is: `delegate.propose_call() -> validate -> ToolManager.execute_tool() -> wm.store_result(key) -> ArtifactRef`. This is the same as PlanToolNode's `_call_with_retry() -> _store()` pipeline. The delegate can reuse this path wholesale.
