# TASK-3545: Add deterministic nightly and explicit live CI plans

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3536, TASK-3537, TASK-3540, TASK-3543
**Assigned-to**: unassigned
**Module**: M9
**Spec acceptance criteria**: AC14

---

## Context

Implement the M9 deliverable **Add deterministic nightly and explicit live CI plans** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.
- Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.
- Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.
- Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/e2e.yml` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/e2e/plans/deterministic.md` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/e2e/plans/live.md` | CREATE | Targeted test coverage |
| `tests/sdd_scripts/test_e2e_ci_plans.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `.github/workflows/ci.yml:1` — Existing CI has push/PR triggers and uv setup. New E2E workflow adds scheduled/manual lanes; do not alter existing workflow. Source SHA-256: `4916a147e2886dca6abfa60602197998e099c7477a78d6c05139111b0e502ca6`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3536 (`sdd/tasks/active/TASK-3536-e2e-auth-offline-scenarios.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3537 (`sdd/tasks/active/TASK-3537-e2e-crash-isolation-scenarios.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3540 (`sdd/tasks/active/TASK-3540-e2e-live-agent.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3543 (`sdd/tasks/active/TASK-3543-e2e-closeout.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

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
      "path": ".github/workflows/e2e.yml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/e2e/plans/deterministic.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/e2e/plans/live.md",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_e2e_ci_plans.py",
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
- **Parallelism:** TASK-3545 owns its declared files for M9. TASK-3536 supplies exercise real sessions and offline minimal startup; TASK-3537 supplies exercise crash cleanup and concurrent worktree isolation; TASK-3540 supplies wire bounded live google agent mcp target and smoke; TASK-3543 supplies require validated e2e evidence before both closeout flows. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.
2. Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.
3. Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.
4. Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `.github/workflows/e2e.yml` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.

2. Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.

3. Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.

4. Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.
### `packages/ai-parrot-server/tests/e2e/plans/deterministic.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.

2. Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.

3. Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.

4. Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.
### `packages/ai-parrot-server/tests/e2e/plans/live.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.

2. Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.

3. Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.

4. Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.
### `tests/sdd_scripts/test_e2e_ci_plans.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Add cron 0 3 * * * and manual deterministic workflow; provision existing dependencies and local Redis, no provider secrets.
- [ ] Separate dispatch-only live job with explicit flag/key, protected secret access and BLOCKED missing prerequisite behavior.
- [ ] Use exact frozen scenario node IDs; no root suite, collection-error suppression or exploratory agents; upload artifacts on failure.
- [ ] Test plan selection and model/flag separation through real schema parsing; no static-only YAML substring assertions.
- [ ] Relevant spec criteria AC14 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_ci_plans.py -q`

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

Completed 2026-09-24. Implemented via a manual worktree + native sonnet `sdd-coder`
dispatch (the `parrot-sdd-coder` MCP engine was unresponsive at the time — see
FEAT-581 orchestration notes) and merged by hand (`git merge --no-ff`) after
verifying real delivery (exactly the 4 declared files, single commit).

Created `.github/workflows/e2e.yml` (deterministic nightly/manual job with no
provider secrets, local Redis provisioning, `set -o pipefail` on the plan run,
failure-only artifact upload; a separate `live` job gated on
`workflow_dispatch.inputs.run_live == 'true'`, the only job referencing
`secrets.GOOGLE_API_KEY`), `packages/ai-parrot-server/tests/e2e/plans/deterministic.md`
(wraps the 8 frozen deterministic node IDs from TASK-3535/3536/3537 as `required:
true`, plus TASK-3548's browser scenario as `required: false` since this task's
declared scope did not include provisioning a Node/pnpm/Playwright toolchain in
CI — flagged for a possible follow-up task if full M9 browser-lane CI
provisioning is wanted), `packages/ai-parrot-server/tests/e2e/plans/live.md`
(dedicated `policy: required` plan wrapping TASK-3540's frozen live node with
the default `LiveBudget`, so a missing live secret yields `BLOCKED`/exit 3
rather than a false pass when explicitly requested), and
`tests/sdd_scripts/test_e2e_ci_plans.py` (29 tests validating both plans
through the real `E2EPlan` loader and the workflow YAML structurally via
`yaml.safe_load`).

Tests: `pytest tests/sdd_scripts/test_e2e_ci_plans.py -q` → 29 passed (re-run
verified). Regression: `tests/sdd_scripts/test_e2e_spec_contract.py` +
`test_e2e_closeout_contract.py` + `test_e2e_ci_plans.py` → 76 passed, no
interference (re-run verified). `ruff check` / `black --check` clean.

No STOP conditions. One disclosed, in-scope deviation: browser-lane CI
provisioning deferred (see above), consistent with AC14 and this task's Scope.
