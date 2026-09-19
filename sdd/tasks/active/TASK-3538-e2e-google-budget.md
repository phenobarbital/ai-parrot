# TASK-3538: Implement shared generation budget primitive

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3519, TASK-3520
**Assigned-to**: unassigned
**Module**: M6
**Spec acceptance criteria**: AC11, AC17

---

## Context

Implement the M6 deliverable **Implement shared generation budget primitive** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement GenerationBudget and non-retryable GenerationBudgetExceeded using the audited constructor/error contract.
- Reserve attempts atomically before dispatch, enforce request bytes/output ceiling/deadline, and retain usage counters after failure.
- Support one shared run counter across scenarios/clients; exact token billing is not inferred from bytes.
- Use concurrency and boundary tests without credentials/network; exhaustion cannot reserve or issue another attempt.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/budget.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-client-google/tests/unit/test_generation_budget.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:631` — Provider SDK use belongs here. Initial ask send is line 3400; small MAX_TOKENS retry raises cap to 8192 at 3409. Budget mode must prevent that growth. Signature: `async def get_client(self, model: str = None, **kwargs) -> genai.Client`. Source SHA-256: `6ee140ced87407e91f5a930223b5836b1923a52b5effad954c83ee054f3f2df5`.

```python
from parrot.clients.google import GoogleGenAIClient
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3519 (`sdd/tasks/active/TASK-3519-e2e-google-budget-spike.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3520 (`sdd/tasks/active/TASK-3520-e2e-models.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `GenerationBudget.reserve(*, request_bytes: int, output_tokens: int) -> None (async)`

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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/budget.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/test_generation_budget.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3538 owns its declared files for M6. TASK-3519 supplies audit every google generation path for enforceable budgets; TASK-3520 supplies define strict e2e schemas and typed errors. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement GenerationBudget and non-retryable GenerationBudgetExceeded using the audited constructor/error contract.
2. Reserve attempts atomically before dispatch, enforce request bytes/output ceiling/deadline, and retain usage counters after failure.
3. Support one shared run counter across scenarios/clients; exact token billing is not inferred from bytes.
4. Use concurrency and boundary tests without credentials/network; exhaustion cannot reserve or issue another attempt.

### Fixed interfaces

- `GenerationBudget.reserve(*, request_bytes: int, output_tokens: int) -> None (async)`

### `packages/ai-parrot-client-google/src/parrot/clients/google/budget.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement GenerationBudget and non-retryable GenerationBudgetExceeded using the audited constructor/error contract.

2. Reserve attempts atomically before dispatch, enforce request bytes/output ceiling/deadline, and retain usage counters after failure.

3. Support one shared run counter across scenarios/clients; exact token billing is not inferred from bytes.

4. Use concurrency and boundary tests without credentials/network; exhaustion cannot reserve or issue another attempt.
### `packages/ai-parrot-client-google/tests/unit/test_generation_budget.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement GenerationBudget and non-retryable GenerationBudgetExceeded using the audited constructor/error contract.
- [ ] Reserve attempts atomically before dispatch, enforce request bytes/output ceiling/deadline, and retain usage counters after failure.
- [ ] Support one shared run counter across scenarios/clients; exact token billing is not inferred from bytes.
- [ ] Use concurrency and boundary tests without credentials/network; exhaustion cannot reserve or issue another attempt.
- [ ] Relevant spec criteria AC11, AC17 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/test_generation_budget.py -q`

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
