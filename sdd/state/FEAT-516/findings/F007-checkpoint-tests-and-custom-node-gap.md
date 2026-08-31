---
id: F007
query_id: Q008
type: read
intent: Locate tests for flow interruption, resume, idempotency, and repeated node execution.
executed_at: 2026-08-31T15:23:00+02:00
duration_ms: 175
parent_id: null
depth: 0
---

# F007 - Core tests prove node skipping but custom-flow resume is a known gap

## Summary

Core tests prove that resuming from a checkpoint does not execute completed nodes again and that a lease prevents concurrent resumes. A Thales integration test documents that custom nodes with live constructor dependencies cannot be reconstructed by the current `AgentsFlow.resume()` signature because it does not accept node factories. Dev-flow has the same custom-node shape.

## Citations

- path: `packages/ai-parrot/tests/flows/checkpoint/test_suspend_resume.py`
  lines: 173-207
  symbol: `test_resume_skips_completed_nodes`
  excerpt: |
    resumed = await AgentsFlow.resume(...)
    assert agents["agent1"].calls == 1
    assert agents["agent2"].calls == 2
- path: `packages/ai-parrot/tests/flows/checkpoint/test_suspend_resume.py`
  lines: 210-226
  symbol: `test_resume_locked_raises_flowlockederror`
  excerpt: |
    await fake_store.acquire_lease(flow_id, "other-holder", ttl=60)
    with pytest.raises(FlowLockedError):
- path: `packages/ai-parrot/tests/flows/thales/test_integration.py`
  lines: 164-190
  symbol: `TestCheckpointResume`
  excerpt: |
    AgentsFlow.resume has no node_factories parameter.
    Full AgentsFlow.resume support is reported as an open gap.

