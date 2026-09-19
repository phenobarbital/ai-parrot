# TASK-3530: Add private Redis and authenticated minimal BotManager target

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3518, TASK-3525, TASK-3528
**Assigned-to**: unassigned
**Module**: M4
**Spec acceptance criteria**: AC4, AC6

---

## Context

Implement the M4 deliverable **Add private Redis and authenticated minimal BotManager target** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Implement only the session/route payload frozen by the verified session research report.
- Provision private persistence-disabled Redis with distinct port/data directory and pre-import host/port/db env; never flush shared Redis.
- Build minimal aiohttp entry point with discovery/database/crews disabled, health and E2E-only secret-guarded bootstrap/protected fixture routes.
- Use real stored sessions and selected real API route; strip external integration configuration; missing binary/prerequisites are explicit BLOCKED.
- Full profile requires explicit command/readiness settings; never assume run.py exposes healthz.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/targets/redis.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/src/parrot/e2e/targets/botmanager.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_botmanager_target.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/manager/manager.py:188` — Explicitly disable discovery/database/crews in the minimal profile; production setup is not modified by fixture auth. Signature: `def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS, enable_crews: bool = ENABLE_CREWS, enable_registry_bots: bool = ENABLE_REGISTRY_BOTS, enable_swagger_api: bool = ENABLE_SWAGGER) -> None`. Source SHA-256: `4a02c5feb76658ddd89a63649ae28bd13f1cdd39e9feeab51343048851c80844`.
- `docker/integrations/server.py:22` — Builds an aiohttp app, /healthz and BotManager().setup(app); session storage is not configured. Signature: `def build_app() -> web.Application`. Source SHA-256: `c580501988bc7a82b8ba884bb8f1ded9542083f7e86cf5c0bb9a71e983ebc302`.

```python
from parrot.manager.manager import BotManager
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3518 (`sdd/tasks/active/TASK-3518-e2e-session-spike.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3525 (`sdd/tasks/active/TASK-3525-e2e-target-protocol.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3528 (`sdd/tasks/active/TASK-3528-e2e-watchdog.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/redis.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/botmanager.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_botmanager_target.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:docker/integrations/server.py#build_app",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.__init__"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3530 owns its declared files for M4. TASK-3518 supplies verify real navigator-session redis and fixture authentication; TASK-3525 supplies define target adapter protocol and lazy fixed registry; TASK-3528 supplies enforce leases and recovery after controller/supervisor death. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Implement only the session/route payload frozen by the verified session research report.
2. Provision private persistence-disabled Redis with distinct port/data directory and pre-import host/port/db env; never flush shared Redis.
3. Build minimal aiohttp entry point with discovery/database/crews disabled, health and E2E-only secret-guarded bootstrap/protected fixture routes.
4. Use real stored sessions and selected real API route; strip external integration configuration; missing binary/prerequisites are explicit BLOCKED.
5. Full profile requires explicit command/readiness settings; never assume run.py exposes healthz.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/src/parrot/e2e/targets/redis.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement only the session/route payload frozen by the verified session research report.

2. Provision private persistence-disabled Redis with distinct port/data directory and pre-import host/port/db env; never flush shared Redis.

3. Build minimal aiohttp entry point with discovery/database/crews disabled, health and E2E-only secret-guarded bootstrap/protected fixture routes.

4. Use real stored sessions and selected real API route; strip external integration configuration; missing binary/prerequisites are explicit BLOCKED.

5. Full profile requires explicit command/readiness settings; never assume run.py exposes healthz.
### `packages/ai-parrot-server/src/parrot/e2e/targets/botmanager.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Implement only the session/route payload frozen by the verified session research report.

2. Provision private persistence-disabled Redis with distinct port/data directory and pre-import host/port/db env; never flush shared Redis.

3. Build minimal aiohttp entry point with discovery/database/crews disabled, health and E2E-only secret-guarded bootstrap/protected fixture routes.

4. Use real stored sessions and selected real API route; strip external integration configuration; missing binary/prerequisites are explicit BLOCKED.

5. Full profile requires explicit command/readiness settings; never assume run.py exposes healthz.
### `packages/ai-parrot-server/tests/unit/e2e/test_botmanager_target.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Implement only the session/route payload frozen by the verified session research report.
- [ ] Provision private persistence-disabled Redis with distinct port/data directory and pre-import host/port/db env; never flush shared Redis.
- [ ] Build minimal aiohttp entry point with discovery/database/crews disabled, health and E2E-only secret-guarded bootstrap/protected fixture routes.
- [ ] Use real stored sessions and selected real API route; strip external integration configuration; missing binary/prerequisites are explicit BLOCKED.
- [ ] Full profile requires explicit command/readiness settings; never assume run.py exposes healthz.
- [ ] Relevant spec criteria AC4, AC6 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_botmanager_target.py -q`

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
