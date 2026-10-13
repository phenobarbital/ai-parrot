# TASK-4281: Confirm or remove result_limit error code

**Feature**: FEAT-661 — sdd-lsp-models-fixes
**Spec**: sdd/specs/sdd-lsp-models-fixes.spec.md
**Status**: pending
**Priority**: low
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: agent

## Context

`result_limit` is a named operational error code in the spec's Data Models
table but doesn't appear to be referenced in `toolkit.py`'s merged code.
Worth confirming it belongs to a manifest-size case elsewhere, or is dead.

Resolves ledger issue:4b0e5d3b1a42.

## Scope

Grep for `result_limit` across the codebase. If used somewhere, add a comment
in models.py documenting where. If dead, remove it from the error-code
enum/model.

### NOT in scope
- Adding new error codes
- Changing error handling logic

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/sdd_lsp/models.py` | MODIFY | Confirm or remove result_limit |

## Acceptance Criteria

- [ ] `result_limit` is confirmed used (with documented location) or removed
- [ ] `ruff check benchmarks/sdd_lsp/models.py` passes

## Validation Commands

```bash
ruff check benchmarks/sdd_lsp/models.py
grep -rn 'result_limit' benchmarks/sdd_lsp/ packages/ai-parrot-tools/src/parrot_tools/lsp/
```

## Completion Note

(filled by implementing agent)
