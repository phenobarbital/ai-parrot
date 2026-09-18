# TASK-3294: Apply measured routing in worker prompt twins and operator configuration

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3292, TASK-3293
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC7, AC8, AC9, AC12, AC13, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Teach both worker copies to display server evidence, preserve model restrictions on fallback and stop blocked tasks without polling indefinitely.
- Provide the requested two exact candidate identities in example configuration and explain policy thresholds and operational limits.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Scoped implementation/documentation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Scoped implementation/documentation |
| `examples/sdd-coder-mcp.yaml` | MODIFY | Scoped implementation/documentation |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Scoped implementation/documentation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `.claude/agents/sdd-worker.md:1` — `---`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md:1` — `---`.
- `examples/sdd-coder-mcp.yaml:1` — `# FEAT-549 — sdd-coder orchestration kernel as a local MCP toolkit.`.
- `docs/dev_loop/sdd-coder-orchestrator.md:1` — `# sdd-worker as orchestrator of parallel sdd-coder seats (FEAT-549)`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:149` — `async def coder_plan(self, feature: str, worktree: str) -> CoderResult`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_plan` — source-verified symbol identity for the references above.

### Touched-file freshness

- `.claude/agents/sdd-worker.md:1` — existing file read; baseline SHA-256 `7f79d3a80d7dfc05ef909bb54a72f2f947bb11e1b8db573200dc8c7b6529a693`. Hash is freshness evidence, not a Delegation Contract.
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md:1` — existing file read; baseline SHA-256 `7f79d3a80d7dfc05ef909bb54a72f2f947bb11e1b8db573200dc8c7b6529a693`. Hash is freshness evidence, not a Delegation Contract.
- `examples/sdd-coder-mcp.yaml:1` — existing file read; baseline SHA-256 `9a0b57ef704d81f9eb5085462e71bdf0193a61f367fc3fbb4eb8168d72232711`. Hash is freshness evidence, not a Delegation Contract.
- `docs/dev_loop/sdd-coder-orchestrator.md:1` — existing file read; baseline SHA-256 `75a1d141852a2c3d042e01c386373beaeda0103220f0455599b3dd48519ef891`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3292` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py`. These outputs are future contracts at authoring time; verify after the dependency lands.
- `TASK-3293` creates/changes: `sdd/templates/task.md`, `.claude/commands/sdd-task.md`, `.agents/skills/sdd-task/SKILL.md`. These outputs are future contracts at authoring time; verify after the dependency lands.

### Integration reconciliation

FEAT-559 is in progress in its own per-spec index and is not implemented in this
baseline: there is no landed execution-pool API to import. Freeze this task's
interfaces against current dev. If FEAT-559 lands before execution/merge, reverify
contracts and preserve its available-seat/suspension intersection and execution
identity; never restore a suspended seat or discard its API parameters. Do not
add external TASK IDs to this feature's depends_on DAG. FEAT-560 has already
landed `partition_wave` in `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`; roster changes must preserve it.
This resolves spec §8's code-research prerequisite; no guessed pool APIs are used.

### Does NOT Exist

- `sdd_coder/orchestrator.py` — use the verified engine module.
- An existing complexity classifier or graph revision token at this baseline.
- Guaranteed equivalence between `sonnet` and `sonnet-5`.
- Dependency-created complexity symbols before their owning tasks complete.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "examples/sdd-coder-mcp.yaml",
      "action": "MODIFY"
    },
    {
      "path": "docs/dev_loop/sdd-coder-orchestrator.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_plan"
  ]
}
```

This declares existing references verified above, not a precomputed score.
When dependency-created symbols become existing imports, the executor must verify
and add them to this contract before admission; absence from today's graph is
not evidence of zero impact. Collector snapshots and scores remain server-owned.

## Implementation Notes

Use existing Pydantic v2 and async subprocess patterns. No new library installation.
Maintain 120-column Python, strict type hints, Google-style docstrings and logging.
Keep architecture decisions in this task/spec; do not ask the coder to decide
whether a task feels complex. No Delegation Contract is emitted: this packet
fixes interfaces and behavior but does not contain complete writer-ready source.

**Parallelism**: true. Depends on TASK-3292 actual MCP fields and TASK-3293 authoring protocol; edits prompt twins/example/docs only.

## Implementation Blueprint

### Fixed interfaces and behavior

Worker must display classification, key metrics, reason codes, assessment ID and selected effective model from coder_plan. Route native only with prepared.model and prepared.assessment_id. Distinguish dependency blocks from routing blocks; process independent chunks and report remaining blocked task IDs when none can proceed. On complexity_plan_stale request an explicit new plan, not manual reassignment.
Override all existing sequential/attempt-3/unavailable-server fallback instructions for complex/unknown tasks: cannot self-implement using an unspecified worker model. If no assessment can be obtained (including server unavailable or roster_empty), classify evidence as unavailable for routing purposes and block instead of assuming standard. Preserve review/feedback, fidelity and cleanup semantics.
Example YAML adds strong-model policy entries and matching seats for canonical gpt-5.6-terra via codex and canonical sonnet-5 via native (only where the host accepts the exact ID); preserve existing ordinary seats. Both policy identity tuples and seat.model must agree. Keep model IDs in configuration, not prompt conditionals. Document how an operator explicitly maps a canonical model to an exact deployed ID; never claim sonnet alias is verified equivalent.
Document all six score rows/five signal families, hard triggers, unknown handling, runtime artifact location, collector limits, depth-two/static graph freshness limits and no empirical model ranking. Explain empty allowlist blocks restricted tasks. Never overwrite local .parrot/mcp-toolkits.yaml or secret files. Worker twins must be byte-identical.

### Steps (in order)

1. Update fallback and display behavior in canonical worker prompt and mirror exactly to packaged copy.
2. Add valid policy/seat YAML examples while preserving normal candidates.
3. Document thresholds, artifacts, blocks and operational model mapping.
4. Run existing prompt parity and YAML validation.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Both worker copies are byte-identical and do not bypass restrictions through attempt 3 or server-unavailable fallback.
- [ ] The two requested candidate models appear in configuration with exact, consistent identity mappings.
- [ ] No-source/no-model states are visible blocks rather than an LLM confidence decision.
- [ ] Independent work can finish when restricted tasks are blocked; completion is not falsely reported.

## Test Specification

- Run pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q.
- Load YAML with existing PyYAML and construct SddCoderToolkit configuration without a live provider probe.
- TASK-3295 adds durable assertions covering all fallback language paths.

Store command output in `artifacts/logs/TASK-3294-complexity.log`. Use the activated
main environment; worktrees share it and must not create/install a new environment.
No live model call is needed for these checks.

## Agent Instructions

1. Read the approved spec and verify every dependency is completed in this feature index.
2. Re-read exact source contracts and dependency outputs; update this packet if references moved.
3. Mark only this task in progress in `sdd/tasks/index/complex-sdd-tasks.json` in the feature worktree.
4. Implement only the declared scope and run its focused validation.
5. Commit code and this task's SDD state together; preserve other agents' edits.
6. On verified completion move the task to completed, update its index entry/path and fill the Completion Note.

## Completion Note

Implemented as specified: both `sdd-worker.md` copies teach the worker to
display evidence (classification/metrics/assessment ID/model), handle
`complexity_plan_stale` by requesting a fresh plan, and refuse to bypass a
`complex_model_unavailable` block via fallback/self-implementation for
non-standard classifications; `examples/sdd-coder-mcp.yaml` configures the
two requested strong-model candidates (`gpt-5.6-terra` via codex,
`sonnet-5` via native); `docs/dev_loop/sdd-coder-orchestrator.md` documents
the full scoring system, hard triggers, routing rules and operator model
identity mapping.

Delivered by the native haiku agent (attempt_uid
03326bd0d6944f49b5b6ec91939a5b84). Two real defects found on review and
fixed:
- The delivery made a SECOND commit that moved its own task file to
  `sdd/tasks/completed/` and edited the per-spec index — out of scope for
  a coder (SDD state is the orchestrator's job). The worker merged ONLY
  the first, code-only commit (`e9b140ef0f9b729da1f31eb3e70d493ad53083ae`)
  into the feature branch via `git merge --no-ff`, verified
  `git diff <base> HEAD --stat -- sdd/` is empty, and performed this SDD
  state update itself.
- The example YAML and its matching doc section used a nonexistent
  `roster.policy.strong_model_candidates`/`seat_label` schema —
  `SddCoderToolkit.__init__` has no `policy` kwarg (only a top-level
  `complexity` kwarg), and `ComplexityPolicy.strong_models` entries are
  `StrongModelIdentity(canonical_model, backend, model)`, no `seat_label`.
  The example was silently non-functional (`strong_models` stayed empty).
  Fixed both files to the real schema in commit
  `5f5ab220288874ddfbdf4bc86f896cacb6bf3635`, verified by constructing
  `SddCoderToolkit` directly from the corrected YAML.

Both defects recorded as model feedback
(`coder-feedback:503a300a5f5b84aac0fe786d`,
`coder-feedback:94bcf9bfdadbb67f737cffb0`) and the review outcome recorded
(`coder-review:c2808d191eb03491800e8680`).

Acceptance criteria: satisfied — worker copies verified byte-identical
(`diff` clean); no bypass of complexity restrictions (worker prompt now
explicitly refuses to self-implement complex/unknown blocks); strong-model
candidates configured with consistent, now-functional identities; blocking
behavior (`complex_model_unavailable` vs dependency blocks) documented and
distinguished.

Tests: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` ->
296 passed (0 failed), run with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` (needed
for `parrot.mcp`'s `pkgutil.extend_path` namespace merge with
`ai-parrot-server`'s `parrot/mcp/transports/`; core-only `PYTHONPATH` makes
the whole `conftest.py` import chain fail — pre-existing, unrelated to this
task). `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py`
-> the same 4 pre-existing failures noted in TASK-3293 (unrelated
delegation-protocol wording), no new failures.

Limitations: none beyond this task's declared scope. Note for future
debugging (not a defect, just a gotcha): importing `parrot.*` triggers a
navconfig/Navigator side effect that `chdir()`s the process to the main
checkout — a verification script combining a relative path with an early
`parrot` import can silently read the wrong file; use an absolute path
opened before any `parrot` import.

Seat: haiku (native) · Backend: native · Model: haiku · Attempts: 1 ·
Duration: ~618s (per subagent hand-back) · Tokens: n/a (native, not
MCP-metered) · Fix commit: 5f5ab220288874ddfbdf4bc86f896cacb6bf3635
(worker, post-merge); code-only commit adopted:
e9b140ef0f9b729da1f31eb3e70d493ad53083ae (worker's own manual
`git merge --no-ff`, since the coder's out-of-scope second commit made
`coder_merge`'s "latest attempt branch" unsafe to adopt whole).
