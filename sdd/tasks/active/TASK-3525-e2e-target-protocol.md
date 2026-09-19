# TASK-3525: Define target adapter protocol and lazy fixed registry

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3521
**Assigned-to**: unassigned
**Module**: M4
**Spec acceptance criteria**: AC2, AC6

---

## Context

Implement the M4 deliverable **Define target adapter protocol and lazy fixed registry** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Define LaunchSpec with argv/env/cwd/stdio; redact env from repr/logs/serialization and validate argv execution without shell.
- Define TargetAdapter prepare/ready Protocol exactly as §3 and a fixed lazy registry for six public target kinds.
- Registry imports only the selected adapter; missing optional implementation/dependency yields explicit prerequisite error.
- Resolve M3/M4 cycle by making this protocol independent of supervisor and concrete target modules.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/targets/__init__.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/src/parrot/e2e/targets/base.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_target_registry.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

This module is new. No existing project symbol is required beyond standard library and already-declared Pydantic/YAML/pytest dependencies. Its field and outcome contracts come from spec §2.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3521 (`sdd/tasks/active/TASK-3521-e2e-plan-loader.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `TargetAdapter.prepare(config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec (async)`
- `TargetAdapter.ready(state: RunState) -> bool (async)`

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/base.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_target_registry.py",
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
- **Parallelism:** TASK-3525 owns its declared files for M4. TASK-3521 supplies load contained feature plans and enforce spec consistency. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Define LaunchSpec with argv/env/cwd/stdio; redact env from repr/logs/serialization and validate argv execution without shell.
2. Define TargetAdapter prepare/ready Protocol exactly as §3 and a fixed lazy registry for six public target kinds.
3. Registry imports only the selected adapter; missing optional implementation/dependency yields explicit prerequisite error.
4. Resolve M3/M4 cycle by making this protocol independent of supervisor and concrete target modules.

### Fixed interfaces

- `TargetAdapter.prepare(config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec (async)`
- `TargetAdapter.ready(state: RunState) -> bool (async)`

### `packages/ai-parrot-server/src/parrot/e2e/targets/__init__.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define LaunchSpec with argv/env/cwd/stdio; redact env from repr/logs/serialization and validate argv execution without shell.

2. Define TargetAdapter prepare/ready Protocol exactly as §3 and a fixed lazy registry for six public target kinds.

3. Registry imports only the selected adapter; missing optional implementation/dependency yields explicit prerequisite error.

4. Resolve M3/M4 cycle by making this protocol independent of supervisor and concrete target modules.
### `packages/ai-parrot-server/src/parrot/e2e/targets/base.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define LaunchSpec with argv/env/cwd/stdio; redact env from repr/logs/serialization and validate argv execution without shell.

2. Define TargetAdapter prepare/ready Protocol exactly as §3 and a fixed lazy registry for six public target kinds.

3. Registry imports only the selected adapter; missing optional implementation/dependency yields explicit prerequisite error.

4. Resolve M3/M4 cycle by making this protocol independent of supervisor and concrete target modules.
### `packages/ai-parrot-server/tests/unit/e2e/test_target_registry.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Define LaunchSpec with argv/env/cwd/stdio; redact env from repr/logs/serialization and validate argv execution without shell.
- [ ] Define TargetAdapter prepare/ready Protocol exactly as §3 and a fixed lazy registry for six public target kinds.
- [ ] Registry imports only the selected adapter; missing optional implementation/dependency yields explicit prerequisite error.
- [ ] Resolve M3/M4 cycle by making this protocol independent of supervisor and concrete target modules.
- [ ] Relevant spec criteria AC2, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_target_registry.py -q`

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
