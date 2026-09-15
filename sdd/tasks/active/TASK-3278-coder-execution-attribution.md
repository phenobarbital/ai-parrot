# TASK-3278: Add execution attribution to telemetry and review history

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-3275
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3275 for AttemptRecord identity. Runs beside TASK-3276/TASK-3277 because telemetry and existing feedback/review files are disjoint; TASK-3281 waits for this work before editing test_feedback.py.

## Context

Implements M3 attribution contracts; §2 integration points and §7 compatibility. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Add optional validated execution_id to historical feedback/review/telemetry records; absence means unknown historical attribution, never an invented execution.

- Project execution_id explicitly from new AttemptRecord rows and include it in OutcomeRow while keeping field allowlisting and existing bounds.

- Keep feedback occurrence IDs, pattern deduplication, 90-day lesson policy and correction-rate cohorts unchanged; no operational failures enter lesson records.

- Add isolated store/projection compatibility tests here. Engine-side required identity and cross-execution source authentication land in TASK-3281.

**NOT in scope**: Engine attribution validation, suspension events, changes to feedback ranking/expiry/measurement policy.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` | MODIFY | Add execution identity to allowlisted usage/outcome projection |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` | MODIFY | Optional historical execution attribution without changing lesson IDs |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py` | MODIFY | Optional historical execution attribution without changing cohorts |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py` | MODIFY | Legacy and current row compatibility |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py` | MODIFY | Legacy review/lesson record compatibility |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.telemetry import AttemptUsageRow, OutcomeRow, build_attempt_row
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReview, CoderReviewMeasurement, CoderReviewStore
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:40` — AttemptUsageRow; OutcomeRow at 76; build_attempt_row(record, *, feature_id, job_id, task_id, declared_files) at 156 explicitly allowlists fields.

- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:24` — CoderFeedback uses extra='forbid'; feedback_id() at 65 hashes backend/model/task/attempt/pattern.

- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py:22` — CoderReview uses extra='forbid'; CoderReviewStore.record at 76 and report at 130 aggregate measured review cohorts.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py:20` — _row(**over) helper and TestProjection preserve no-exception-text policy.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py:22` — feedback(**overrides) helper and store(tmp_path), line 42, support isolated legacy record replay.

### Does NOT Exist

- Current feedback/review/usage payloads have no execution_id.

- A timeout is not a valid feedback source or a reviewer correction commit.

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

1. Use an additive optional field for old JSON; validate nonempty new values as UUIDs. Do not add execution_id to existing stable feedback/review key algorithms.

2. Update build_attempt_row's explicit field mapping, not model_dump forwarding. Preserve error_class-only persistence and usage unknown/null behavior.

3. Round-trip old feedback/review events without execution_id and new events with it through a fresh store; confirm same occurrence IDs and same zero-fix cohort counts.

4. Do not migrate engine-based tests to a guessed lifecycle here; add focused unit cases only and leave their migration to TASK-3281/TASK-3285.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
CoderFeedback.execution_id: str | None (historical default None)
CoderReview.execution_id: str | None (historical default None)
AttemptUsageRow.execution_id and OutcomeRow.execution_id: additive historical identity
```

### Bounded implementation checklist

- [ ] Old records parse without rewriting history; adding execution_id preserves feedback_id and review cohort totals.

- [ ] New usage/outcome JSON carries the same execution UUID as its attempt.

- [ ] Unknown history is not counted as a zero-fix baseline; no raw failure payload crosses the telemetry allowlist.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-3, AC-11. Feature-wide criteria are shared with dependent tasks.

- [ ] Old records parse without rewriting history; adding execution_id preserves feedback_id and review cohort totals.

- [ ] New usage/outcome JSON carries the same execution UUID as its attempt.

- [ ] Unknown history is not counted as a zero-fix baseline; no raw failure payload crosses the telemetry allowlist.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3278-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_legacy_history_and_telemetry`
- `test_execution_identity_projection`
- `test_feedback_identity_is_stable_with_execution_attribution`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3278-coder-execution-attribution.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
