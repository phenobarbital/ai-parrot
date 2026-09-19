# TASK-3506: Close factory-owned toolkit resources on local MCP exit

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement M4 of the approved specification: close factory-owned toolkit resources on local mcp exit. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Add private _ToolkitStdioMCPServer retaining the instantiated toolkit without changing create_toolkit_mcp_server's public signature or tool filters.
- Wrap start in try/finally and stop with idempotent resource release; close _opened resources then cleanup under an overall 10-second budget and isolated logging.
- Handle CLI SIGTERM through cancellation/cleanup, restore prior handlers, and preserve existing KeyboardInterrupt/list/config error behavior.
- Test EOF, startup errors, concurrent/repeated stop, no-resource toolkits and child cleanup without changing wiki MCP or the generic StdioMCPServer implementation.
- Ensure cancellation of the existing stdin-reader path does not make CLI termination hang during executor shutdown; cover the actual process exit path.

**NOT in scope**: LSP-specific settings, installer templates, underlying generic transport refactor or unrelated toolkits.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | Task implementation |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | Task implementation |
| `packages/ai-parrot/tests/mcp/test_owned_toolkit_lifecycle.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.mcp.toolkit_server import create_toolkit_mcp_server` — verified in `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`; use only where relevant.
- `from parrot.mcp.local_server import StdioMCPServer` — verified in `packages/ai-parrot/src/parrot/mcp/local_server.py`; use only where relevant.
- `from parrot.tools.toolkit import AbstractToolkit` — verified in `packages/ai-parrot/src/parrot/tools/toolkit.py`; use only where relevant.
- `CLI entry point is existing; no new import is needed to edit it.` — verified in `packages/ai-parrot/src/parrot/mcp/local_cli.py`; use only where relevant.

### Existing Signatures to Use

- `create_toolkit_mcp_server` — `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:29`: create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer; imports under stdout redirection, constructs toolkit kwargs, filters and registers tools. Currently does not retain a resource owner.
- `StdioMCPServer` — `packages/ai-parrot/src/parrot/mcp/local_server.py:36`: existing MCP stdio server uses line-delimited JSON; it is not an LSP Content-Length client.
- `StdioMCPServer.start` — `packages/ai-parrot/src/parrot/mcp/local_server.py:44`: async start(self); stdin currently uses run_in_executor, so cancellation alone may leave executor shutdown waiting.
- `StdioMCPServer.stop` — `packages/ai-parrot/src/parrot/mcp/local_server.py:80`: async stop(self); sets the running flag, without owned toolkit cleanup.
- `AbstractToolkit` — `packages/ai-parrot/src/parrot/tools/toolkit.py:206`: base toolkit, tool_prefix defaults to None; use an empty prefix for the four approved names.
- `AbstractToolkit.__init__` — `packages/ai-parrot/src/parrot/tools/toolkit.py:321`: __init__(self, **kwargs); initializes logger, _opened and _open_lock.
- `AbstractToolkit._open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:390`: async _open(self) -> None; custom partial startup must clean itself up.
- `AbstractToolkit._close` — `packages/ai-parrot/src/parrot/tools/toolkit.py:406`: async _close(self) -> None; reset _opened via the superclass.
- `AbstractToolkit._ensure_open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:419`: async _ensure_open(self) -> None; guarded by _open_lock.
- `AbstractToolkit.get_tools` — `packages/ai-parrot/src/parrot/tools/toolkit.py:486`: get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]; discovery must not start a process.
- `ToolkitTool._execute` — `packages/ai-parrot/src/parrot/tools/toolkit.py:145`: async _execute(self, **kwargs) -> Any; auto_open is applied before calling the bound method. Keep LSP auto_open=False.
- `mcp_local` — `packages/ai-parrot/src/parrot/mcp/local_cli.py:88`: mcp_local(name: str | None, config_path: Path | None, include: tuple[str, ...], exclude: tuple[str, ...], list_toolkits: bool) -> None; runs server.start via asyncio.run and catches KeyboardInterrupt.

### Dependency-produced contracts

- No implementation prerequisites. Existing repository conventions and the approved spec apply.

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
      "path": "packages/ai-parrot/src/parrot/mcp/toolkit_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/local_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_owned_toolkit_lifecycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.start",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer.stop",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._close",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._ensure_open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.get_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool._execute",
    "sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- Independent root task; may run alongside tasks with disjoint targets. Owns lsp-mcp-lifecycle targets only.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer (unchanged)`
- `_ToolkitStdioMCPServer: private constructor adds owned toolkit; async start(self) -> None; async stop(self) -> None`

1. Modify the factory's unique server-construction block to retain toolkit ownership while preserving registration/filtering.
2. Implement idempotent close orchestration and CLI-owned signal cancellation with bounded cleanup.
3. Use fake resource-owning AbstractToolkit subclasses and actual subprocess EOF/SIGTERM tests to demonstrate cleanup and existing-toolkit compatibility.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Add private _ToolkitStdioMCPServer retaining the instantiated toolkit without changing create_toolkit_mcp_server's public signature or tool filters.
- [ ] Wrap start in try/finally and stop with idempotent resource release; close _opened resources then cleanup under an overall 10-second budget and isolated logging.
- [ ] Handle CLI SIGTERM through cancellation/cleanup, restore prior handlers, and preserve existing KeyboardInterrupt/list/config error behavior.
- [ ] Test EOF, startup errors, concurrent/repeated stop, no-resource toolkits and child cleanup without changing wiki MCP or the generic StdioMCPServer implementation.
- [ ] Ensure cancellation of the existing stdin-reader path does not make CLI termination hang during executor shutdown; cover the actual process exit path.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_owned_toolkit_lifecycle.py -q`

## Test Specification

- `test_owned_mcp_toolkit_cleanup`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_no_resource_and_failed_open_compatibility`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_mcp_cli_sigterm_restores_and_exits`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_cleanup_timeout_is_bounded`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
