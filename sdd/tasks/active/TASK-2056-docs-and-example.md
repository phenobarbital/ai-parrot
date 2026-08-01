# TASK-2056: Documentation + runnable checkpointing example

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2053, TASK-2054, TASK-2055
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 — user-facing documentation of the two-tier design and a
runnable example, closing the feature's acceptance criteria.

---

## Scope

- Extend `docs/orchestration/agentsflow.md` with a "State Checkpointing &
  Resume" section covering:
  - Opt-in usage (`checkpoint=True`, retention/history defaults 24h/10,
    `checkpoint_include_responses`, `durable=True` write-through).
  - The two tiers (Redis ephemeral vs. durable sqlite/pg/mongo) and the
    three durable triggers (suspend/dump API, write-through, shutdown hook).
  - `suspend()` / `resume()` / re-fork from a historical checkpoint.
  - `to_definition()` and the `NODE_REGISTRY` requirement for programmatic flows.
  - **Idempotency caveat** (at-least-once per node) and lossy-checkpoint
    behavior (spec §7 — must be documented, it's an acceptance criterion).
  - `FLOW_CHECKPOINT_*` env vars table.
  - HTTP ops endpoints.
- Create `examples/flow/agentsflow_checkpointing.py`: a small declarative
  flow that checkpoints to Redis, is interrupted, and resumes — mirroring
  the style of the existing `examples/flow/agentsflow_standalone.py`.

**NOT in scope**: code changes to `parrot/` (docs-only task; if you find a
bug, file it in the completion note — do not fix inline).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/orchestration/agentsflow.md` | MODIFY | Checkpointing & resume section |
| `examples/flow/agentsflow_checkpointing.py` | CREATE | Runnable example |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All public API from prior tasks — verify each against the LANDED code, not the spec:
from parrot.bots.flows.flow.flow import AgentsFlow          # flow/flow.py:159
from parrot.bots.flows.core.checkpoint import FlowCheckpointer, FlowStateSerializer  # TASK-2051/2047
from parrot.bots.flows.core.checkpoint.store.factory import get_checkpoint_store     # TASK-2048
```

### Existing Signatures to Use
- Document ONLY the signatures as actually implemented by TASK-2046..2055 —
  read the landed modules first; where the implementation deviated from the
  spec (check their completion notes), the implementation wins.
- Example style reference: `examples/flow/agentsflow_standalone.py` (exists —
  indexed in the repo knowledge graph).

### Does NOT Exist
- ~~Auto-resume-on-startup~~ — do NOT document it (spec Non-Goal).
- ~~AgentCrew checkpointing~~ — phase 2; mention only as "coming later" if at all.
- ~~`msgpack`~~ — the dependency is `ormsgpack`.

---

## Implementation Notes

### Key Constraints
- Follow the structure/tone of the existing AgentsFlow user guide
  (`docs/orchestration/agentsflow.md`, created by TASK-1601).
- The example must run without Postgres/Mongo — Redis only, with a clear
  comment on how to switch the durable store.
- Include the shutdown-hook snippet (`FlowRecoveryService.attach_to_app`).

---

## Acceptance Criteria

- [ ] Docs section covers: opt-in, two tiers, three durable triggers, resume/re-fork, export, idempotency caveat, lossy behavior, env vars, HTTP endpoints.
- [ ] `python examples/flow/agentsflow_checkpointing.py` runs against local Redis (document the requirement at the top of the file).
- [ ] Every code snippet in the docs imports/calls only APIs that exist in the landed implementation.
- [ ] `ruff check examples/flow/agentsflow_checkpointing.py` clean.

---

## Test Specification

```python
# No new test files. Verification is:
#   1. Run the example end-to-end against local Redis.
#   2. Doc snippets validated by importing the referenced names in a REPL/pytest collect.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2053/2054/2055 in `tasks/completed/` (read their completion notes for deviations)
3. **Verify the Codebase Contract** — the LANDED code is the source of truth for every documented signature
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
