# TASK-3533: Execute bounded plans and publish final evidence

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3523, TASK-3528, TASK-3529, TASK-3530, TASK-3532
**Assigned-to**: unassigned
**Module**: M3
**Spec acceptance criteria**: AC2, AC5, AC7, AC8

---

## Context

Implement the M3 deliverable **Execute bounded plans and publish final evidence** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Load/preflight plan, capture source identity, start target dependencies and execute only declared node IDs with plugin.
- Enforce run/scenario deadlines; start no optional paid lane without flags/key; store per-scenario BLOCKED rather than silently deleting coverage.
- Always teardown/reap every owned target and pytest child before hashing final artifacts/updating verdict pointer.
- Capture post-run identity, reject source mutations, map status to §2 exit codes and preserve incomplete evidence after signals.
- Share one live budget context per run when the optional live adapter is installed; no model call in readiness.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/runner.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

This module is new. No existing project symbol is required beyond standard library and already-declared Pydantic/YAML/pytest dependencies. Its field and outcome contracts come from spec §2.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3523 (`sdd/tasks/active/TASK-3523-e2e-evidence-verifier.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3528 (`sdd/tasks/active/TASK-3528-e2e-watchdog.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3529 (`sdd/tasks/active/TASK-3529-e2e-mcp-targets.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3530 (`sdd/tasks/active/TASK-3530-e2e-botmanager-target.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3532 (`sdd/tasks/active/TASK-3532-e2e-pytest-plugin.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict (async)`

### Modify-Target Freshness

All task targets are CREATE; check for collisions before writing them.

### Does NOT Exist

- The new E2E harness and run/verify machinery do not exist at decomposition time;
  dependent task outputs are not pre-existing imports.
- No `E2ECriterion`, universal agent `/mcp/info`, reliable cookie session backend,
  or automatic provider-wide request budget may be assumed.
- Eligibility annotations are not Delegation Contracts. This task follows normal
  implementation routing until a complete validated code packet is authored.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/runner.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_runner.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3533 owns its declared files for M3. TASK-3523 supplies evaluate exact coverage and validate immutable evidence; TASK-3528 supplies enforce leases and recovery after controller/supervisor death; TASK-3529 supplies add real toolkit http and persistent stdio target adapters; TASK-3530 supplies add private redis and authenticated minimal botmanager target; TASK-3532 supplies capture exact pytest node and phase evidence. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Load/preflight plan, capture source identity, start target dependencies and execute only declared node IDs with plugin.
2. Enforce run/scenario deadlines; start no optional paid lane without flags/key; store per-scenario BLOCKED rather than silently deleting coverage.
3. Always teardown/reap every owned target and pytest child before hashing final artifacts/updating verdict pointer.
4. Capture post-run identity, reject source mutations, map status to §2 exit codes and preserve incomplete evidence after signals.
5. Share one live budget context per run when the optional live adapter is installed; no model call in readiness.

### Fixed interfaces

- `run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> E2EVerdict (async)`

### `packages/ai-parrot-server/src/parrot/e2e/runner.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Load/preflight plan, capture source identity, start target dependencies and execute only declared node IDs with plugin.

2. Enforce run/scenario deadlines; start no optional paid lane without flags/key; store per-scenario BLOCKED rather than silently deleting coverage.

3. Always teardown/reap every owned target and pytest child before hashing final artifacts/updating verdict pointer.

4. Capture post-run identity, reject source mutations, map status to §2 exit codes and preserve incomplete evidence after signals.

5. Share one live budget context per run when the optional live adapter is installed; no model call in readiness.
### `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Load/preflight plan, capture source identity, start target dependencies and execute only declared node IDs with plugin.
- [ ] Enforce run/scenario deadlines; start no optional paid lane without flags/key; store per-scenario BLOCKED rather than silently deleting coverage.
- [ ] Always teardown/reap every owned target and pytest child before hashing final artifacts/updating verdict pointer.
- [ ] Capture post-run identity, reject source mutations, map status to §2 exit codes and preserve incomplete evidence after signals.
- [ ] Share one live budget context per run when the optional live adapter is installed; no model call in readiness.
- [ ] Relevant spec criteria AC2, AC5, AC7, AC8 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_runner.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

Test the boundary and negative cases from Scope using the exact task-owned test file(s).

**Runtime E2E validation:** ordinary SDD test selection intentionally excludes E2E.
After the required harness dependencies exist, run declared scenario node IDs via
`parrot e2e run --plan` with `PARROT_TEST_E2E=1`. Live execution additionally needs
`PARROT_TEST_REAL_LLM=1` and the provider key. These are separate from the file-level
pytest contract above. This task cannot claim E2E success solely from agent-tier tests.

## Agent Instructions

1. Read the approved spec and confirm every Depends-on task is done in the per-spec index.
2. For research-gated work, read the completed research contract; BLOCKED research
   does not authorize guessing its unresolved interface.
3. Update `sdd/tasks/index/agentic-e2e-testing.json` to in-progress with assignment/time.
4. Verify imports/signatures, then implement this task's bounded blueprint.
5. Run Validation Commands and applicable runtime probes; retain useful logs.
6. Commit scoped code and SDD state, move this task to `sdd/tasks/completed/`,
   update its index file path/status/timestamps and fill the Completion Note.
7. Never update the historical monolithic task index.

## Completion Note

To be filled by the implementing agent with actual completion date, tests,
observations, limitations and any explicitly authorized deviations.
