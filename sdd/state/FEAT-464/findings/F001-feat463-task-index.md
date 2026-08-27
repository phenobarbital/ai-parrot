# F001: FEAT-463 Task Index and Status

**Query**: wiki_query "matrix swarm agent integration"
**Source**: sdd/tasks/index/matrix-agents-swarm.json

## Key Facts

FEAT-463 (matrix-agents-swarm) is the core feature with 10 tasks (TASK-2478 through TASK-2487), all status: "in-progress" (started_at: 2026-08-25). Spec: sdd/specs/matrix-agents-swarm.spec.md (status: approved).

### Task Dependency Chain

```
TASK-2478 (Config & Event Models) — foundation, no deps
  → TASK-2479 (AppService Room Primitives) — depends 2478
    → TASK-2480 (Channel Manager) — depends 2478, 2479
      → TASK-2481 (Tunnel Registry) — depends 2478-2480
        → TASK-2482 (Inbound Task Handler) — depends 2478, 2481
          → TASK-2483 (AgentSwarmToolkit) — depends 2480-2482
            → TASK-2484 (Transport Wiring) — depends 2480-2483
              → TASK-2485 (Session Cross-Pollination) — depends 2481, 2484
                → TASK-2487 (Docs/Examples) — depends 2485, 2486

TASK-2486 (Docker Dev Stack) — parallel=true, no deps
```

### Implication for FEAT-464

FEAT-464 sample depends on FEAT-463 completion. All 10 tasks are "in-progress" but none completed yet. The sample must be built AFTER core modules exist, or designed to work incrementally.
