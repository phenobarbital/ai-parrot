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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Extended `docs/orchestration/agentsflow.md` with a "State
Checkpointing & Resume" section (placed before "See Also", matching the
existing doc's structure) covering every required item: two-tier design
table, opt-in constructor kwargs (with the `FlowMetadata` block +
constructor-wins precedence), the three durable triggers (write-through/
suspend-dump/graceful-shutdown with the `attach_to_app()` snippet),
`resume()`/re-fork semantics, `to_definition()` + the `NODE_REGISTRY`
requirement, the idempotency caveat and lossy-checkpoint behavior as
explicitly flagged `⚠️` call-outs (both are spec §7 acceptance-criteria
items, not optional footnotes), the `FLOW_CHECKPOINT_*` env var table,
and the HTTP ops endpoint table with the 409/404 mappings. Verified
every code snippet's imports/API calls against the LANDED
implementation (not the spec) by actually running them in a Python
REPL: `from parrot.bots.flows import AgentsFlow`,
`from parrot.bots.flows.core.checkpoint.recovery import
get_recovery_service`, `from parrot.bots.flows.core.checkpoint.errors
import FlowLockedError, CheckpointNotFoundError,
FlowNotExportableError`, and confirmed `AgentsFlow.resume`/`.suspend`/
`.to_definition` all exist.

Created `examples/flow/agentsflow_checkpointing.py` matching
`agentsflow_standalone.py`'s style/structure (module docstring, `USE_LLM`-
style header comment, `EXAMPLE N` sections, a `main()` with a try/except
that prints a helpful hint on failure). Two runnable scenarios: (1) kill-
and-resume — run a 3-node linear flow with `checkpoint=True`, then call
`AgentsFlow.resume()` on a **fresh** `AgentsFlow` instance (no reference
to the original), with per-node call counters proving zero re-execution;
(2) re-fork from the checkpoint written right after the first node,
proving the downstream nodes re-run while the upstream one doesn't. Uses
a lightweight `CountingAgent`/`StaticRegistry` stub (not `BasicAgent`) so
the example needs **no LLM API key** — only a local Redis, matching the
task's "must run without Postgres/Mongo" constraint literally (Redis
only) while keeping it fully self-contained. A third, uncalled
`_durable_tier_and_shutdown_snippet()` function (marked `# pragma: no
cover - docs only`) shows the `durable=True` + `DurableCheckpointStore`
+ `FlowRecoveryService.attach_to_app()` wiring as copy-pasteable
reference, with an inline comment on swapping `driver="sqlite"` for
`"postgres"`/`"mongodb"`.

**Verified end-to-end against a real throwaway Redis** (`docker run
redis:7-alpine`), not just import-checked: both examples ran cleanly,
printed the expected call counts (`researcher=1, writer=1, editor=1`
after resume; `researcher=1, writer=2, editor=2` after re-fork,
confirming only downstream nodes re-ran), and the `lossy` warning fired
correctly (the `Response` stub class isn't a registered Pydantic type,
so `FlowStateSerializer` degrades it to a tagged repr as designed —
this is the CORRECT documented behavior, not a bug). `ruff check`
clean.

**Deviations from spec**: none.
