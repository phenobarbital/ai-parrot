# TASK-4286 — Add get_views mapping to JSON-2 transport

- **Feature**: transport-json2-fixes
- **Feature ID**: FEAT-664
- **Spec**: sdd/specs/transport-json2-fixes.spec.md
- **Status**: pending
- **Priority**: medium
- **Estimated effort**: S
- **Depends-on**: []

## Context

`Json2Transport._build_body` has no explicit handler for the `get_views` method.
`get_views` takes `(views, options)` where `views` is a list of `(view_id,
view_type)` tuples — not record ids. The generic fallback raises `OdooRPCError`
because `_looks_like_ids` returns `False` for tuples.

## Scope

- Add a `get_views` branch in `_build_body` that maps `args[0]` → `views`
  and `args[1]` (if present) → `options`.
- Add a unit test for the new mapping.

### NOT in scope

- Other unmapped methods beyond `get_views`.

## Files to Modify

- `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`

## Codebase Contract

### Verified Imports
- `from parrot.interfaces.odoointerface import OdooRPCError` — exists in json2.py:22

### Existing Signatures
- `Json2Transport._build_body(method, args, kwargs) -> dict[str, Any]` — line 108 (staticmethod)

## Acceptance Criteria

- AC1: `_build_body("get_views", [[(False, "form")], {}], None)` returns `{"views": [(False, "form")], "options": {}}`.
- AC2: `_build_body("get_views", [[(1, "list"), (2, "form")]], None)` returns `{"views": [(1, "list"), (2, "form")]}`.
- AC3: Existing tests pass.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/odoo/ -x -q
```

## Completion Note

Implemented in commits f4f12ad9d (TASK-4285) and 519f3e82e (TASK-4286); code merged to dev via PR #1654 before SDD state was closed. Verified 2026-10-16: `pytest packages/ai-parrot-tools/tests/odoo/` -> 4 passed. State closed retroactively in this worktree.
