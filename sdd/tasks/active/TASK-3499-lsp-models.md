# TASK-3499: Define LSP evidence, configuration and failure models

**Feature**: FEAT-580 - SDD LSP Research Pilot
**Spec**: `sdd/specs/sdd-research-lsp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement M1 of the approved specification: define lsp evidence, configuration and failure models. The reported 13% cost, 12% token and 24% call reductions are hypotheses; only the specified evaluation can establish local benefit. Read the complete spec's contracts, acceptance criteria and relevant module before implementation.

## Scope

- Implement all §2 Data Models and fixed operational codes, strict Pydantic v2 validation and bounded defaults; export no toolkit until its module exists.
- Define private WorkspaceSnapshot, DiagnosticBatch and LSPFailure representations used by dependent tasks. Preserve complete uncropped diagnostics internally and JSON-safe public evidence separately.
- Validate paths/hashes/coordinate shapes and all configurable caps without opening files, starting processes or probing executables in model constructors.
- Represent unavailable, partial and unknown independently of empty successful results; sentinel operator-unconfigured is handled before process creation by the toolkit.

**NOT in scope**: Protocol, source scanning, process startup, public tools and live benchmarks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/__init__.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/src/parrot_tools/lsp/models.py` | CREATE | Task implementation |
| `packages/ai-parrot-tools/tests/lsp/test_models.py` | CREATE | Acceptance and regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pydantic import BaseModel, Field` — verified in `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py`; use only where relevant.

### Existing Signatures to Use

- `SymbolHit` — `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:48`: existing AST result model carries line spans, not identifier columns, source hashes or LSP versions. Do not infer a position from its line span.

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
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_models.py",
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
- Independent root task; may run alongside tasks with disjoint targets. Owns lsp-models targets only.
- Activate the main repository virtual environment when using a shell in a worktree; do not create a worktree venv. Store test output in `artifacts/logs/`.
- Format touched Python with black and run ruff for touched Python files. These supplement the file-level test contract below.

## Implementation Blueprint

The following are required interfaces or artifact contracts, not claims that the symbols already exist:

- `LSPConfig, SourcePosition, SourceRange, SourceState, LSPLocation, LSPDiagnostic, EvidenceMeta, LSPResult`
- `DiagnosticSnapshot, WorkspaceSnapshot, DiagnosticBatch, LSPFailure`

1. Map each spec field to one typed model with explicit defaults; keep shared model imports light.
2. Define private transport/snapshot records and exact failure vocabulary before downstream implementations import them.
3. Test valid round trips, forbidden extras, boundary limits, negative coordinates and hashes, and missing/partial coverage invariants.

Use complete implementations, with no placeholder methods or unfinished public tools. Test fixtures must be deterministic and independent of live providers unless explicitly opted in.

## Acceptance Criteria

- [ ] Implement all §2 Data Models and fixed operational codes, strict Pydantic v2 validation and bounded defaults; export no toolkit until its module exists.
- [ ] Define private WorkspaceSnapshot, DiagnosticBatch and LSPFailure representations used by dependent tasks. Preserve complete uncropped diagnostics internally and JSON-safe public evidence separately.
- [ ] Validate paths/hashes/coordinate shapes and all configurable caps without opening files, starting processes or probing executables in model constructors.
- [ ] Represent unavailable, partial and unknown independently of empty successful results; sentinel operator-unconfigured is handled before process creation by the toolkit.
- [ ] All target files are complete and file-level validation passes.
- [ ] No unrelated files or actual developer host configuration are changed.
- [ ] Failures, unavailable prerequisites and verification limitations are recorded honestly in the completion note.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_models.py -q`

## Test Specification

- `test_models_reject_extra_fields_and_invalid_limits`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_source_hash_coordinate_and_range_validation`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_unknown_and_empty_success_are_distinct`: cover the corresponding scope invariant with both successful and adversarial inputs.
- `test_import_and_construction_have_no_io`: cover the corresponding scope invariant with both successful and adversarial inputs.

## Agent Instructions

1. Read the approved spec and this task; verify prerequisites in `sdd/tasks/index/sdd-research-lsp.json`.
2. Mark only this task in-progress with assignment/start timestamp before implementing.
3. Reverify existing and dependency-produced contracts; follow the file scope and update the task first if an approved scope correction is needed.
4. Implement and run the validation above; record actual results and any external blockers.
5. Run the required SDD review, then commit only task-scoped implementation plus this task and its per-spec index state. Do not use the historical monolithic index.
6. Mark done only when every acceptance criterion is satisfied. Leave blocked external execution unfinished.

## Completion Note

Not completed. The implementing agent must record changed behavior, validation results, commit, review outcome and remaining limitations here.
