# TASK-3288: Collect bounded Ruff, wiki, scope and dependency evidence

**Feature**: FEAT-561 - Deterministic complexity routing for SDD tasks
**Spec**: `sdd/specs/complex-sdd-tasks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3287
**Assigned-to**: unassigned

## Context

Implements FEAT-561 §2–§4; feature acceptance coverage: AC1, AC4, AC5, AC6, AC10, AC14.
Measured evidence must determine routing before dispatch. This task owns the
bounded deliverable below; decisions are fixed by the approved spec and this packet.

## Scope

- Implement all five measurement families and input fingerprints using the feature checkout; collect before code generation.
- Use async subprocesses with bounded output, timeouts, cancellation cleanup and a maximum of four collectors; do not add Radon or provider calls.

**NOT in scope**: unrelated refactors, provider/client changes, new dependencies,
FEAT-559 suspension implementation, edits outside the file table, or changing
approved scoring thresholds through LLM judgment.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` | CREATE | Scoped implementation/documentation |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified from source at `3ba22952c307435fba30704081f1af72658c568f`. Source-verified signatures below are not
claims of runtime import smoke testing. Recheck after upstream task merges.

### Verified Imports / Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:91` — `class BlastRadiusOutput(BaseModel):`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:287` — `async def blast_radius(self, symbol: str, *, relations: list[str] | None=None, depth: int=2, include_inferred: bool=True, include_tests: bool=True) -> BlastRadiusOutput`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2266` — `def symbols_blast(path_: str | None, symbol: str, relations: tuple[str, ...], depth: int, include_inferred: bool, include_tests: bool, as_json: bool) -> None`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:32` — `class TaskRef(BaseModel):`.

### Exact existing symbol IDs

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskRef` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#symbols_blast` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#BlastRadiusOutput` — source-verified symbol identity for the references above.
- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService.blast_radius` — source-verified symbol identity for the references above.

### Touched-file freshness

- All target files are new; do not import them as existing modules before implementing this task.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#symbols_blast",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#BlastRadiusOutput",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService.blast_radius"
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

**Parallelism**: true. Depends on TASK-3287 parser/evaluator and TASK-3286 types. Parallel with TASK-3289 roster and TASK-3293 authoring: all target files are disjoint.

## Implementation Blueprint

### Fixed interfaces and behavior

New in complexity_collectors.py:
- async collect_complexity(worktree: Path, task_file: Path, index_path: Path, policy: ComplexityPolicy) -> ComplexityEvidence.
- async validate_complexity_snapshot(worktree: Path, task_file: Path, index_path: Path, assessment: ComplexityAssessment, policy: ComplexityPolicy) -> bool.
Re-use parse_complexity_contract. Reject resolved paths outside worktree, missing MODIFY targets, existing CREATE targets, duplicate index IDs, missing dependency nodes and cycles with ComplexityContractError. Read full index and compute direct/transitive reverse dependencies independent of task status; deduplicate diamond graphs.
Ruff invocation: ruff check --isolated --no-cache --no-fix --ignore-noqa --select C901 --config lint.mccabe.max-complexity=0 --output-format json -- <explicit MODIFY Python paths>. Separate syntax pass uses --select E9 and the same isolation/no-fix options. Store version, arguments and per-function counts; accept exit 0/1 as diagnostics and treat invalid syntax, non-C901 malformed records or tool failure as unknown. MODIFY .py/.pyi are Python; known documentation/config suffixes (.md,.rst,.txt,.json,.yaml,.yml,.toml,.ini,.cfg) are non-applicable; other existing suffixes are unknown unless a supported analyzer is present. CREATE targets have no existing complexity.
For each exact contract symbol, invoke wikitoolkit symbols blast with --path <absolute feature worktree>, --depth 2 --no-inferred --tests --json. CLI --json emits the raw BlastRadiusOutput fields (cli.py:2185), not a ToolResult envelope. Parse root/impacted/files/truncated; nonzero exit, malformed JSON or a missing root is unknown, never zero. Deduplicate impacted IDs across roots and exclude all root IDs, not only the current root. Retain impacted files and raw per-root payloads; stale hits, missing roots, truncated payload or errors give unknown with a lower bound. Missing contract list gives unknown, explicitly empty gives non-applicable. Graph freshness is limited to the verified service contract; no invented revision field.
Count normalized file parents (root='.'), CREATE + 2*MODIFY, and only top-level Acceptance Criteria checkboxes outside fences. Snapshot HEAD, actual task/index/policy/target hashes before/after collection. Reject inconsistent snapshots if inputs changed during collection; validate_complexity_snapshot returns False on any mismatch or unreadable input. Every subprocess has a 30s total deadline and aggregate stdout+stderr cap 8MiB by default; stop/reap on cancellation/overflow. Canonicalize paths before hashing; do not cache wiki output between plans.

### Steps (in order)

1. Implement bounded subprocess helper and deterministic fixture injection at module helper boundaries.
2. Validate task/files/index and calculate local metric families.
3. Collect Ruff and per-symbol blast data with explicit status semantics.
4. Build fingerprints and add the preflight snapshot comparison helper.

Blueprints are implementation instructions, not stub source files. Implement the
complete behavior and edge cases; do not leave placeholders in executable code.

## Acceptance Criteria

- [ ] All metric families include states, sources, counts and raw diagnostics.
- [ ] A diamond DAG counts each descendant once; source task itself is excluded.
- [ ] CREATE code is never analyzed as existing code; syntax failure and missing collectors never yield measured zero.
- [ ] Timeout, cancellation and output cap reap subprocesses without blocking the event loop.
- [ ] Wiki root absence/truncation/staleness and shared callers follow the spec; task/root checkout mismatches are rejected.

## Test Specification

- Synthetic Python fixtures: C901/noqa/empty file/invalid syntax; fixture wiki payloads and errors.
- Criteria fixtures with nested/fenced/checked boxes; scope and DAG invalidity cases.
- Instrument subprocess helper to verify limits and cancellation without live providers.
- Run pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py -q.

Store command output in `artifacts/logs/TASK-3288-complexity.log`. Use the activated
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
