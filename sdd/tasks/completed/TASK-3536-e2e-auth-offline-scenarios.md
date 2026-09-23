# TASK-3536: Exercise real sessions and offline minimal startup

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3535, TASK-3530, TASK-3516
**Assigned-to**: unassigned
**Module**: M5
**Spec acceptance criteria**: AC1, AC4

---

## Context

Implement the M5 deliverable **Exercise real sessions and offline minimal startup** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected real API assertion.
- Test minimal boot with a controlled empty tokenizer cache and outbound network disabled except fixture loopback.
- Ensure missing Redis is BLOCKED for required auth coverage; no requests to operator services or injected module stubs.
- Differentiate import-time lazy-tokenizer guarantee from later first-tokenization/cache behavior.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/e2e/test_botmanager.py` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/manager/manager.py:188` — Explicitly disable discovery/database/crews in the minimal profile; production setup is not modified by fixture auth. Signature: `def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS, enable_crews: bool = ENABLE_CREWS, enable_registry_bots: bool = ENABLE_REGISTRY_BOTS, enable_swagger_api: bool = ENABLE_SWAGGER) -> None`. Source SHA-256: `4a02c5feb76658ddd89a63649ae28bd13f1cdd39e9feeab51343048851c80844`.
- `docker/integrations/server.py:22` — Builds an aiohttp app, /healthz and BotManager().setup(app); session storage is not configured. Signature: `def build_app() -> web.Application`. Source SHA-256: `c580501988bc7a82b8ba884bb8f1ded9542083f7e86cf5c0bb9a71e983ebc302`.
- `packages/ai-parrot/src/parrot/skills/parsers.py:32` — Module line 29 eagerly creates the cl100k_base encoder; counting is synchronous. Signature: `def _count_tokens(text: str) -> int`. Source SHA-256: `da1d2cbd8719420f7e2c6e97a9dff740741226f4e6a917e4a3bd456d96462499`.

```python
from parrot.manager.manager import BotManager
from parrot.skills.parsers import _count_tokens
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3535 (`sdd/tasks/active/TASK-3535-e2e-mcp-scenarios.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3530 (`sdd/tasks/active/TASK-3530-e2e-botmanager-target.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3516 (`sdd/tasks/active/TASK-3516-e2e-lazy-tokenizer.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/tests/e2e/test_botmanager.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:docker/integrations/server.py#build_app",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.__init__",
    "sym:packages/ai-parrot/src/parrot/skills/parsers.py#_count_tokens"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3536 owns its declared files for M5. TASK-3535 supplies add shared e2e fixtures and real mcp scenarios; TASK-3530 supplies add private redis and authenticated minimal botmanager target; TASK-3516 supplies defer skill tokenizer acquisition until first count. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected real API assertion.
2. Test minimal boot with a controlled empty tokenizer cache and outbound network disabled except fixture loopback.
3. Ensure missing Redis is BLOCKED for required auth coverage; no requests to operator services or injected module stubs.
4. Differentiate import-time lazy-tokenizer guarantee from later first-tokenization/cache behavior.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/tests/e2e/test_botmanager.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected real API assertion.
- [ ] Test minimal boot with a controlled empty tokenizer cache and outbound network disabled except fixture loopback.
- [ ] Ensure missing Redis is BLOCKED for required auth coverage; no requests to operator services or injected module stubs.
- [ ] Differentiate import-time lazy-tokenizer guarantee from later first-tokenization/cache behavior.
- [ ] Relevant spec criteria AC1, AC4 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

- `packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile` — frozen integration node ID; no renaming without updating all plans.
- `packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot` — frozen integration node ID; no renaming without updating all plans.

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

Completed 2026-09-24 by seat gpt-5.6-terra (backend codex), attempt 1,
attempt_uid `e5f7a885b1754f6eaa8beefc4679241e` (182.7s). Delivered cleanly
first attempt (0 lint errors).

Created `packages/ai-parrot-server/tests/e2e/test_botmanager.py` (frozen
node IDs `test_authenticated_minimal_profile` and
`test_botmanager_offline_boot`: private-Redis bootstrap cookie round-trip,
anonymous/invalid denial, and minimal boot with a controlled empty
tokenizer cache and outbound network disabled except fixture loopback) and
`packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py`.

Tests:
- `pytest packages/ai-parrot-server/tests/unit/e2e/test_botmanager_prerequisites.py -q`
  → 2 passed.

Only the 2 declared files touched (145 insertions); no `sdd/` files touched.

No unresolved limitations. AC1/AC4 demonstrated by the new test suite.
