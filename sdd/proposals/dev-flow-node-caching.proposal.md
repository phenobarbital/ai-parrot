---
id: FEAT-516
title: Recover dev-flow jobs from durable node checkpoints
slug: dev-flow-node-caching
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-31
  summary_oneline: Recover dev_flow and dev_loop jobs from typed, run-scoped node checkpoints with artifact-aware continuation.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-516/
created: 2026-08-31
updated: 2026-08-31
---

# FEAT-516 - Recover dev-flow jobs from durable node checkpoints

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: inline
> **Audit**: [`sdd/state/FEAT-516/`](../state/FEAT-516/)

---

## 0. Origin

The complete original request is preserved at
`sdd/state/FEAT-516/source.md`.

> Add node caching to `dev_loop` and `dev_flow` so a restarted job can reuse
> completed bug-intake, research, and development work instead of executing
> the entire flow again.

**Initial signals**:

- Verbs: add, cache, reuse, recover, restart
- Named entities: `dev_loop`, `dev_flow`, `AgentsFlow`, Redis, bug intake,
  research, development, worktree
- Acceptance criteria provided: recovery intent and three priority nodes;
  detailed identity and failure policies were resolved during review

## 1. Synthesis Summary

The repository already has the core mechanism needed for node caching:
`AgentsFlow` can checkpoint node completion and resume without re-executing
completed nodes. The dev workflows do not enable it, their shared flow instance
does not have per-job checkpoint identity, and generic resume cannot safely
rebuild their custom explicit-edge graph. Their node outputs and live shared
objects also need typed, selective rehydration. The recommended solution is
run-scoped checkpoint recovery backed by the existing Redis store, combined
with worktree and task-index validation when an interrupted development node
must execute again. [F002, F003, F005, F006, F007]

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|---|---|---|---|
| 1 | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | `AgentsFlow.run_flow`, `resume`, `_run_flow_scheduler` | Checkpoint lifecycle and completed-node skipping | F002, F007, F008 |
| 2 | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py` | `FlowCheckpointer` | Node-event snapshot assembly and Redis writes | F002, F006 |
| 3 | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py` | `FlowStateSerializer` | Typed result serialization | F006, F008 |
| 4 | `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | `build_dev_loop_flow` | Explicit-edge bug/enhancement flow | F001, F003 |
| 5 | `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | `build_dev_flow` | Explicit-edge proactive SDD flow | F001, F003 |
| 6 | `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | `DevLoopRunner.run` | Run identity and live session ownership | F003, F006 |
| 7 | `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | `DevFlowRunner.run` | Dev-flow run identity and execution | F003, F006 |
| 8 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/bug_intake.py` | `BugIntakeNode.execute` | Bug enrichment and shared-state projection | F004 |
| 9 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | `ResearchNode.execute` | Jira, research, repository and worktree preparation | F004, F005 |
| 10 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | `DevelopmentNode.execute` | Worker dispatch and task-index-aware continuation | F004, F005 |
| 11 | `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | `TaskScheduler` | Excludes tasks already persisted as done | F005 |

### 2.2 Constraints Discovered

- **Checkpointing already supplies node-level recovery.** Resume seeds completed
  node IDs and results; completed nodes do not execute again. In-flight and
  failed nodes rerun, providing at-least-once node semantics. *Evidence*: F002,
  F007.
- **Checkpoint identity is currently incompatible with runner identity.** Each
  runner invocation has its own `run_id`, but the runner calls a shared
  `AgentsFlow` whose `flow_id` belongs to the instance. *Evidence*: F003.
- **Explicit routing must survive reconstruction.** The dev graphs depend on
  callable predicates, OR joins, and bounded back-edges; generic
  `from_definition` reconstruction changes those semantics and loses live node
  dependencies. *Evidence*: F001, F007, F008.
- **Cache hits must restore shared state.** Downstream nodes read keys such as
  `research_output` and `development_output`, while the current generic resume
  only restores checkpoint context and cannot safely reconstruct a live
  `SessionHost`. *Evidence*: F004, F006.
- **Development has a second recovery layer.** A development node interrupted
  before completion must rerun, but `TaskScheduler` can omit tasks already
  marked done and Research can validate/reuse the existing worktree. *Evidence*:
  F005.
- **Redis failure policy must be stronger for these flows.** Current checkpoint
  writes are fire-and-forget and swallow persistence errors. The accepted policy
  requires a successful checkpoint barrier before downstream work starts.
  *Evidence*: F002; user decision recorded 2026-08-31.

### 2.3 Relevant History

| Commit | Date | Relevance |
|---|---|---|
| `8d7657b23` | 2026-08-30 | Non-ancestor commit adds a tested `flow_factory` resume path and checkpoint type registration for another custom explicit-edge flow |
| `0562660ef` | 2026-08 | Introduced `AgentsFlow` checkpoint wiring, suspend, and resume |
| `5cefa96db` | 2026-08 | Introduced event-driven checkpoint snapshots and leases |

The `8d7657b23` implementation is repository precedent, not functionality on
the current branch. It should be ported or adapted after reviewing its complete
diff. *Evidence*: F008.

## 3. Probable Scope

### 3.1 Recovery Contract

1. The first execution may generate a `run_id`, but that ID must be returned to
   and persisted by the caller/job system.
2. A restarted process constructs a new runner/flow and supplies the same
   `run_id`.
3. Checkpoint identity is namespaced by workflow and stable run ID, preventing
   `dev_loop` and `dev_flow` collisions.
4. The runner loads the latest checkpoint for that identity. No checkpoint is a
   normal cache miss and starts a fresh flow.
5. The runner verifies an immutable input fingerprint containing at least flow
   kind, normalized brief, topology/version, repository identity, and relevant
   execution policy. Reusing a `run_id` with a different fingerprint is a hard
   error.
6. Resume rebuilds the graph through the original flow factory so custom nodes,
   live dependencies, explicit predicates, OR joins, and retry edges are
   preserved.
7. Typed completed-node results are restored and projected back to the shared
   keys expected by downstream nodes. Live-only values such as `SessionHost`,
   dispatchers, toolkits, and trace context are newly constructed and rebound.
8. Completed nodes are skipped. A node that had not durably checkpointed
   completion runs again.
9. The flow acquires the existing per-flow Redis lease; a concurrent duplicate
   resume fails instead of running the same side effects twice.

### 3.2 Required Checkpoint Barrier

For `dev_loop` and `dev_flow`, node completion is not released to downstream
routing until the Redis checkpoint write succeeds. A Redis connection, encoding,
lease, or write error fails the job immediately. This required mode is scoped to
these workflows so the generic `AgentsFlow` default can retain its existing
best-effort compatibility contract. [F002]

The checkpoint is committed only after `node.execute()` succeeds and after the
node result/shared-state projection is complete. A failed or cancelled node is
never marked cacheable.

### 3.3 Priority Node Behavior

**Bug intake**

- A completed checkpoint restores the enriched brief and `bug_findings` without
  reproducing the failure again or re-emitting external enrichment side effects.
- An incomplete bug-intake node reruns normally. [F004]

**Research**

- A completed checkpoint restores `ResearchOutput`, `jira_issue_key`, relevant
  excerpts, and the validated worktree identity without re-dispatching research
  or recreating Jira state.
- Before accepting recovered research, validate that the worktree remains a
  registered worktree on the expected branch and required spec/task artifacts
  still exist. Invalid state fails explicitly rather than silently using stale
  output.
- If research was interrupted before its completion checkpoint, existing Jira
  lookup and worktree-reuse behavior keeps its rerun idempotent. [F004, F005]

**Development**

- A completed checkpoint restores `DevelopmentOutput` and does not dispatch
  workers again.
- If interrupted mid-node, development reruns against the recovered
  `ResearchOutput` and validated worktree. Pool mode reconstructs the scheduler
  from the per-spec index and dispatches only unfinished tasks.
- Single-agent mode remains node-granular: without task artifacts it may rerun
  the worker, which must inspect prior work before editing. The spec should not
  claim task-granular recovery where no task index exists. [F005]

### 3.4 Observability

Expose structured events and logs for cache miss, checkpoint committed, resume
started, node restored, node rerun, artifact validation failure, fingerprint
mismatch, lease conflict, and fatal checkpoint persistence failure. A recovered
run must remain distinguishable from a fresh run in the session timeline and
run bundle.

### 3.5 Non-Goals

- No reuse across different `run_id` values, even when briefs appear equivalent.
- No semantic/global cache keyed only by prompt text.
- No blind deserialization of `SessionHost`, clients, toolkits, dispatchers, or
  other live resources.
- No marking partially executed nodes as complete.
- No replacement of the existing `CheckpointStore` or Redis key family.
- No exactly-once guarantee inside an interrupted node; recovery is exactly-once
  for durably completed nodes and at-least-once for the interrupted frontier.

## 4. Acceptance Direction

- A fresh run writes a durable checkpoint after every successfully completed
  node.
- A new flow process supplied the same `run_id` resumes from the latest durable
  checkpoint.
- Bug intake and research dispatcher call counts remain unchanged after their
  completed checkpoints are restored.
- Completed development is not dispatched again.
- Interrupted pool development dispatches only tasks not already marked done in
  the per-spec index.
- A different brief or topology under the same `run_id` fails with a fingerprint
  mismatch.
- Redis write failure prevents downstream node dispatch and fails the job.
- Two concurrent resumes for the same `run_id` cannot both acquire the lease.
- Restored `ResearchOutput` and `DevelopmentOutput` retain their Pydantic types.
- A fresh `SessionHost` is bound on resume; no serialized live host is trusted.
- Explicit-edge routing and bounded retry loops behave identically after resume.
- Tests cover both `dev_loop` and `dev_flow`, including exception/restart paths.

## 5. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|---|---|---|---|---|
| C1 | Core checkpointing skips completed nodes | F002, F007 | high | Direct implementation and tests |
| C2 | Dev workflows do not enable per-run checkpoints | F003 | high | Direct builder and runner reads |
| C3 | Shared flow identity is unsafe for job caching | F002, F003 | high | `flow_id` is instance-owned while `run_id` is per invocation |
| C4 | Typed/shared-state recovery needs explicit handling | F004, F006 | high | Direct serializer and node contract reads |
| C5 | Pool development can continue from persisted task status | F005 | medium | Pinned for task-index mode, not equivalent in single-agent mode |
| C6 | Flow-factory resume is the preferred engine extension | F007, F008 | medium | Tested precedent exists outside current branch and requires reconciliation |

Distribution: **4 high**, **2 medium**, **0 low**.

## 6. Decisions

- [x] **Cache identity scope** - Reuse is limited to the same stable `run_id`.
  A restarted job creates a new flow instance and supplies that existing ID;
  automatically generating another ID would intentionally be a cache miss.
  *Resolved by user, 2026-08-31.*
- [x] **Redis failure policy** - Any checkpoint persistence failure is a hard
  error and fails the job before downstream side effects execute.
  *Resolved by user, 2026-08-31.*

No material proposal questions remain.

## 7. Recommended Next Step

**`$sdd-spec FEAT-516`** - Formalize the per-run builder lifecycle, required
checkpoint barrier, recovery adapter contract, fingerprint schema, and test
matrix before task decomposition.

## 8. Research Audit

| Artifact | Path |
|---|---|
| State | `sdd/state/FEAT-516/state.json` |
| Source | `sdd/state/FEAT-516/source.md` |
| Research plan | `sdd/state/FEAT-516/research_plan.json` |
| Findings | `sdd/state/FEAT-516/findings/F001-*.md` through `F008-*.md` |
| Synthesis | `sdd/state/FEAT-516/synthesis.json` |

Budget consumed: 18 files, 9 grep calls, 3 git calls, 295 research seconds.
Research was not truncated.

## 9. Provenance

| Field | Value |
|---|---|
| Generated by | `$sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Codex with user policy decisions |
