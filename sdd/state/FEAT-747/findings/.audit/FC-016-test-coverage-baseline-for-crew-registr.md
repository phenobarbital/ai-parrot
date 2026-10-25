---
id: FC-016
query_id: Q042
type: glob
intent: "Existing tests for crew, registry, working memory and matrix — coverage baseline."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-016 — Test coverage baseline for crew, registry, working memory, matrix, a2a

## Summary

`find packages -path '*/tests/*' -name 'test_*.py'` filtered by crew/registry/working_memory/matrix/a2a (excluding build/): ~130 files. Matrix has the densest coverage (26 files in `ai-parrot-integrations/tests/test_matrix_*.py`: appservice, channels, compose, crew, delegation, handle_task, hook, registry_human, reply_to, session_models, session_tunnel, swarm_config, swarm_events, swarm_example, swarm_toolkit, transport, transport_collaborative, transport_swarm, tunnel, channel_delivery). Crew: `tests/test_crew_{sequential,parallel,loop,flow,final,tool_node,ask_prompt}_regression.py`, `tests/bots/flows/crew/*`. Registry: `tests/test_agent_registry_instances.py`, `tests/registry/test_capability_registry.py`, `tests/registry/test_registry_tooling_normalize.py`. Working memory: `tools/working_memory/tests/test_working_memory.py`, `tests/tools/working_memory/task_memory/*`. A2A: 20+ files across core and server.

## Citations

- path: `packages/ai-parrot-integrations/tests/test_matrix_swarm_toolkit.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    AgentSwarmToolkit tests

- path: `packages/ai-parrot-integrations/tests/test_matrix_tunnel.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    tunnel correlation/TTL tests

- path: `packages/ai-parrot-integrations/tests/test_matrix_delegation.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    HybridDelegator tests

- path: `packages/ai-parrot/tests/test_crew_sequential_regression.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    run_sequential regression

- path: `packages/ai-parrot/tests/test_agent_registry_instances.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    AgentRegistry instance lifecycle

- path: `packages/ai-parrot/tests/registry/test_capability_registry.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    CapabilityRegistry semantic search

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tests/test_working_memory.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    WorkingMemoryToolkit

- path: `packages/ai-parrot/tests/integration/events/test_a2a_trace_propagation.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    trace_id across A2A hop

- path: `packages/ai-parrot/tests/test_a2a_v1_mesh_router.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    A2A mesh router


## Notes

Note the `tools/working_memory/tests/` directory sits inside the *source* tree (FC-011 tree), unlike the other suites.
