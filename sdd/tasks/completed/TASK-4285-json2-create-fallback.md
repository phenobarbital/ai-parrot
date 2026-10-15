# TASK-4285 — Widen JSON-2 create fallback detection

- **Feature**: transport-json2-fixes
- **Feature ID**: FEAT-664
- **Spec**: sdd/specs/transport-json2-fixes.spec.md
- **Status**: pending
- **Priority**: high
- **Estimated effort**: S
- **Depends-on**: []

## Context

`Json2Transport._is_create_signature_error` is too narrow. It requires
`".create:"` in the error text AND one of `"missing a required argument"` /
`"unexpected keyword argument"`. Odoo 19 models with a `create` override can
return `"got an unexpected keyword argument 'vals_list'"` — no `".create:"`
prefix — so `web_save` fallback never fires.

## Scope

- Widen `_is_create_signature_error` to also match when `"vals_list"` appears
  in the error text (alongside the existing `"unexpected keyword argument"`
  check), regardless of `".create:"` prefix.
- Add unit tests for the widened detection.

### NOT in scope

- Changing the `web_save` fallback logic itself.
- Adding retry for non-create methods.

## Files to Modify

- `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`

## Codebase Contract

### Verified Imports
- `from parrot.interfaces.odoointerface import OdooRPCError` — exists in json2.py:22

### Existing Signatures
- `Json2Transport._is_create_signature_error(exc: OdooRPCError) -> bool` — line 195
- `Json2Transport.execute_kw(self, model, method, args, kwargs) -> Any` — line 218

## Acceptance Criteria

- AC1: `_is_create_signature_error(OdooRPCError("got an unexpected keyword argument 'vals_list'"))` returns `True`.
- AC2: `_is_create_signature_error(OdooRPCError("res.partner.create: missing a required argument"))` still returns `True`.
- AC3: `_is_create_signature_error(OdooRPCError("some unrelated error"))` returns `False`.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/odoo/ -x -q
```

## Completion Note

Implemented in commits f4f12ad9d (TASK-4285) and 519f3e82e (TASK-4286); code merged to dev via PR #1654 before SDD state was closed. Verified 2026-10-16: `pytest packages/ai-parrot-tools/tests/odoo/` -> 4 passed. State closed retroactively in this worktree.
