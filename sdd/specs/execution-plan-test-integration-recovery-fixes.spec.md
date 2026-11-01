---
type: feature
base_branch: dev
feature_id: FEAT-789
projects: [ai-parrot]
tags: [execution-plan, recovery, working-memory, bugfix, ledger]
discovered_from: issue:ca325f05ae53
---
# FEAT-789 — Plan node writes lose their version outside a turn session

**Status**: approved · **Parent**: FEAT-585 (plan-then-execute-hardening, merged) · **Issue**: `issue:ca325f05ae53`

## Problem
`test_fresh_process_recovery_chain` fails on a clean `dev` checkout: the resumed run ends `partial`,
node `c` failing with `"'b_out' not found. Available: []"`.

Root cause (reproduced 2026-11-02): `PlanToolNode._store` (`bots/flows/plan/node.py`) writes a
versioned artifact only when a `TurnTaskSession` is bound **and** the attempt has a producer receipt.
A plan dispatched by `ExecutionPlanToolkit` runs in a background task with no turn session, so every
write takes the "legacy" branch — `working_memory.store_result(...)`, which with an enabled catalog
*does* call `catalog.aput_generic` and create a version — and then returns `_Written(..., None, ...)`,
discarding that version. Checkpoint `ArtifactRef.versions` is therefore always `[]`,
`PlanMemoryBinding.restore` restores nothing, and a fresh process cannot read `b_out`.

The FEAT-585 spec (§2, "Use a toolkit-local PlanWorkingMemoryCatalog … Resolve the exact EvidenceRef
from checkpoint ArtifactRef.versions"; Known Risks: "PlanToolNode already uses aput_generic") assumes
plan-node writes are versioned whenever task memory is enabled. The code does not meet that.

## Design
- **M1.** In `PlanToolNode._store`, when the catalog is enabled but no session/producer is available,
  write through `catalog.aput_generic(key, payload, description=..., metadata=...)` directly and return
  the resulting `artifact_id@version` evidence string (built with the existing `_evidence_ref`).
  Provenance is not invented: no `producer_call_id`/`attribution` is passed, and `degraded` keeps its
  current value (`False`) for this branch.
- The disabled-catalog branch (`catalog is None`) stays byte-identical: `working_memory.store_result`.
- The session+producer branch (`_store_versioned`) is unchanged.

## Acceptance Criteria
- [ ] AC-1 `test_fresh_process_recovery_chain` passes: the resumed run is `completed` and only `c` is dispatched.
- [ ] AC-2 With an enabled catalog and no turn session, a plan node's `ArtifactRef.versions` holds one `artifact_id@version` per stored key.
- [ ] AC-3 With task memory disabled, the write path and `ArtifactRef.versions == []` are unchanged.
- [ ] AC-4 `packages/ai-parrot/tests/tools/execution_plan/` and `packages/ai-parrot/tests/bots/flows/plan/` (if present) stay green.

## Out of scope
Opening a turn session for background plan runs (receipt/attribution tracking); the
`@pytest.mark.asyncio`-on-sync-function warning in the same test file.
