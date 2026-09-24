# TASK-3508: Verify pinned Pyright, raw MCP and worktree isolation

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3507
**Assigned-to**: unassigned

## Context

Implement M1–M4 of the approved specification: verify pinned pyright, raw mcp and worktree isolation. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Add real Pyright 1.1.414 fixtures with aliases, inheritance, duplicate names, PEP 420 namespace roots and non-target dependency changes.
- Exercise baseline/error/removal transitions including versioned empty publications; missing executable skips ordinary offline runs only, never qualifies acceptance.
- Drive raw local MCP initialize/list/call/EOF against the complete toolkit, asserting pure protocol stdout and no surviving child.
- Test two divergent worktrees and simultaneous callers; assert distinct evidence, serialized per-instance operations and old-generation rejection.
- Create fixtures in pytest temporary directories without modifying repository source or installing dependencies.

**NOT in scope**: Changing core implementation to hide failing behavior, downloading Pyright or running paid seats.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py` | CREATE | Acceptance and regression tests |
| `packages/ai-parrot-tools/tests/lsp/test_mcp_integration.py` | CREATE | Acceptance and regression tests |
| `packages/ai-parrot-tools/tests/lsp/test_worktree_isolation.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`; use only where relevant.
- `from parrot.mcp.local_server import StdioMCPServer` — verified in `packages/ai-parrot/src/parrot/mcp/local_server.py`; use only where relevant.

### Existing Signatures to Use

- `create_toolkit_mcp_server` — `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:29`: create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer; imports under stdout redirection, constructs toolkit kwargs, filters and registers tools. Currently does not retain a resource owner.
- `StdioMCPServer` — `packages/ai-parrot/src/parrot/mcp/local_server.py:36`: existing MCP stdio server uses line-delimited JSON; it is not an LSP Content-Length client.
- `StdioMCPServer.start` — `packages/ai-parrot/src/parrot/mcp/local_server.py:44`: async start(self); stdin currently uses run_in_executor, so cancellation alone may leave executor shutdown waiting.
- `StdioMCPServer.stop` — `packages/ai-parrot/src/parrot/mcp/local_server.py:80`: async stop(self); sets the running flag, without owned toolkit cleanup.

### Dependency-produced contracts

- TASK-3507 supplies `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/lsp.yaml`, `examples/lsp-mcp.yaml`, `docs/sdd/lsp-pilot.md`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

### Does NOT Exist

- The files marked CREATE are new task deliverables; do not assume their modules or exports already exist.
- Files marked MODIFY that are created by a prerequisite must be verified after that prerequisite lands.
- No existing LSP client, persistent diagnostic baseline API or five-arm pilot harness is established by the references above.
- Do not assume generic MCP transport implements LSP framing, or AST line spans provide identifier columns.
- Verify any additional symbol before use; do not invent provider adapters or methods.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_mcp_integration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_worktree_isolation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.start",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.stop"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3507 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `Consume completed LSPToolkit and PyrightSession APIs via public tools; fake_server.py remains the fault fixture.`
- `Integration prerequisite flag: PARROT_LSP_REQUIRE_PYRIGHT=1 makes unavailable/wrong-version backend a hard failure.`

1. Build deterministic temporary Git namespace workspaces and configure both source roots explicitly.
2. Test the real server and raw MCP independently, with file hashes and actual semantic outcomes as assertions.
3. Add isolation/restart/EOF tests and run the prerequisite-required integration command in the provisioned environment.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Add real Pyright 1.1.414 fixtures with aliases, inheritance, duplicate names, PEP 420 namespace roots and non-target dependency changes.
- [ ] Exercise baseline/error/removal transitions including versioned empty publications; missing executable skips ordinary offline runs only, never qualifies acceptance.
- [ ] Drive raw local MCP initialize/list/call/EOF against the complete toolkit, asserting pure protocol stdout and no surviving child.
- [ ] Test two divergent worktrees and simultaneous callers; assert distinct evidence, serialized per-instance operations and old-generation rejection.
- [ ] Create fixtures in pytest temporary directories without modifying repository source or installing dependencies.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_pyright_integration.py -q`
- `pytest packages/ai-parrot-tools/tests/lsp/test_mcp_integration.py -q`
- `pytest packages/ai-parrot-tools/tests/lsp/test_worktree_isolation.py -q`

## Test Specification

- `test_pyright_pinned_navigation`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_pyright_saved_edit_diagnostic_delta`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_pyright_dependency_restart`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_fake_server_stdio_end_to_end`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_mcp_eof_reaps_child`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_two_worktrees_and_concurrent_callers`: cover the corresponding scope invariant with both successful and adversarial inputs.

Real-Pyright acceptance requires `PARROT_LSP_REQUIRE_PYRIGHT=1` and the pinned executable. A skipped offline run is not integration acceptance.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

**Implemented by the sdd-worker orchestrator directly** (not dispatched to a
coder seat): the `parrot-sdd-coder` engine has a confirmed hard routing gap
for `unknown`-classification tasks — every one of 6 distinct seats across
all 3 backends (nova: glm/qwen/mistral/minimax, google-compat: gemini,
codex: codex-spark) rejected this task with `CoderFailure: seat ... is not
eligible for unknown task TASK-3508`, and native `coder_prepare_native` also
refused (`task_not_in_plan`). Filed as `issue:f0cf45fc31dd`. The human
operator explicitly authorized implementing directly after reviewing the
`/sdd-done` blocker report.

**`test_pyright_integration.py`** — real, pinned-Pyright (1.1.414) tests:
`test_pyright_pinned_navigation` (alias/re-export chain, inheritance,
duplicate names, a PEP 420 namespace root via `source_roots`),
`test_pyright_saved_edit_diagnostic_delta` (baseline -> error -> removal
diagnostic transitions including the versioned empty publication after a
fix), `test_pyright_dependency_restart` (editing a non-target dependency
bumps `_session_generation`, never reusing stale evidence). All three are
gated by an `autouse` fixture that SKIPS an ordinary offline run when
`pyright`/`pyright-langserver` are absent or the wrong version (never
counted as integration acceptance per spec §5), and HARD-FAILS instead
under `PARROT_LSP_REQUIRE_PYRIGHT=1` — verified both paths explicitly
(offline: 3 skipped with a clear reason; `PARROT_LSP_REQUIRE_PYRIGHT=1`:
3 failures). No real Pyright is provisioned in this environment, so these
3 tests are **unexecuted here** — this is the honestly-reported limitation
the task's own scope anticipates, not a gap I can close locally.

**`test_mcp_integration.py`** — raw local MCP protocol tests against the
real `parrot mcp-local lsp` CLI as a subprocess (never the in-process
toolkit API), configured with `fake_server.py` as the LSP backend (never a
live Pyright): `test_fake_server_stdio_end_to_end` (initialize -> tools/list
exposing exactly the 4 documented tools -> tools/call -> EOF, asserting
every stdout line is valid JSON-RPC) and `test_mcp_eof_reaps_child`
(explicit focus: the fake-server child process is a real OS child before
shutdown and fully reaped — via stdlib `/proc/<pid>/task/<pid>/children` +
`os.kill(pid, 0)`, no new dependency — after a clean stdin EOF).

**`test_worktree_isolation.py`** — `test_two_worktrees_and_concurrent_callers`:
two independent `LSPToolkit` instances over two divergent git worktrees
produce fully distinct `EvidenceMeta` (repo_root/workspace_id/
workspace_digest); concurrent callers against ONE instance are proven
strictly serialized by monkeypatching `PyrightSession.request` with an
in-flight counter (`max_in_flight == 1` under 3-way `asyncio.gather`); and
old-generation rejection — a stale `expected_sha256` after an on-disk edit
is rejected (`status="error"`, `code="source_changed"`), and a fresh call
bumps `_session_generation` with new `workspace_digest` evidence.

Validation: `pytest packages/ai-parrot-tools/tests/lsp/ -q` → 116 passed, 3
skipped (real-Pyright tests, expected — no `pyright` binary in this
environment). `black -l 120`/`ruff check` clean on all 3 new files.

**Observed, non-blocking**: the 3 skipped real-Pyright tests each emit a
`PluggyTeardownRaisedWarning` from this repo's own root `conftest.py`
`pytest_runtest_setup` hookwrapper (its `except Exception` doesn't catch
`pytest.skip.Exception`, a `BaseException` subclass, raised from an
`autouse` fixture). Reproduced independently of this task's code with a
minimal fixture in an unrelated scratch file; `conftest.py` is out of this
task's file scope, so not touched — noted here for whoever provisions the
real M6 CI lane.

Seat: sonnet (native, no MCP seat) — implemented directly by the
sdd-worker orchestrator per the human-authorized exception above.
