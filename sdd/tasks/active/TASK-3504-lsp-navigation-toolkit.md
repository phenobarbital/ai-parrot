# TASK-3504: Expose hash-verified definition and reference tools

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3500, TASK-3503
**Assigned-to**: unassigned

## Context

Implement M3 of the approved specification: expose hash-verified definition and reference tools. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Create LSPToolkit(config, **kwargs), auto_open=False and tool_prefix=''; add only the two fully implemented navigation methods at this stage.
- Validate tool inputs and environment sentinel before process startup; own operation lock, lazy startup, 120-second idle shutdown and 90-second total call deadline.
- Capture before/after manifests, restart sessions on any workspace/config digest change, discard responses if the workspace changes during a call and bind permanently to one root.
- Normalize Location/LocationLink to bounded confined ranges/hashes, convert UTF-16, deduplicate and enforce limit/byte caps with omission counts and partial status.
- Map expected failures into LSPResult and propagate cancellation after cleanup; fallback text recommends wiki/AST without auto-invoking other tools.

**NOT in scope**: Diagnostic public methods/baselines (next task), wiki/MCP registration and LLM routing.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_navigation.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from parrot.tools.toolkit import AbstractToolkit` — verified in `packages/ai-parrot/src/parrot/tools/toolkit.py`; use only where relevant.

### Existing Signatures to Use

- `AbstractToolkit` — `packages/ai-parrot/src/parrot/tools/toolkit.py:206`: base toolkit, tool_prefix defaults to None; use an empty prefix for the four approved names.
- `AbstractToolkit.__init__` — `packages/ai-parrot/src/parrot/tools/toolkit.py:321`: __init__(self, **kwargs); initializes logger, _opened and _open_lock.
- `AbstractToolkit._open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:390`: async _open(self) -> None; custom partial startup must clean itself up.
- `AbstractToolkit._close` — `packages/ai-parrot/src/parrot/tools/toolkit.py:406`: async _close(self) -> None; reset _opened via the superclass.
- `AbstractToolkit._ensure_open` — `packages/ai-parrot/src/parrot/tools/toolkit.py:419`: async _ensure_open(self) -> None; guarded by _open_lock.
- `AbstractToolkit.get_tools` — `packages/ai-parrot/src/parrot/tools/toolkit.py:486`: get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]; discovery must not start a process.
- `ToolkitTool._execute` — `packages/ai-parrot/src/parrot/tools/toolkit.py:145`: async _execute(self, **kwargs) -> Any; auto_open is applied before calling the bound method. Keep LSP auto_open=False.

### Dependency-produced contracts

- TASK-3500 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.
- TASK-3503 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_navigation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._close",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._ensure_open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.get_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#ToolkitTool._execute"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3500, TASK-3503 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `LSPToolkit.__init__(self, config: LSPConfig | dict[str, Any], **kwargs: Any) -> None`
- `async def lsp_definition(self, path: str, line: int, column: int, expected_sha256: str) -> LSPResult`
- `async def lsp_references(self, path: str, line: int, column: int, expected_sha256: str, include_declaration: bool = False, limit: int = 50) -> LSPResult`

1. Implement private lifecycle helpers and idempotent cleanup against the completed session/snapshot APIs.
2. Add both navigation methods with input validation, generation restart and pre/post evidence verification.
3. Test result normalization, external-path omission, capped output, concurrent callers and idle cancellation; do not expose diagnostic stubs.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Create LSPToolkit(config, **kwargs), auto_open=False and tool_prefix=''; add only the two fully implemented navigation methods at this stage.
- [ ] Validate tool inputs and environment sentinel before process startup; own operation lock, lazy startup, 120-second idle shutdown and 90-second total call deadline.
- [ ] Capture before/after manifests, restart sessions on any workspace/config digest change, discard responses if the workspace changes during a call and bind permanently to one root.
- [ ] Normalize Location/LocationLink to bounded confined ranges/hashes, convert UTF-16, deduplicate and enforce limit/byte caps with omission counts and partial status.
- [ ] Map expected failures into LSPResult and propagate cancellation after cleanup; fallback text recommends wiki/AST without auto-invoking other tools.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_navigation.py -q`

## Test Specification

- `test_definition_reference_normalization`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_hash_mismatch_and_workspace_changed`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_no_io_on_construction_and_listing`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_lifecycle_cancel_idle_shutdown`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
