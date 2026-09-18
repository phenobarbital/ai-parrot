# TASK-3284: Teach both worker prompts the execution lifecycle and fallback

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2h)
**Depends-on**: TASK-3283
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3283 actual MCP surface. Owns only prompt twins and operator docs; TASK-3285 waits to validate prompt/schema agreement against their final content.

## Context

Implements M4 and M5 documentation; §2 worker lifecycle and §5 AC-15. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Update both allowlists/loops to generate and retain one UUID per worker invocation; begin before planning, reuse it across all chunks/retries/native/reviews/cleanup, and explicitly resume the same ID after restart.

- Print exclusion model/incident/source task+execution/reason/cooldown/persistence status without injecting platform incidents into coder lesson prompts.

- Use plan_stale to replan, not_dispatched to keep the task pending, fallback_required for the sequential worker loop, and never treat empty chunks with pending tasks as completion.

- Report native failure or critical confirmed review via attempt-bound suspend_model while preserving per-delivery feedback/review metrics; suspension never means a live native child stopped.

- End only after admitted work settles and persistence succeeds; keep recovery_required blocked until completion/termination evidence is available. Document coordinated MCP/worker upgrade.

- Document kwargs.suspension cooldown_seconds=1800/history_max_tokens=1200, immutable per-execution exclusions, new-run expiry, separate repositories and limits under unwritten events.

**NOT in scope**: Editing sdd-coder model choices, global roster YAML, runtime implementations or changing existing code-feedback policies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Canonical worker allowlist and execution-pool loop |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Packaged twin with the same lifecycle and feedback semantics |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Protocol migration, policy, recovery, exclusions and operator examples |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

No Python imports are required for this documentation-only task. Verify the MCP signatures against the registered toolkit.

### Existing Signatures to Use

- `.claude/agents/sdd-worker.md:26` — tools frontmatter lists the ten current MCP calls; Orchestrator Loop at 217 starts with coder_plan.

- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md:217` — Packaged loop mirrors canonical prompt, including native background notification/no-poll behavior.

- `docs/dev_loop/sdd-coder-orchestrator.md:73` — Per-delivery correction feedback documents review-only lessons and metrics; roster/loop below still describe first-tool probing.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:43` — arg_models is the registered tool authority; reread after TASK-3283, not just this pre-change anchor.

### Does NOT Exist

- Neither worker prompt currently retains an execution UUID.

- No global roster mutation, autonomous cooldown health call or native status polling is part of this feature.

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

1. Replace startup probe-by-plan wording with begin/use/end protocol, preserving existing worktree/task ownership and feedback-source rules.

2. Write complete scoped call examples for all seven changed methods, with the same retained execution_id. Avoid snippets that accidentally create one UUID per chunk.

3. Keep native preparation -> Agent launch -> completion notification -> merge ordering. Do not suggest Agent polling, repeat spawn or cleanup after merely reporting a timeout.

4. Add explicit error/fallback handling for exhaustion, unavailable history, failed persistence, scope/config mismatch, stale plan and uncertain recovery.

5. Keep both prompt copies synchronized and verify their lifecycle sections/allowlists against TASK-3283 schemas. Update outdated restart-attribution claims in docs to match the verified recovery implementation.

6. Perform a static walkthrough of success, timeout/fallback, native-live suspension and restart cases. TASK-3285 owns automated prompt/schema consistency regression tests.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
Worker protocol: one execution_id -> coder_begin_execution -> scoped plan/run/review/cleanup -> coder_end_execution
Read-only coder_feedback_report(feature, worktree) does not require or start an execution
```

### Bounded implementation checklist

- [ ] Both worker copies contain the three new tools and required ID propagation, matching the real schemas.

- [ ] Confirmed defects continue to populate the correct repo/model lesson plane; operational incidents do not.

- [ ] Empty chunk plus pending work cannot end the feature; live native reports cannot trigger premature cleanup.

- [ ] Docs explain 30-minute default, fixed expiry from failure observation, startup-snapshot isolation and migration.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-7, AC-8, AC-12, AC-15. Feature-wide criteria are shared with dependent tasks.

- [ ] Both worker copies contain the three new tools and required ID propagation, matching the real schemas.

- [ ] Confirmed defects continue to populate the correct repo/model lesson plane; operational incidents do not.

- [ ] Empty chunk plus pending work cannot end the feature; live native reports cannot trigger premature cleanup.

- [ ] Docs explain 30-minute default, fixed expiry from failure observation, startup-snapshot isolation and migration.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3284-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_mcp_and_prompt_twins (automated by TASK-3285)`
- `Static lifecycle walkthrough: success, exhausted pool, failed persistence and uncertain native child`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
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
8. On completion move this file to `sdd/tasks/completed/TASK-3284-coder-worker-pool-lifecycle.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Completed 2026-09-16 by sdd-worker (orchestrator), delivered by seat `mistral`
(backend `nova`, model `mistral.devstral-2-123b`), attempt_uid
`2e9f6e665f094133af403b7711937b8b`, merged in commit `af40eecd58c9d57d37d5edac1cfb0eddbe569d9c`.

Both worker-prompt twins (`.claude/agents/sdd-worker.md`,
`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`)
were delivered correctly: tool allowlists gained `coder_begin_execution`/
`coder_end_execution`/`coder_suspend_model`, the Orchestrator Loop was rewritten
to generate one UUID per invocation and thread `execution_id` through every
step, and `not_dispatched`/`plan_stale` outcome handling plus
`coder_suspend_model` reporting were added.

`docs/dev_loop/sdd-coder-orchestrator.md` had two confirmed defects that I
found during review and fixed directly in commit
`7415d6316f43f2cd9038407a3f3a4dfc3fa74d19` (`fix(sdd-coder-execution-pool-suspensions):
TASK-3284 review fixes`):
1. The new "Execution lifecycle and suspension policy" section was pasted
   twice (once nested `###` under "## The roster", once top-level `##`
   before "## Related") — removed the duplicate.
2. "Operator examples" cited two CLI subcommands
   (`parrot sdd-coder suspensions list`, `parrot sdd-coder execution show`)
   that do not exist anywhere in the codebase (verified via grep) — replaced
   with an accurate description of `CoderSuspensionStore.recent()`/
   `for_execution()` over the shared ledger, and clarified that execution
   snapshots are separate per-worktree JSON files
   (`.sdd-coder/executions/<uuid>.json`), not a ledger category.

Also found (not a defect in the delivery — this section predates the
feature and mistral's diff never touched it) that the doc's pre-existing
"## The loop" section still described the old pre-execution-pool protocol,
contradicting the newly-added content and the updated worker prompts.
Rewrote it in the same fix commit: threaded `execution_id` through
`coder_plan`/`coder_run_chunk`/`coder_prepare_native`/`coder_cleanup`,
added step 0 "Begin execution" and step 6 "End execution", and added
`not_dispatched`/`plan_stale` rows to the "## Outcomes" table for
consistency with the updated "## The loop" prose.

Validation: `git diff --check` clean, heading-uniqueness grep clean (see
`artifacts/logs/task-3284-review-fixes.log`). TASK-3285 owns the automated
`test_mcp_and_prompt_twins` consistency test and the final offline
package/ledger regression gate per this task's own scope note.

Feedback recorded: `coder-feedback:00ce15ba8a077c9bb1020402` (pattern
`duplicated-doc-section-and-fabricated-cli`). Review recorded:
`coder-review:a74b108b538264bd97afff14` (fix_commits=
[`7415d6316f43f2cd9038407a3f3a4dfc3fa74d19`]).

Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b ·
Attempts: 1 · Duration: 470.98s · Tokens: 1981569 in / 12881 out.
