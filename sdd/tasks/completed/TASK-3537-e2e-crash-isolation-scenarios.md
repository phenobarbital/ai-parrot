# TASK-3537: Exercise crash cleanup and concurrent worktree isolation

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3535, TASK-3528, TASK-3531
**Assigned-to**: unassigned
**Module**: M5
**Spec acceptance criteria**: AC5, AC6

---

## Context

Implement the M5 deliverable **Exercise crash cleanup and concurrent worktree isolation** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Kill controller and supervisor separately at deterministic registration barriers and after readiness; verify watchdog cleanup.
- Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained unresolved cleanup failure.
- Run two worktrees concurrently with distinct state/ports/data and module origins; one owner down must leave the other alive.
- Use deterministic barriers and bounded deadlines, not brittle sleeps or broad process scans.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/e2e/test_supervisor.py` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `tests/mcp/test_mcp_local_e2e.py:72` — Legacy helpers illustrate pipes/EOF, but _recv currently uses a blocking readline despite a timeout argument; new supervisor must enforce a real deadline. Signature: `def _spawn(cwd: Path, *args: str) -> subprocess.Popen`. Source SHA-256: `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3535 (`sdd/tasks/active/TASK-3535-e2e-mcp-scenarios.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3528 (`sdd/tasks/active/TASK-3528-e2e-watchdog.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3531 (`sdd/tasks/active/TASK-3531-e2e-ui-browser-targets.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/tests/e2e/test_supervisor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager",
    "sym:tests/mcp/test_mcp_local_e2e.py#_spawn"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3537 owns its declared files for M5. TASK-3535 supplies add shared e2e fixtures and real mcp scenarios; TASK-3528 supplies enforce leases and recovery after controller/supervisor death; TASK-3531 supplies add isolated ui and owned obscura browser targets. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Kill controller and supervisor separately at deterministic registration barriers and after readiness; verify watchdog cleanup.
2. Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained unresolved cleanup failure.
3. Run two worktrees concurrently with distinct state/ports/data and module origins; one owner down must leave the other alive.
4. Use deterministic barriers and bounded deadlines, not brittle sleeps or broad process scans.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/tests/e2e/test_supervisor.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Kill controller and supervisor separately at deterministic registration barriers and after readiness; verify watchdog cleanup.
- [ ] Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained unresolved cleanup failure.
- [ ] Run two worktrees concurrently with distinct state/ports/data and module origins; one owner down must leave the other alive.
- [ ] Use deterministic barriers and bounded deadlines, not brittle sleeps or broad process scans.
- [ ] Relevant spec criteria AC5, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

- `packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death` — frozen integration node ID; no renaming without updating all plans.
- `packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown` — frozen integration node ID; no renaming without updating all plans.
- `packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent` — frozen integration node ID; no renaming without updating all plans.
- `packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass` — frozen integration node ID; no renaming without updating all plans.

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

Completed 2026-09-24 by native seat sonnet, attempt_uid
`87a263c16be0405587bf2b9fa8004ab9`. Delivered cleanly first attempt.

Created `packages/ai-parrot-server/tests/e2e/test_supervisor.py` (frozen
node IDs `test_controller_and_supervisor_death`,
`test_timeout_and_grandchild_teardown`, `test_two_worktrees_independent`,
`test_wrong_checkout_cannot_pass` — gated `PARROT_TEST_E2E=1`, real
subprocesses: killing controller at a deterministic registration barrier
and again after readiness, a hung target+grandchild process-group tree
forced to SIGKILL, a foreign/non-owned identity never signaled with
failure retained across repeat `stop()`, two independent
`E2ESupervisor`s over two worktrees proving one owner's `stop()` never
touches the sibling, and two synthetic worktrees with same-named modules
of different content proving PYTHONPATH-based module-origin isolation)
and `packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py`
(always-run fast contract complement, same four scope bullets against
synthetic `tmp_path` worktrees — this is the file named in Validation
Commands).

Tests:
- `pytest packages/ai-parrot-server/tests/unit/e2e/test_crash_probe_contract.py -q`
  → 5 passed.
- `PARROT_TEST_E2E=1 pytest packages/ai-parrot-server/tests/e2e/test_supervisor.py -q`
  → 4 passed (all frozen node IDs).
- `pytest packages/ai-parrot-server/tests/unit/e2e/test_supervisor.py -q`
  (pre-existing file, untouched by this task) → 19 passed standalone.
- Full-sweep regression check on `tests/unit/e2e/` showed ~18 intermittent
  failures, but confirmed as pre-existing resource-contention flakiness
  when many real-subprocess tests run together in this sandbox, NOT a
  regression from this task: the failure set differs between consecutive
  runs, and `test_supervisor.py` (untouched by TASK-3537) passes 19/19
  alone but fails intermittently only under full-sweep load. Filed
  `issue:e21ec87c6aba` (test isolation/resource contention) and
  `issue:64ea6d91b811` (`sdd/state/e2e/` missing from `.gitignore`, also
  flagged by the implementing agent) — both out of this task's scope.
- `ruff check` / `black --check` clean on both new files.

Only the 2 declared files touched (880 insertions); nothing under `sdd/`
committed (test-run byproducts under `sdd/state/e2e/` were cleaned before
commit). No production/source files touched.

No unresolved limitations. AC5/AC6 demonstrated by the new test suites.
