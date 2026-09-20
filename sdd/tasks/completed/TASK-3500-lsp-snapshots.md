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

Implemented `capture_workspace(config, paths)` in `parrot_tools/lsp/snapshot.py`: builds the deterministic
manifest via `git ls-files -z` (tracked, `--deleted`, `--others --exclude-standard`), filtered to `.py`/`.pyi`
plus in-root `pyrightconfig.json`/`pyproject.toml`/`uv.lock`/`.python-version`. Hashing/reading runs in an owned
subprocess worker (stable open→fstat→read→fstat with `O_NONBLOCK`, 10s deadline, `_kill_and_reap()` on
timeout/cancellation — verified no orphaned processes via `/proc` cmdline scan + `ps -ef`). Confinement checks
(traversal, escaping symlinks, FIFO/non-regular targets, ignored/unlisted paths, tracked-deleted tombstones,
oversized files/manifest, invalid UTF-8) each map to a fixed `LSP_ERROR_CODES` entry. Digest is sha256 over
sorted file hashes + tombstones + `config_digest`, so both content edits and non-target config changes
invalidate it. `to_lsp_position`/`from_lsp_range` (+ private `_from_lsp_position`) convert one-based Unicode
↔ zero-based UTF-16, astral/surrogate-pair aware, CRLF/tabs/EOF handled, half-surrogate ranges rejected as
`protocol_error`.

**Codebase Contract check (requested by TASK-3499):** confirmed `DiagnosticBatch`/`DiagnosticSnapshot.diagnostics:
dict[str, list[RawDiagnostic]]` — this task does not consume or produce that field; only `WorkspaceSnapshot`/
`LSPFailure` are touched and their shapes matched exactly. No mismatch.

**Design note flagged for reviewers of M3 (toolkit.py):** `from_lsp_range`/`_from_lsp_position` are new helpers
not named in the task's Implementation Blueprint (only `capture_workspace`/`to_lsp_position` were listed); added
because AC4 requires "the inverse range normalization needed by toolkit results" and the blueprint text says its
listed interfaces are required but not exhaustive. Returns the existing `SourceRange` model, no new contract
symbol. Also: git-subprocess failures (not a worktree, subprocess timeout) map to `resource_limit`, and malformed
worker JSON maps to `protocol_error` — best-fit choices onto the fixed vocabulary since no more specific code
exists for either case; documented in code comments.

Validation: `PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest
packages/ai-parrot-tools/tests/lsp/test_snapshot.py -q` → 4 passed. Full `packages/ai-parrot-tools/tests/lsp/`
(includes TASK-3499's `test_models.py`) → 18 passed, no regression. `black`/`ruff check` clean on both touched
files (one `ASYNC240` finding fixed by hoisting a module-level constant resolve out of the async function).

Post-merge regression (`select_tests --tier merge`): 98 passed (`dev_loop/sdd_coder` + `packages/ai-parrot/tests/mcp`),
48 passed/1 deselected (`packages/ai-parrot-tools/tests/lsp` + `tool_optimizations/integration`), 15 passed
(`tests/mcp/test_toolkit_server.py`).

Coder-feedback patterns checked: hasattr-duck-typing — not applicable (error dispatch is on the fixed
`LSPFailure.code` string, checked exactly, no ambiguous duck-typed branching). unisolated-real-home-in-tests —
verified: no test touches `$HOME`/`PARROT_HOME`/XDG paths; all I/O is scoped to `tmp_path`.
unscoped-removal-reuses-full-uninstall-helper — not applicable (all functions are new, nothing reused/wrapped).

No code review deferred findings for this delivery; the two design notes above are carried forward for later-task
review, not defects. No correction feedback filed.

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a (not reported by native
Agent dispatch) · Tokens: 221067 (subagent_tokens, per completion notification).
