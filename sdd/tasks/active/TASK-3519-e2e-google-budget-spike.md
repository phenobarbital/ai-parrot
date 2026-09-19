# TASK-3519: Audit every Google generation path for enforceable budgets

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Module**: M6
**Spec acceptance criteria**: AC11, AC17

---

## Context

Implement the M6 deliverable **Audit every Google generation path for enforceable budgets** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

**Research completion rule:** record a concrete verified contract, not a proposed assumption. Missing executable/service access keeps dependent implementation gated. Full-profile measurement alone may finish with an explicit BLOCKED/opt-in disposition as AC16 permits. No paid model request is required for this research.

## Scope

- Enumerate nonstreaming initial, continuation, repair, retry/fallback and hidden SDK requests with exact source anchors.
- Verify SDK retry/AFC disabling and how serialized request bytes include system/history/tools/results; record concrete wrapper seams and error propagation.
- Freeze GenerationBudget constructor, exception type and optional client hook placement without changing AbstractClient; use counting local fake transport, no paid calls.
- Document unsupported budgeted modes and legacy no-hook behavior; unresolved bypasses block the guard implementation.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-581/research/google-budget.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:631` — Provider SDK use belongs here. Initial ask send is line 3400; small MAX_TOKENS retry raises cap to 8192 at 3409. Budget mode must prevent that growth. Signature: `async def get_client(self, model: str = None, **kwargs) -> genai.Client`. Source SHA-256: `6ee140ced87407e91f5a930223b5836b1923a52b5effad954c83ee054f3f2df5`.
- `packages/ai-parrot/src/parrot/clients/factory.py:257` — Satellite discovered lazily; unknown provider raises ImportError, not a silent fallback. Signature: `def create(llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient`. Source SHA-256: `d49371904bf501f823f6b812627f5e5d7aacf37b66921325d33a2c0500560c55`.

```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.factory import LLMFactory
```

### Dependency Interfaces (new, not existing)

None.

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
      "path": "sdd/state/FEAT-581/research/google-budget.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3519 owns its declared files for M6. No task dependencies; uses verified existing contracts only. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Enumerate nonstreaming initial, continuation, repair, retry/fallback and hidden SDK requests with exact source anchors.
2. Verify SDK retry/AFC disabling and how serialized request bytes include system/history/tools/results; record concrete wrapper seams and error propagation.
3. Freeze GenerationBudget constructor, exception type and optional client hook placement without changing AbstractClient; use counting local fake transport, no paid calls.
4. Document unsupported budgeted modes and legacy no-hook behavior; unresolved bypasses block the guard implementation.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `sdd/state/FEAT-581/research/google-budget.md` (CREATE)

Write reproducible research evidence: baseline/version and source anchors, exact commands, sanitized observations, selected contract, rejected assumptions, and PASS/BLOCKED for every required question. Store bulky logs in artifacts/logs/. A blocked question cannot unlock dependent implementation.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Enumerate nonstreaming initial, continuation, repair, retry/fallback and hidden SDK requests with exact source anchors.
- [ ] Verify SDK retry/AFC disabling and how serialized request bytes include system/history/tools/results; record concrete wrapper seams and error propagation.
- [ ] Freeze GenerationBudget constructor, exception type and optional client hook placement without changing AbstractClient; use counting local fake transport, no paid calls.
- [ ] Document unsupported budgeted modes and legacy no-hook behavior; unresolved bypasses block the guard implementation.
- [ ] Relevant spec criteria AC11, AC17 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_google_client.py -q`

## Test Specification

Research tasks additionally require the concrete experiments in Scope; existing file-level tests are compatibility checks, not proof the spike succeeded.

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
