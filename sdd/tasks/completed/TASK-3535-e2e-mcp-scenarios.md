# TASK-3535: Add shared E2E fixtures and real MCP scenarios

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3534
**Assigned-to**: unassigned
**Module**: M5
**Spec acceptance criteria**: AC3, AC5, AC11

---

## Context

Implement the M5 deliverable **Add shared E2E fixtures and real MCP scenarios** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Create suite-local opt-in fixtures before any spawn; use existing markers and explicit supervisor context.
- Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF behavior.
- Use async client operations and bounded reads; target processes import clean source rather than pytest module stubs.
- Fixtures guarantee owner cleanup under assertion failure and preserve evidence/log paths.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/e2e/conftest.py` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/e2e/test_mcp_http.py` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py` | CREATE | Targeted test coverage |
| `packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot-server/tests/conftest.py:169` — e2e and integration directory markers already exist. New suite opt-in must run before fixtures/clients. Signature: `def pytest_collection_modifyitems(config, items)`. Source SHA-256: `c5ffad60067f1764b985191b34567e0aafbe6d9c97166966399d46d56b45cb84`.
- `tests/mcp/test_mcp_local_e2e.py:72` — Legacy helpers illustrate pipes/EOF, but _recv currently uses a blocking readline despite a timeout argument; new supervisor must enforce a real deadline. Signature: `def _spawn(cwd: Path, *args: str) -> subprocess.Popen`. Source SHA-256: `4849a8cf317883d64dcc0c2f9c41b6dec4ebd7ac646d1506a48ae3606e03d1de`.
- `packages/ai-parrot-server/src/parrot/mcp/server.py:36` — Transport selection and ownership already exist; this wrapper is not a supervisor. Signature: `MCPServer(config: MCPServerConfig, parent_app: Optional[web.Application] = None); register_tools(tools); async start(); async stop()`. Source SHA-256: `73637e33dfd6bc014a1ef7c246bb952136ef1d06a3c5f25c173493bd6afe46af`.

```python
from parrot.mcp.server import MCPServer
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3534 (`sdd/tasks/active/TASK-3534-e2e-cli.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": "packages/ai-parrot-server/tests/e2e/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/e2e/test_mcp_http.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/server.py#MCPServer",
    "sym:packages/ai-parrot-server/tests/conftest.py#pytest_collection_modifyitems",
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
- **Parallelism:** TASK-3535 owns its declared files for M5. TASK-3534 supplies expose lazy e2e run verify and lifecycle commands. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Create suite-local opt-in fixtures before any spawn; use existing markers and explicit supervisor context.
2. Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF behavior.
3. Use async client operations and bounded reads; target processes import clean source rather than pytest module stubs.
4. Fixtures guarantee owner cleanup under assertion failure and preserve evidence/log paths.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/tests/e2e/conftest.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `packages/ai-parrot-server/tests/e2e/test_mcp_http.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Create suite-local opt-in fixtures before any spawn; use existing markers and explicit supervisor context.
- [ ] Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF behavior.
- [ ] Use async client operations and bounded reads; target processes import clean source rather than pytest module stubs.
- [ ] Fixtures guarantee owner cleanup under assertion failure and preserve evidence/log paths.
- [ ] Relevant spec criteria AC3, AC5, AC11 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

- `packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops` — frozen integration node ID; no renaming without updating all plans.
- `packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof` — frozen integration node ID; no renaming without updating all plans.

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
attempt_uid `e08f31ed59e340c0a1951eb823b11e5f` (356.8s). Delivery merged
cleanly first attempt (0 lint errors).

Created `packages/ai-parrot-server/tests/e2e/conftest.py` (suite-local
opt-in fixtures before any spawn, using the existing e2e/integration
markers and an explicit supervisor context),
`packages/ai-parrot-server/tests/e2e/test_mcp_http.py` (frozen node ID
`test_http_cli_stays_alive_and_stops`, real HTTP initialize/list/tool-effect
checks), `packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py` (frozen
node ID `test_stdio_tool_roundtrip_and_eof`, persistent stdio JSON
purity/EOF behavior with a real deadline, not the legacy blocking
`_recv`), and `packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py`.

Tests:
- `pytest packages/ai-parrot-server/tests/unit/e2e/test_fixture_opt_in.py -q`
  → 2 passed.
- Regression: `pytest packages/ai-parrot-server/tests/unit/e2e/ -q` →
  420 passed, 4 skipped, no regressions.

Only the 4 declared files touched (304 insertions); no `sdd/` files
touched. Engine lint autofix (black, commit `3e2eaae5e`).

No unresolved limitations. AC3/AC5/AC11 demonstrated by the new test suite.
