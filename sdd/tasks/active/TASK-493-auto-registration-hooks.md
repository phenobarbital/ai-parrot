# TASK-493: Auto-Registration Hooks

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-490
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec. Adds optional `routing_meta` field to DataSource and
> AbstractTool, and optional `capability_registry` parameter to DatasetManager.add_source()
> and ToolManager.register() so resources are auto-registered when a registry is present.

---

## Scope

- Add optional `routing_meta: dict[str, Any] = {}` field to:
  - `DataSource` (or its base class)
  - `AbstractTool` (or equivalent base)
- Modify `DatasetManager.add_source()` to accept optional `capability_registry` parameter:
  - If registry provided, call `registry.register_from_datasource(source, name)`.
- Modify `ToolManager.register()` (or similar) to accept optional `capability_registry` parameter:
  - If registry provided, call `registry.register_from_tool(tool)`.
- Write unit tests.

**NOT in scope**: IntentRouterMixin, CapabilityRegistry implementation (already in TASK-490).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/base.py` | MODIFY | Add `routing_meta` to DataSource |
| `parrot/tools/base.py` | MODIFY | Add `routing_meta` to AbstractTool |
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Optional `capability_registry` in add_source() |
| `parrot/tools/manager.py` | MODIFY | Optional `capability_registry` in register() |
| `tests/tools/test_auto_registration.py` | CREATE | Unit tests |

---

## Implementation Notes

### Key Constraints
- `routing_meta` is optional with empty dict default — zero impact on existing code.
- `capability_registry` parameter is optional (default None) — no change when not provided.
- Auto-registration should not fail if registry rejects the entry — log warning and continue.

### References in Codebase
- `parrot/tools/dataset_manager/sources/base.py` — DataSource base class
- `parrot/tools/base.py` — AbstractTool base class
- `parrot/tools/dataset_manager/tool.py:88` — DatasetEntry / add_source
- `parrot/tools/manager.py` — ToolManager.register()

---

## Acceptance Criteria

- [ ] `routing_meta` field added to DataSource and AbstractTool (optional, default {})
- [ ] DatasetManager.add_source() auto-registers when capability_registry provided
- [ ] ToolManager.register() auto-registers when capability_registry provided
- [ ] Without capability_registry, behavior is identical to current
- [ ] All existing tests still pass
- [ ] New tests pass: `pytest tests/tools/test_auto_registration.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-493-auto-registration-hooks.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
