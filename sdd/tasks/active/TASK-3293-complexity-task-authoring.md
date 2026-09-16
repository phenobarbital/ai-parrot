# TASK-3293: Emit measurable task contracts in both SDD authoring hosts

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3287
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC3, AC4, AC12, AC13, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Add Complexity Contract authoring instructions and a concrete parser-compatible task example to the template and both hosts.
- Separate measurable declaration from optional Delegation Contract; do not add hand-authored complexity classification, model guesses or threshold overrides.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/task.md` | MODIFY | Scoped implementation/documentation |
| `.claude/commands/sdd-task.md` | MODIFY | Scoped implementation/documentation |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Scoped implementation/documentation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `sdd/templates/task.md:1` — `# TASK-<NNN>: <Title>`.
- `.claude/commands/sdd-task.md:1` — `# /sdd-task — Decompose a Spec into SDD Tasks`.
- `.agents/skills/sdd-task/SKILL.md:1` — `---`.

### Touched-file freshness

- `sdd/templates/task.md:1` — existing file read; baseline SHA-256 `af33b471e26da1006858eb4dc5c411393f01217c7fc954d860250b9dd9a31b1b`. Hash is freshness evidence, not a Delegation Contract.
- `.claude/commands/sdd-task.md:1` — existing file read; baseline SHA-256 `8ecd36a086c1a0ee98986be7b6cceac229bd86925e9862c73ee2e23ce669f5d3`. Hash is freshness evidence, not a Delegation Contract.
- `.agents/skills/sdd-task/SKILL.md:1` — existing file read; baseline SHA-256 `2687e993640ec60d84565ffa4280b7ba0a41b06fe4eb6a2def105c646f76f8f8`. Hash is freshness evidence, not a Delegation Contract.

### Dependency-provided contracts

- `TASK-3287` creates/changes: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py`, `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py`. These outputs are future contracts at authoring time; verify after the dependency lands.

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
      "path": "sdd/templates/task.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-task/SKILL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
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

**Parallelism**: true. Depends on TASK-3287 parser schema. Parallel with TASK-3288/TASK-3289 and subsequent engine tasks because its three documentation targets are disjoint.

## Implementation Blueprint

### Fixed interfaces and behavior

Add ## Complexity Contract JSON with schema_version=1, targets identical to Files to Create / Modify (uppercase actions), and contract_symbols listing all existing exact IDs referenced by the Codebase Contract. Explain None/absent legacy coverage versus an explicitly empty list for no existing symbol references; cannot omit a difficult symbol merely to reduce its blast score.
Authoring must validate the target table, section boundaries, top-level Acceptance Criteria and existing-symbol provenance. Future APIs from dependency tasks must be labeled future, verified after dependencies land, and incorporated into the contract before dispatch when they become existing references. Keep the measured snapshot server-owned: no task score or estimated effort replaces evaluation.
Maintain current task ID allocator, per-spec index schema and graph-check rules. Preserve optional Delegation Contract semantics and its complete-code/hash requirements. Do not alter spec approval, sync or worktree creation rules. Use the TASK-3287 parser contract; document legacy unknown route and action/existence validation timing.

### Steps (in order)

1. Add a separate measurable declaration section and explanatory example to the template.
2. Add equivalent generation/reverification steps to command and skill.
3. Manually compare host meaning and validate a completed example through parse_complexity_contract after dependencies land.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] Both hosts instruct generation of the same schema with exact target/symbol provenance.
- [ ] Legacy missing coverage is documented as unknown and cannot be downgraded by natural-language assurances.
- [ ] Complexity Contract and Delegation Contract remain distinct and independently optional for old tasks.
- [ ] Template criteria remain machine-countable top-level checkboxes.

## Test Specification

- Validate a temporary fully populated example with parse_complexity_contract; check malformed declarations fail.
- Run existing packages/ai-parrot-tools/tests/tool_optimizations/test_sdd_contracts.py; new authoring integration assertions are owned by TASK-3295.

Store command output in `artifacts/logs/TASK-3293-complexity.log`. Use the activated
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

Not started. On completion record files changed, acceptance evidence, tests,
commit SHA, remaining limitations and actual model/attempt/assessment attribution.
