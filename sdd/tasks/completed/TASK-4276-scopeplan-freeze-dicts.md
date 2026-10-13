# TASK-4276: Freeze ScopePlan dict fields

**Feature**: FEAT-659 — nodes-qa-tech-debt
**Spec**: sdd/specs/nodes-qa-tech-debt.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: XS
**Depends-on**: none
**Assigned-to**: agent

## Context

`ScopePlan` is `@dataclass(frozen=True)` with every other collection field
using immutable tuples. FEAT-604's `cap_hits: dict[str, tuple[str, ...]]` and
`cap_impacted: dict[str, str]` are plain mutable dicts, breaking the class's
established immutability convention.

Resolves ledger issue:f8d560ed8764.

## Scope

Change `cap_hits` and `cap_impacted` to use `MappingProxyType` (or convert to
frozen representations). Update `plan_tests` in `select.py` to wrap them.

### NOT in scope
- Changing other ScopePlan fields
- Modifying the frozen=True semantics

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | Change cap_hits/cap_impacted type annotations to use MappingProxyType |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | Wrap dict values in MappingProxyType at construction |

## Acceptance Criteria

- [ ] `ScopePlan.cap_hits` and `cap_impacted` are immutable mappings (MappingProxyType)
- [ ] `plan_tests` wraps dict values before constructing ScopePlan
- [ ] Existing test_scope tests pass

## Validation Commands

```bash
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/ -x -q --timeout=30
```

## Completion Note

(filled by implementing agent)
