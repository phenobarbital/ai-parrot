# TASK-3517: Verify supervisor crash recovery and Obscura isolation contracts

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Module**: M3/M4
**Spec acceptance criteria**: AC5, AC6, AC13

---

## Context

Implement the M3/M4 deliverable **Verify supervisor crash recovery and Obscura isolation contracts** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

**Research completion rule:** record a concrete verified contract, not a proposed assumption. Missing executable/service access keeps dependent implementation gated. Full-profile measurement alone may finish with an explicit BLOCKED/opt-in disposition as AC16 permits. No paid model request is required for this research.

## Scope

- Reproduce controller/supervisor death before and after target registration using disposable local processes; record event ordering and bounded recovery.
- Verify actual Obscura version/help, private profile argument and DevTools attachment; preserve the newly added manager signal/atexit behavior.
- Freeze watchdog registration/ACK/heartbeat control schemas, private socket request shapes and concrete owned browser argv in the report; absent binaries leave that contract BLOCKED.
- Document the launch-before-registration crash window and tested recovery; do not mark resolved using prose alone.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-581/research/lifecycle.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:32` — Existing dataclass has no profile parameter; determine supported binary flags in the spike. Signature: `ObscuraProcessConfig(binary_path: str, port: int = 9222, host: str = "127.0.0.1", stealth: bool = False, allow_private_network: bool = False, attach_only: bool = False, startup_timeout: float = 10.0)`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.
- `tests/mcp/test_mcp_local_e2e.py:72` — Legacy helpers illustrate pipes/EOF, but _recv currently uses a blocking readline despite a timeout argument; new supervisor must enforce a real deadline. Signature: `def _spawn(cwd: Path, *args: str) -> subprocess.Popen`. Source SHA-256: `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
from parrot.mcp.obscura import ObscuraProcessConfig
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
      "path": "sdd/state/FEAT-581/research/lifecycle.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessConfig",
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
- **Parallelism:** TASK-3517 owns its declared files for M3/M4. No task dependencies; uses verified existing contracts only. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Reproduce controller/supervisor death before and after target registration using disposable local processes; record event ordering and bounded recovery.
2. Verify actual Obscura version/help, private profile argument and DevTools attachment; preserve the newly added manager signal/atexit behavior.
3. Freeze watchdog registration/ACK/heartbeat control schemas, private socket request shapes and concrete owned browser argv in the report; absent binaries leave that contract BLOCKED.
4. Document the launch-before-registration crash window and tested recovery; do not mark resolved using prose alone.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `sdd/state/FEAT-581/research/lifecycle.md` (CREATE)

Write reproducible research evidence: baseline/version and source anchors, exact commands, sanitized observations, selected contract, rejected assumptions, and PASS/BLOCKED for every required question. Store bulky logs in artifacts/logs/. A blocked question cannot unlock dependent implementation.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Reproduce controller/supervisor death before and after target registration using disposable local processes; record event ordering and bounded recovery.
- [ ] Verify actual Obscura version/help, private profile argument and DevTools attachment; preserve the newly added manager signal/atexit behavior.
- [ ] Freeze watchdog registration/ACK/heartbeat control schemas, private socket request shapes and concrete owned browser argv in the report; absent binaries leave that contract BLOCKED.
- [ ] Document the launch-before-registration crash window and tested recovery; do not mark resolved using prose alone.
- [ ] Relevant spec criteria AC5, AC6, AC13 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/mcp/test_obscura.py -q`

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
