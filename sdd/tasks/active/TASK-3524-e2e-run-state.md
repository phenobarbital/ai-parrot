# TASK-3524: Persist locked run state and validate process identity

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3520, TASK-3517
**Assigned-to**: unassigned
**Module**: M3
**Spec acceptance criteria**: AC5, AC6

---

## Context

Implement the M3 deliverable **Persist locked run state and validate process identity** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement worktree/run-contained mode-0600 atomic state and mode-0700 directories, with advisory locks for competing commands.
- Read boot ID, PID/PGID and creation time; validate owner/worktree before any signaling authorization.
- Persist starting immediately and retain failed/unreaped state; adopted process identity remains non-owned.
- Test PID reuse, stale state, concurrent down and symlink/path attacks without signaling unrelated processes.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/state.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_state.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3520 (`sdd/tasks/active/TASK-3520-e2e-models.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3517 (`sdd/tasks/active/TASK-3517-e2e-lifecycle-spike.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `read_state(run_id: str, *, worktree: Path) -> RunState`
- `write_state(state: RunState, *, worktree: Path) -> None`

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/state.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_state.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3524 owns its declared files for M3. TASK-3520 supplies define strict e2e schemas and typed errors; TASK-3517 supplies verify supervisor crash recovery and obscura isolation contracts. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement worktree/run-contained mode-0600 atomic state and mode-0700 directories, with advisory locks for competing commands.
2. Read boot ID, PID/PGID and creation time; validate owner/worktree before any signaling authorization.
3. Persist starting immediately and retain failed/unreaped state; adopted process identity remains non-owned.
4. Test PID reuse, stale state, concurrent down and symlink/path attacks without signaling unrelated processes.

### Fixed interfaces

- `read_state(run_id: str, *, worktree: Path) -> RunState`
- `write_state(state: RunState, *, worktree: Path) -> None`

### `packages/ai-parrot-server/src/parrot/e2e/state.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement worktree/run-contained mode-0600 atomic state and mode-0700 directories, with advisory locks for competing commands.

2. Read boot ID, PID/PGID and creation time; validate owner/worktree before any signaling authorization.

3. Persist starting immediately and retain failed/unreaped state; adopted process identity remains non-owned.

4. Test PID reuse, stale state, concurrent down and symlink/path attacks without signaling unrelated processes.
### `packages/ai-parrot-server/tests/unit/e2e/test_state.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement worktree/run-contained mode-0600 atomic state and mode-0700 directories, with advisory locks for competing commands.
- [ ] Read boot ID, PID/PGID and creation time; validate owner/worktree before any signaling authorization.
- [ ] Persist starting immediately and retain failed/unreaped state; adopted process identity remains non-owned.
- [ ] Test PID reuse, stale state, concurrent down and symlink/path attacks without signaling unrelated processes.
- [ ] Relevant spec criteria AC5, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_state.py -q`

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
