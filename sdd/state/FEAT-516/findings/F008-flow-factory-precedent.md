---
id: F008
query_id: Q010
type: git_log
intent: Inspect recent history for design decisions affecting dev_flow, dev_loop, and AgentsFlow persistence.
executed_at: 2026-08-31T15:24:00+02:00
duration_ms: 95
parent_id: null
depth: 0
---

# F008 - Another branch contains a tested flow-factory resume design

## Summary

Commit `8d7657b23` is present in repository history but is not an ancestor of current `HEAD` (`cc6695747`). It adds `AgentsFlow.resume(flow_factory=...)` specifically to rebuild custom explicit-edge flows with live dependencies and correct routing, validates completed node IDs, and adds process-wide checkpoint type registration. This is strong precedent to port or adapt, not current-branch functionality.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 1333-1453
  symbol: `AgentsFlow.resume`
  excerpt: |
    Current branch reconstructs with cls.from_definition(...)
    and exposes no flow_factory argument.
- commit: `8d7657b23f1fa7fe678d6087757a0289a3a6f248`
  date: 2026-08-30
  author: Claude
  message: `core+saas(T18): resume a flow whose graph the caller built`
  files_touched:
    - `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
    - `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py`
    - `packages/ai-parrot/tests/flows/checkpoint/test_resume_flow_factory.py`

## Notes

The commit explains three failure modes: missing live dependencies, loss of explicit-edge semantics, and typed results degrading during checkpoint serialization.

