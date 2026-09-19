# TASK-3531: Add isolated UI and owned Obscura browser targets

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3517, TASK-3525, TASK-3528, TASK-3530
**Assigned-to**: unassigned
**Module**: M4
**Spec acceptance criteria**: AC6, AC13

---

## Context

Implement the M4 deliverable **Add isolated UI and owned Obscura browser targets** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Apply verified private-profile binary flags, unique CDP port and loopback endpoint; retain sole supervisor ownership.
- Implement explicit exploratory-only adoption that never transfers kill ownership; reject adoption for deterministic browser checks.
- Build/preview UI with PUBLIC_API_URL set beforehand and generated output isolated from tracked source; verify backend/proxy reachability.
- Preflight versions/binaries without auto-install; expose endpoint for DevTools attach and capture nonsecret environment fingerprints.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/targets/ui.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_ui_browser_targets.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:32` — Existing dataclass has no profile parameter; determine supported binary flags in the spike. Signature: `ObscuraProcessConfig(binary_path: str, port: int = 9222, host: str = "127.0.0.1", stealth: bool = False, allow_private_network: bool = False, attach_only: bool = False, startup_timeout: float = 10.0)`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `packages/ai-parrot-server/ui/vite.config.ts:45` — PUBLIC_API_URL configured before build; base=/admin/; server.proxy routes /api; generated outDir at ../src/parrot/server/ui/dist. Source SHA-256: `fa616cf5018be3b4cffeac4431381a9b3835c84313d4679ba0656d0218dba548`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
from parrot.mcp.obscura import ObscuraProcessConfig
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3517 (`sdd/tasks/active/TASK-3517-e2e-lifecycle-spike.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3525 (`sdd/tasks/active/TASK-3525-e2e-target-protocol.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3528 (`sdd/tasks/active/TASK-3528-e2e-watchdog.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3530 (`sdd/tasks/active/TASK-3530-e2e-botmanager-target.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/ui.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/targets/browser.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_ui_browser_targets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessConfig",
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
- **Parallelism:** TASK-3531 owns its declared files for M4. TASK-3517 supplies verify supervisor crash recovery and obscura isolation contracts; TASK-3525 supplies define target adapter protocol and lazy fixed registry; TASK-3528 supplies enforce leases and recovery after controller/supervisor death; TASK-3530 supplies add private redis and authenticated minimal botmanager target. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Apply verified private-profile binary flags, unique CDP port and loopback endpoint; retain sole supervisor ownership.
2. Implement explicit exploratory-only adoption that never transfers kill ownership; reject adoption for deterministic browser checks.
3. Build/preview UI with PUBLIC_API_URL set beforehand and generated output isolated from tracked source; verify backend/proxy reachability.
4. Preflight versions/binaries without auto-install; expose endpoint for DevTools attach and capture nonsecret environment fingerprints.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/src/parrot/e2e/targets/ui.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Apply verified private-profile binary flags, unique CDP port and loopback endpoint; retain sole supervisor ownership.

2. Implement explicit exploratory-only adoption that never transfers kill ownership; reject adoption for deterministic browser checks.

3. Build/preview UI with PUBLIC_API_URL set beforehand and generated output isolated from tracked source; verify backend/proxy reachability.

4. Preflight versions/binaries without auto-install; expose endpoint for DevTools attach and capture nonsecret environment fingerprints.
### `packages/ai-parrot-server/src/parrot/e2e/targets/browser.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Apply verified private-profile binary flags, unique CDP port and loopback endpoint; retain sole supervisor ownership.

2. Implement explicit exploratory-only adoption that never transfers kill ownership; reject adoption for deterministic browser checks.

3. Build/preview UI with PUBLIC_API_URL set beforehand and generated output isolated from tracked source; verify backend/proxy reachability.

4. Preflight versions/binaries without auto-install; expose endpoint for DevTools attach and capture nonsecret environment fingerprints.
### `packages/ai-parrot-server/tests/unit/e2e/test_ui_browser_targets.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Apply verified private-profile binary flags, unique CDP port and loopback endpoint; retain sole supervisor ownership.
- [ ] Implement explicit exploratory-only adoption that never transfers kill ownership; reject adoption for deterministic browser checks.
- [ ] Build/preview UI with PUBLIC_API_URL set beforehand and generated output isolated from tracked source; verify backend/proxy reachability.
- [ ] Preflight versions/binaries without auto-install; expose endpoint for DevTools attach and capture nonsecret environment fingerprints.
- [ ] Relevant spec criteria AC6, AC13 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_ui_browser_targets.py -q`

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
