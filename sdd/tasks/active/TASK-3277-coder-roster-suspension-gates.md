# TASK-3277: Gate primary and fallback probes by exact model identity

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-3275
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3275 for structured probe metadata. Parallel with TASK-3276 and TASK-3278; owns roster.py/test_roster.py only and preserves the recently landed exclusive scheduling behavior.

## Context

Implements M3 roster wiring; §2 model identity and probe failure policy. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Add an explicit excluded ModelKey set to probe and check it before each primary/fallback smoke call. Preserve static credential/binary checks and existing smoke deadlines.

- Exclude empty MCP model IDs with model_identity_required before a paid call. Normalize native default identity to native/haiku; do not invent MCP provider defaults.

- Return structured per-model probe failures using TASK-3275 metadata, including a failed primary when a fallback succeeds. Static host/config unavailability is not fabricated as a failed smoke invocation.

- Use distinct effective ModelKeys for chunk assignment/retry eligibility so aliases cannot double-book or escape exclusions; preserve roster order, rotation and exclusive-task semantics.

- Do not persist here: the engine adds execution-bound probe incidents and durably records them in TASK-3279.

**NOT in scope**: Ledger writes, engine begin/dispatch wiring and modifications to dispatcher implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py` | MODIFY | Exclusion-aware probing and distinct-model assignment |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` | MODIFY | Probe gates, aliases, fallback and exclusive-chunk regressions |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe, available_seats, ChunkAssigner
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, SeatProbeResult
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:35` — async RosterProbe.probe(roster) -> List[SeatProbeResult] currently visits every configured seat.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:50` — _probe_one checks static readiness, then optional primary/fallback smoke; results currently lose failed-primary evidence after successful fallback.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:115` — available_seats copies configured seats with model_used; ChunkAssigner.assign at 134 preserves exclusive tasks alone/first.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py:66` — test_probe_switches_to_fallback_model uses injected smoke; test_assign_exclusive_tasks_run_alone_and_first at 86 protects current scheduling behavior.

### Does NOT Exist

- Current RosterProbe has no exclusion parameter and no structured failed-primary history.

- No new provider health integration, global ban or automatic cooldown test call is authorized.

New symbols mentioned below are target declarations, not claims about existing APIs. Dependency-produced symbols
must be verified in the feature worktree before import. Never guess a replacement when a contract has changed.

## Implementation Notes

- Python implementations use Pydantic v2 and existing dependencies; no provider SDK or dependency additions.
- Preserve concurrent lint, feedback and exclusive-task scheduling work; do not weaken those gates.
- Run filesystem/ledger work off the event loop. Tests use isolated temporary repositories and no live providers.
- Operational suspension is separate from reviewed code feedback; lint, polling deadlines, cancellation and host
  Git failures do not become model lessons or automatically model suspensions.
- This task has no Delegation Contract: the blueprint fixes boundaries, but complete verified implementation
  blocks are not supplied. Use the normal reasoning-capable implementation route, not a mechanical writer packet.

## Implementation Blueprint

### Steps (in order)

1. Extend probe(roster, *, excluded) and propagate the exclusion set into primary and fallback decisions. Retain configured and effective identity in results.

2. Check the configured fallback independently even when primary is excluded; never pass an excluded ID to smoke. Deduplicate alias probes within the begin call rather than repeatedly probing a newly failed key.

3. Capture actual smoke failure UID/time/duration/exception class at the exception/result boundary; no stderr/prose parsing and no raw exception content in durable metadata.

4. Make assignment operate on effective unique model candidates and preserve exclusive batches. Retry selection must remain MCP-only; the pool owns busy reservations.

5. Update the roster test helper to use explicit synthetic model IDs and assert zero smoke invocations for excluded or unknown identities.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
async RosterProbe.probe(roster: RosterConfig, *, excluded: set[ModelKey]) -> list[SeatProbeResult]
available_seats(roster: RosterConfig, results: list[SeatProbeResult]) -> list[RosterSeat]
```

### Bounded implementation checklist

- [ ] Excluded primary/fallback IDs and their aliases cause zero calls; an independently healthy configured fallback remains eligible.

- [ ] One model failure does not ban other models of the same backend.

- [ ] A smoke timeout generates typed failure evidence while unavailable binary/credential checks remain readiness results.

- [ ] Distinct model assignment and existing exclusive-task/rotation tests pass.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-2, AC-3, AC-4, AC-12. Feature-wide criteria are shared with dependent tasks.

- [ ] Excluded primary/fallback IDs and their aliases cause zero calls; an independently healthy configured fallback remains eligible.

- [ ] One model failure does not ban other models of the same backend.

- [ ] A smoke timeout generates typed failure evidence while unavailable binary/credential checks remain readiness results.

- [ ] Distinct model assignment and existing exclusive-task/rotation tests pass.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3277-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_identity_and_fallback_gate`
- `test_empty_model_is_not_probed`
- `test_failed_primary_is_reported_with_successful_fallback`
- `test_assign_exclusive_tasks_run_alone_and_first`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py
git diff --check
```

Run only relevant subsets while upstream/downstream migration is in progress; do not claim the entire feature is green
from a subset. TASK-3285 runs the final offline package and ledger regression gate. If a runtime defect is discovered
outside this task's scope, report it for the owning task instead of broadening file ownership silently.

## Agent Instructions

1. Read the approved spec and this task completely.
2. Verify dependency entries are done in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json` and their task artifacts are completed.
3. Reverify existing imports/signatures and dependency-produced contracts in the worktree; update stale anchors first.
4. Outline implementation steps and risks; preserve edits from others and touch only declared files.
5. Mark this task in-progress in its per-spec index with the session assignment; do not use the historical monolithic index.
6. Implement the blueprint completely and run the scoped acceptance tests.
7. Record actual results, reviewed fixes, incident IDs if applicable, and any blocked criterion in the Completion Note.
8. On completion move this file to `sdd/tasks/completed/TASK-3277-coder-roster-suspension-gates.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
