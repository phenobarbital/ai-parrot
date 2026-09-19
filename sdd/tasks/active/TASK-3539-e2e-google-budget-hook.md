# TASK-3539: Guard every budgeted Google ask request and retry

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3538
**Assigned-to**: unassigned
**Module**: M6
**Spec acceptance criteria**: AC11, AC17

---

## Context

Implement the M6 deliverable **Guard every budgeted Google ask request and retry** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Accept optional generation_budget; guard all audit-identified initial/continuation/repair/retry sends before network.
- Disable SDK retries/AFC in budget mode; clamp MAX_TOKENS growth, reject unsupported modes/media/cache/grounding and never fallback after exhaustion.
- Compute bytes over full rendered payload/history/system/tool schema/results; propagate budget exceptions through broad retry handlers.
- Counting fake transport proves actual dispatched request count and zero extra sends after exhaustion; existing no-hook behavior remains unchanged.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-client-google/tests/unit/test_budgeted_ask.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:631` — Provider SDK use belongs here. Initial ask send is line 3400; small MAX_TOKENS retry raises cap to 8192 at 3409. Budget mode must prevent that growth. Signature: `async def get_client(self, model: str = None, **kwargs) -> genai.Client`. Source SHA-256: `6ee140ced87407e91f5a930223b5836b1923a52b5effad954c83ee054f3f2df5`.
- `packages/ai-parrot/src/parrot/clients/factory.py:257` — Satellite discovered lazily; unknown provider raises ImportError, not a silent fallback. Signature: `def create(llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient`. Source SHA-256: `d49371904bf501f823f6b812627f5e5d7aacf37b66921325d33a2c0500560c55`.

```python
from parrot.clients.google import GoogleGenAIClient
from parrot.clients.factory import LLMFactory
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3538 (`sdd/tasks/active/TASK-3538-e2e-google-budget.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` current SHA-256: `6ee140ced87407e91f5a930223b5836b1923a52b5effad954c83ee054f3f2df5`; re-read at execution because other features may change it.

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
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/test_budgeted_ask.py",
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
- **Parallelism:** TASK-3539 owns its declared files for M6. TASK-3538 supplies implement shared generation budget primitive. Exclusive prerequisite/shared-orchestration edit; do not co-schedule.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Accept optional generation_budget; guard all audit-identified initial/continuation/repair/retry sends before network.
2. Disable SDK retries/AFC in budget mode; clamp MAX_TOKENS growth, reject unsupported modes/media/cache/grounding and never fallback after exhaustion.
3. Compute bytes over full rendered payload/history/system/tool schema/results; propagate budget exceptions through broad retry handlers.
4. Counting fake transport proves actual dispatched request count and zero extra sends after exhaustion; existing no-hook behavior remains unchanged.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Accept optional generation_budget; guard all audit-identified initial/continuation/repair/retry sends before network.

2. Disable SDK retries/AFC in budget mode; clamp MAX_TOKENS growth, reject unsupported modes/media/cache/grounding and never fallback after exhaustion.

3. Compute bytes over full rendered payload/history/system/tool schema/results; propagate budget exceptions through broad retry handlers.

4. Counting fake transport proves actual dispatched request count and zero extra sends after exhaustion; existing no-hook behavior remains unchanged.
### `packages/ai-parrot-client-google/tests/unit/test_budgeted_ask.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Accept optional generation_budget; guard all audit-identified initial/continuation/repair/retry sends before network.
- [ ] Disable SDK retries/AFC in budget mode; clamp MAX_TOKENS growth, reject unsupported modes/media/cache/grounding and never fallback after exhaustion.
- [ ] Compute bytes over full rendered payload/history/system/tool schema/results; propagate budget exceptions through broad retry handlers.
- [ ] Counting fake transport proves actual dispatched request count and zero extra sends after exhaustion; existing no-hook behavior remains unchanged.
- [ ] Relevant spec criteria AC11, AC17 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-client-google/tests/unit/test_budgeted_ask.py -q`

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
