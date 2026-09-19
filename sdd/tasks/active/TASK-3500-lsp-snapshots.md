# TASK-3500: Capture bounded worktree snapshots and convert source positions

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3499
**Assigned-to**: unassigned

## Context

Implement M1 of the approved specification: capture bounded worktree snapshots and convert source positions. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Implement the spec's deterministic Git manifest and source/configuration digests, including tracked deletions, non-ignored untracked Python/stub files, lock files and in-root referenced Pyright config.
- Hash/read in an owned subprocess with bounded JSON I/O and a 10-second deadline; use argument arrays and stable open/fstat/read/fstat checks. Kill/reap the worker on cancellation.
- Confine roots/files and reject traversal, escaping symlinks, FIFOs, unsupported/ignored targets, invalid encoding and configured limits. Requested texts must retain original line endings.
- Implement one-based Unicode to zero-based UTF-16 conversion and the inverse range normalization needed by toolkit results; preserve expected source hashes.

**NOT in scope**: Pyright sessions, toolkit routing, semantic response caching and editor buffers.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_snapshot.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, Field` — verified in `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py`; use only where relevant.

### Existing Signatures to Use

- `SymbolHit` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:48`: existing AST result model carries line spans, not identifier columns, source hashes or LSP versions. Do not infer a position from its line span.

### Dependency-produced contracts

- TASK-3499 supplies `packages/ai-parrot-tools/src/parrot_tools/lsp/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/lsp/models.py`. Read its completed implementation and tests before consuming its API; these are planned deliverables, not verified existing symbols.

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
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/snapshot.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_snapshot.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#SymbolHit"
  ]
}
```

## Implementation Notes

- Follow the uv workspace source layout, strict type hints and async-first resource ownership. Use stdlib and already-declared Pydantic; do not add dependencies without authorization.
- Keep changes within the target table. If implementation reveals an additional target or a conflict with project conventions, report it before expanding scope.
- May run alongside tasks outside its dependency chain with disjoint targets. Requires TASK-3499 for the contracts and deliverables described below.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `async def capture_workspace(config: LSPConfig, paths: list[str]) -> WorkspaceSnapshot`
- `def to_lsp_position(text: str, line: int, column: int) -> dict[str, int]`

1. Use the dependency's models and implement pure position conversion first, including surrogate boundaries.
2. Build private subprocess request/response framing and stable manifest traversal; do not reuse the MCP line protocol as LSP framing.
3. Compare source/config digests in repeat captures and test same-size edits, races, deletions, untracked files and worker timeouts.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Implement the spec's deterministic Git manifest and source/configuration digests, including tracked deletions, non-ignored untracked Python/stub files, lock files and in-root referenced Pyright config.
- [ ] Hash/read in an owned subprocess with bounded JSON I/O and a 10-second deadline; use argument arrays and stable open/fstat/read/fstat checks. Kill/reap the worker on cancellation.
- [ ] Confine roots/files and reject traversal, escaping symlinks, FIFOs, unsupported/ignored targets, invalid encoding and configured limits. Requested texts must retain original line endings.
- [ ] Implement one-based Unicode to zero-based UTF-16 conversion and the inverse range normalization needed by toolkit results; preserve expected source hashes.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_snapshot.py -q`

## Test Specification

- `test_workspace_confinement_and_races`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_workspace_digest_dependency_change`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_unicode_positions`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_worker_cancel_reaps_process`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
