# TASK-533: Remove Legacy Dialogs Module

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-532
**Assigned-to**: unassigned

---

## Context

Implements Module 16 from the spec. Deletes `parrot/integrations/dialogs/` entirely after all consumers have been rewritten to use `parrot/forms/`. This is the final cleanup task.

---

## Scope

- Delete entire `parrot/integrations/dialogs/` directory:
  - `__init__.py`
  - `models.py` (old FormDefinition, FormField, FormSection, FieldType, etc.)
  - `parser.py` (old YAML parser)
  - `cache.py` (old FormDefinitionCache)
  - `registry.py` (old FormRegistry)
  - `llm_generator.py` (old LLMFormGenerator)
- Search entire codebase for any remaining imports from `parrot.integrations.dialogs` and fix them
- Update any `__init__.py` files that re-export from the deleted module
- Verify no test files reference the old module
- Run full test suite to confirm nothing is broken

**NOT in scope**: Any functional changes — this is purely removal.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/dialogs/__init__.py` | DELETE | Old package init |
| `packages/ai-parrot/src/parrot/integrations/dialogs/models.py` | DELETE | Old form models |
| `packages/ai-parrot/src/parrot/integrations/dialogs/parser.py` | DELETE | Old YAML parser |
| `packages/ai-parrot/src/parrot/integrations/dialogs/cache.py` | DELETE | Old cache |
| `packages/ai-parrot/src/parrot/integrations/dialogs/registry.py` | DELETE | Old registry |
| `packages/ai-parrot/src/parrot/integrations/dialogs/llm_generator.py` | DELETE | Old LLM generator |
| `packages/ai-parrot/src/parrot/integrations/__init__.py` | MODIFY | Remove dialogs from exports if present |

---

## Implementation Notes

### Pre-Deletion Checklist

Before deleting anything, run:
```bash
# Find ALL imports of the old module
grep -r "from.*integrations.dialogs" packages/ai-parrot/src/ --include="*.py"
grep -r "from.*integrations\.dialogs" packages/ai-parrot/tests/ --include="*.py"
grep -r "import.*integrations.dialogs" packages/ai-parrot/src/ --include="*.py"
```

Every result must be zero. If any imports remain, fix them first (they should point to `parrot.forms`).

### Key Constraints
- This task MUST run after TASK-532 (Teams rewrite) is complete
- Do NOT delete if any imports still reference the old module
- Run full test suite after deletion to catch any missed references

### References in Codebase
- `parrot/integrations/dialogs/` — the module being removed
- All files modified in TASK-532 — verify they no longer import from dialogs

---

## Acceptance Criteria

- [ ] `parrot/integrations/dialogs/` directory completely removed
- [ ] No imports reference `parrot.integrations.dialogs` anywhere in the codebase
- [ ] Full test suite passes: `pytest packages/ai-parrot/tests/ -v`
- [ ] No runtime errors when importing `parrot.integrations`

---

## Test Specification

```bash
# Verification commands (not Python tests — this is a deletion task)

# 1. No imports reference old module
grep -r "integrations.dialogs" packages/ai-parrot/src/ --include="*.py" | wc -l  # should be 0
grep -r "integrations.dialogs" packages/ai-parrot/tests/ --include="*.py" | wc -l  # should be 0

# 2. Directory is gone
test ! -d packages/ai-parrot/src/parrot/integrations/dialogs && echo "PASS" || echo "FAIL"

# 3. Full test suite
pytest packages/ai-parrot/tests/ -v
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-532 is in `tasks/completed/`
3. **Run the grep commands** in Implementation Notes to confirm zero remaining imports
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Delete** the entire `parrot/integrations/dialogs/` directory
6. **Fix** any remaining imports found
7. **Run full test suite** to verify
8. **Move this file** to `tasks/completed/TASK-533-remove-legacy-dialogs.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
