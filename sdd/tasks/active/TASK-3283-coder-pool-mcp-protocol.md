# TASK-3283: Expose execution lifecycle and suspension tools through MCP

**Feature**: FEAT-559 - SDD coder execution pools and recent suspensions
**Spec**: `sdd/specs/sdd-coder-execution-pool-suspensions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-3282
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-3282 final lifecycle/status behavior. No overlapping toolkit edits may run during this task; TASK-3284 documents exactly this landed surface.

## Context

Implements M4; §2 new public interfaces and deliberate protocol upgrade. This is one bounded part of FEAT-559, not permission to implement the whole feature.
The approved policy suspends an exact backend/model for the rest of its worker execution and records recent
operational history for later executions. The cooldown is 1800 seconds from failure observation, not attempt start.

## Scope

- Register coder_begin_execution, coder_end_execution and coder_suspend_model using the new TASK-3275 argument models and TASK-3279-TASK-3282 engine methods; each valid invocation returns CoderResult.

- Require execution_id in seven orchestration/review schemas and propagate it without generating IDs implicitly. Keep wait/status job-scoped and repository-wide feedback_report read-only.

- Expose suspension policy kwargs alongside existing roster/lint/feedback settings; startup/_open must never probe before begin reads history.

- Include current pool state/exclusions/persistence in status/wait and retain per-seat usage summaries. Await TASK-3282 status where needed.

- Map missing execution to execution_required before any model work, not generic internal_error or silent fallback; test actual adapter invocation as well as schemas.

- Keep expected exhausted pools as OK fallback_required with pending work, not unclassified errors.

**NOT in scope**: Generic toolkit/adapter refactors, worker prompt edits and backward-compatible implicit execution creation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Register lifecycle tools, propagate IDs, policy kwargs and views |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | Actual generated schemas, execution validation and envelopes |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py` | MODIFY | Local server registration and no-probe startup |

Only these implementation/test/documentation files are authorized. The SDD worker separately owns this task's
status, Completion Note, move to completed, and its entry in `sdd/tasks/index/sdd-coder-execution-pool-suspensions.json`.

## Codebase Contract (Anti-Hallucination)

Verified on 2026-09-16 against committed dev source at `be9f7a2a7e4925b3e59aa27b76d40d3e6f930661`;
the feedback/review prerequisite is present in that commit. The allocator subsequently reserved this task.
These are pre-implementation anchors: reread after dependencies land and update stale contracts before coding.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.flows.dev_loop.sdd_coder.models import CoderResult, CoderError
from parrot.mcp.adapter import MCPToolAdapter
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:38` — SddCoderToolkit.arg_models at 43 exposes ten tools; coder_feedback_report currently shares CoderPlanArgs.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:81` — _pre_execute validates explicit argument models; _open at 102 currently invokes engine.open; _run at 126 envelopes method failures.

- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:209` — coder_status currently calls synchronous engine.status; _with_seats at 31 projects job data.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py:57` — Full execute-path test shows _pre_execute exceptions become MCP isError rather than CoderResult; direct method tests alone are insufficient.

- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py:27` — test_mcp_local_serves_sdd_coder constructs the actual server from examples/sdd-coder-mcp.yaml with injected probe.

### Does NOT Exist

- The three lifecycle tools do not exist in the current registration set.

- A required Python method argument alone does not guarantee the generated schema/pre-execute path yields the intended error code.

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

1. Update arg_models and public annotated method signatures together; separate feedback-report argument shape to avoid accidental execution requirement.

2. Forward all scoped IDs through _run to the engine. Missing ID is an explicit protocol error; other malformed UUID/scope/extra-field inputs remain rejected.

3. Verify the real get_tools() JSON schemas mark execution_id required; confirm actual adapter errors expose execution_required even if pre-validation uses the host's isError envelope. Do not change generic MCP adapter code outside this task scope.

4. Adjust _with_seats/status/wait to preserve execution pool view while retaining current rollups. Keep close/shutdown cancellation distinct from model suspension.

5. Use only fake probes/dispatchers for toolkit/server tests; assert server construction and feedback_report cannot perform paid availability checks.

### Target interfaces / fixed constraints

The following is a contract sketch, not a copy-paste implementation or an assertion that new methods exist:

```text
coder_begin_execution(feature: str, worktree: str, execution_id: str)
coder_end_execution(execution_id: str)
coder_suspend_model(execution_id: str, attempt_uid: str, reason: str, evidence_ref: str)
coder_plan/run_chunk/prepare_native/merge/cleanup/record_feedback/record_review: required execution_id
```

### Bounded implementation checklist

- [ ] Actual registered tool set contains the ten existing plus three new tools; no helper leaks into MCP.

- [ ] Missing/invalid ID cannot invoke probe or dispatcher; feedback_report remains callable without a pool.

- [ ] Exhausted and history-degraded responses preserve worker fallback diagnostics and never imply task completion.

- [ ] Configured cooldown/token bounds are enforced and forwarded to the engine.

Complete business logic, exception paths and test bodies within these constraints. Do not leave runtime stubs.
No public API beyond the approved spec is authorized; surface a genuine missing design decision to the worker.

## Acceptance Criteria

Spec coverage: AC-1, AC-8, AC-9, AC-11, AC-15. Feature-wide criteria are shared with dependent tasks.

- [ ] Actual registered tool set contains the ten existing plus three new tools; no helper leaks into MCP.

- [ ] Missing/invalid ID cannot invoke probe or dispatcher; feedback_report remains callable without a pool.

- [ ] Exhausted and history-degraded responses preserve worker fallback diagnostics and never imply task completion.

- [ ] Configured cooldown/token bounds are enforced and forwarded to the engine.
- [ ] Implement every declared deliverable and preserve existing relevant assertions.
- [ ] Targeted tests and scoped formatting/lint pass; record commands/results under `artifacts/logs/task-3283-*.log`.
- [ ] `git diff --check` passes; no runtime code outside this task's declared scope changed.

## Test Specification

### Required scenarios

- `test_missing_execution_rejected`
- `test_toolkit_exposes_execution_lifecycle_tools`
- `test_registered_schemas_require_execution_identity`
- `test_status_wait_preserve_pool_and_seat_views`
- `test_mcp_local_starts_without_probe`

Use the assertions above, an injected aware UTC clock and asyncio events/barriers for races. Assert actual invocation
counts and durable replay results, not just log messages. A fake timeout must fail immediately; never wait 1800 seconds.
For documentation tasks, perform the specified static walkthrough and leave executable cross-checks to the named test owner.

### Validation commands

Activate the main checkout's virtual environment first when running from a feature worktree; do not create a new venv.
Store command output in `artifacts/logs/`.

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py -q
black --check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py
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
8. On completion move this file to `sdd/tasks/completed/TASK-3283-coder-pool-mcp-protocol.md`, update this task's index path/status,
   and commit code plus owned SDD state in the feature worktree. Do not mark done while required work remains.

## Completion Note

Not completed. The executing worker must record its identity, date, implementation summary, verification evidence
and deviations here before marking this task done.
