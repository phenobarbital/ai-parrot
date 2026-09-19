# TASK-3532: Capture exact pytest node and phase evidence

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3523, TASK-3526
**Assigned-to**: unassigned
**Module**: M5
**Spec acceptance criteria**: AC7, AC11

---

## Context

Implement the M5 deliverable **Capture exact pytest node and phase evidence** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Load explicitly via -p, never plugin auto-registration; consume run/control context supplied by the runner.
- Capture selected/collected node IDs plus setup/call/teardown results, xfail/xpass/skips, durations and exit status into structured atomic output.
- Test empty collection, collection error, deselection, duplicates, teardown failures and required skips with pytest subprocesses.
- Do not create clients/start targets during collection; absence of run context is a clear error for runner-specific fixtures.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/pytest_plugin.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_pytest_plugin.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/tests/conftest.py:169` — e2e and integration directory markers already exist. New suite opt-in must run before fixtures/clients. Signature: `def pytest_collection_modifyitems(config, items)`. Source SHA-256: `c5ffad60067f1764b985191b34567e0aafbe6d9c97166966399d46d56b45cb84`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3523 (`sdd/tasks/active/TASK-3523-e2e-evidence-verifier.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3526 (`sdd/tasks/active/TASK-3526-e2e-control-channel.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/pytest_plugin.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_pytest_plugin.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/tests/conftest.py#pytest_collection_modifyitems"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3532 owns its declared files for M5. TASK-3523 supplies evaluate exact coverage and validate immutable evidence; TASK-3526 supplies implement private supervisor control and stdio rpc channel. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Load explicitly via -p, never plugin auto-registration; consume run/control context supplied by the runner.
2. Capture selected/collected node IDs plus setup/call/teardown results, xfail/xpass/skips, durations and exit status into structured atomic output.
3. Test empty collection, collection error, deselection, duplicates, teardown failures and required skips with pytest subprocesses.
4. Do not create clients/start targets during collection; absence of run context is a clear error for runner-specific fixtures.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/src/parrot/e2e/pytest_plugin.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Load explicitly via -p, never plugin auto-registration; consume run/control context supplied by the runner.

2. Capture selected/collected node IDs plus setup/call/teardown results, xfail/xpass/skips, durations and exit status into structured atomic output.

3. Test empty collection, collection error, deselection, duplicates, teardown failures and required skips with pytest subprocesses.

4. Do not create clients/start targets during collection; absence of run context is a clear error for runner-specific fixtures.
### `packages/ai-parrot-server/tests/unit/e2e/test_pytest_plugin.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Load explicitly via -p, never plugin auto-registration; consume run/control context supplied by the runner.
- [ ] Capture selected/collected node IDs plus setup/call/teardown results, xfail/xpass/skips, durations and exit status into structured atomic output.
- [ ] Test empty collection, collection error, deselection, duplicates, teardown failures and required skips with pytest subprocesses.
- [ ] Do not create clients/start targets during collection; absence of run context is a clear error for runner-specific fixtures.
- [ ] Relevant spec criteria AC7, AC11 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_pytest_plugin.py -q`

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

Completed 2026-09-19. Implemented `parrot.e2e.pytest_plugin`, loaded only via
explicit `-p parrot.e2e.pytest_plugin` (no `pytest11` entry point — never
touches env/context at collection time). Invented and documented (nothing
fixed these names) the env-var contract `PARROT_E2E_RUN_ID`/`_OWNER_ID`/
`_CONTROL_SOCKET`/`_RESULTS_PATH` for the future M3 runner (TASK-3533) to
set. `load_run_context()` + `e2e_run_context`/`e2e_control_client` fixtures
consume context lazily at test setup, raising `E2EConfigError`
(`reason_code=run_context_missing`) naming every missing variable —
`--collect-only` succeeds regardless, and constructing `ControlClient`
never opens a socket. Hooks capture selected vs. collected node IDs,
per-phase (setup/call/teardown) outcomes, xfail/xpass/skip classification,
durations, collection errors, and exit status into an atomically-written
(tempfile+fsync+`os.replace`, mode 0600) JSON report when
`PARROT_E2E_RESULTS_PATH` is set. Outcome classification never lets a
teardown failure hide behind a passing call — verified via a real
subprocess test.

Bridge-report JSON schema (schema_version 1) documented in the module
docstring for TASK-3533: `run_id`, `owner_id`, `argv`, `selected_node_ids`,
`collected_node_ids`, `collection_errors`, `results[]`, `counts`,
`exit_status`, `started_at`, `completed_at`. `selected_node_ids` are raw
`::`-containing invocation-arg tokens (duplicates preserved);
`collected_node_ids` are pytest's final post-deselection `session.items` —
matches the subset invariant `parrot.e2e.evidence.verify_evidence` already
enforces. The plugin never synthesizes `blocked`/`missing` outcomes — only
what one pytest session directly observed.

Tests: `pytest packages/ai-parrot-server/tests/unit/e2e/test_pytest_plugin.py -q`
→ 18 passed, every subprocess-boundary scenario (empty collection,
collection error, deselection, duplicates, teardown failure, required
skip/xfail/xpass) exercised via a real `sys.executable -m pytest -p
parrot.e2e.pytest_plugin ...` subprocess. Full-directory regression:
`pytest packages/ai-parrot-server/tests/unit/e2e/ -q` → 372 passed, 4
skipped, no regression against TASK-3524–3531. No sibling-merge fallout.

No unresolved limitations. AC7/AC11 demonstrated by the contract tests.

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 1292.0s · Tokens: 246324 (combined)
