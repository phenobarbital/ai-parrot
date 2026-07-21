---
type: Wiki Overview
title: 'TASK-1528: EditToolkit dependency CRUD + CreateFormTool rule coverage'
id: doc:sdd-tasks-completed-task-1528-edit-toolkit-rule-authoring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 6 (tools slice). Closes the core authoring gap: today `EditToolkit`
  can add/update'
---

# TASK-1528: EditToolkit dependency CRUD + CreateFormTool rule coverage

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1526
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (tools slice). Closes the core authoring gap: today `EditToolkit` can add/update
fields and sections but has NO way to define or edit `depends_on`/`post_depends`. This task adds
dependency CRUD methods that validate via the rule-integrity pass (TASK-1526) and extends
`CreateFormTool` so an LLM can emit rules in generated forms.

---

## Scope

- Add async methods to `EditToolkit` (`tools/edit_toolkit.py`):
  `add_dependency(field_id, rule)`, `update_dependency(field_id, patch)`,
  `remove_dependency(field_id)`, `add_post_dependency(field_id, post)`,
  `remove_post_dependency(field_id, target)`.
- Each method builds the relevant Pydantic model, applies it to the in-progress form, and runs the
  rule-integrity validation (TASK-1526) — returning a structured error dict on invalid rules rather
  than mutating the form.
- Register the new methods in the toolkit's tool dispatch (`execute_tool`, edit_toolkit.py:666) and
  any tool listing so they're LLM-invokable.
- Extend `CreateFormTool` (`tools/create_form.py`) generation contract/prompt so generated schemas
  may include valid `depends_on`/`post_depends` (and they pass validation).
- Unit tests for CRUD + invalid-rule rejection; an integration-style test for CreateFormTool emitting rules.

**NOT in scope**: control-registry capability metadata + `field_helpers` snippets (TASK-1529);
the `RuleEvaluator` (TASK-1530); renderer changes (TASK-1527).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` | MODIFY | Dependency/post-dependency CRUD methods + dispatch |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | Rule schema coverage in generation contract |
| `packages/parrot-formdesigner/tests/` | CREATE/MODIFY | Toolkit + create-form tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.tools import EditToolkit, CreateFormTool
from parrot_formdesigner.services import FormValidator
from parrot_formdesigner.core import (
    FormField, DependencyRule, PostDependency, DependencyOperation, FieldCondition, ConditionOperator,
)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py
class EditToolkit(AbstractToolkit):                  # line 49
    async def update_field(self, ...)                # 281
    async def add_field(self, ...)                   # 320
    async def remove_field(self, section_id, field_id) -> dict  # 361
    async def get_field(self, field_id) -> dict      # 200
    async def search_fields(self, ...)               # 221
    async def execute_tool(self, tool_name, arguments) -> dict   # 666  (dispatch — register new tools here)
    # NOTE: NO depends_on/post_depends editing method exists today.

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py
class CreateFormInput(BaseModel)                     # line 190
class CreateFormTool(AbstractTool)                   # line 226
    async def _execute(self, ...)                    # 289
    async def _generate_with_retry(self, ...)        # 472
    async def _execute_toolkit_edit(self, ...)       # 543

# Validation entry point (TASK-1526 added rule-integrity):
# FormValidator.validate(form, data, *, locale="en") -> ValidationResult   # validators.py:112
```

### Does NOT Exist
- ~~`EditToolkit.add_dependency` / `update_dependency` / `add_post_dependency`~~ — none exist (this task creates them).
- ~~A rule evaluator~~ — TASK-1530; do not call it here.
- ~~Auto-fixing invalid rules~~ — methods REJECT invalid rules; they do not silently repair.

---

## Implementation Notes

### Pattern to Follow
Mirror the structure/return-shape of existing `add_field`/`update_field` (edit_toolkit.py:320/281):
build model → locate target field via `get_field`/internal lookup → validate → apply or return
error dict. Register each new method in `execute_tool` dispatch (edit_toolkit.py:666) following how
existing tools are registered.

### Key Constraints
- Async throughout; `AbstractToolkit` conventions.
- Invalid rules return a structured error (do not raise uncaught); valid rules mutate the form.
- Reuse `FormValidator` rule-integrity (TASK-1526) — do not re-implement reference/ordering checks.

### References in Codebase
- `tools/edit_toolkit.py:281-426` — existing CRUD method patterns + dispatch at `:666`.
- `tools/create_form.py:226-543` — generation/validation flow.

---

## Acceptance Criteria

- [ ] `add_dependency`/`update_dependency`/`remove_dependency` create/edit/clear `FormField.depends_on`.
- [ ] `add_post_dependency`/`remove_post_dependency` manage `FormField.post_depends`.
- [ ] Adding an invalid rule (unknown ref, bad ordering, type mismatch) returns an error and does NOT mutate the form.
- [ ] New methods are dispatchable via `execute_tool` and appear in the toolkit's tool list.
- [ ] `CreateFormTool` can produce a schema containing valid `depends_on`/`post_depends`.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/ -k "toolkit or create_form" -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_formdesigner.tools import EditToolkit
from parrot_formdesigner.core import FormSchema, FormSection, FormField, FieldType

class TestEditToolkitRules:
    async def test_add_dependency_valid(self):
        ...  # add_dependency applies a valid depends_on

    async def test_add_dependency_invalid_rejected(self):
        ...  # unknown field_id → error dict, form unchanged

    async def test_add_and_remove_post_dependency(self):
        ...

    async def test_new_tools_dispatchable(self):
        ...  # execute_tool("add_dependency", {...}) works
```

---

## Agent Instructions

1. **Read the spec** §3 Module 6 + §2 New Public Interfaces (`EditToolkit` methods).
2. **Check dependencies** — TASK-1526 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `edit_toolkit.py` dispatch (`execute_tool`) and the
   existing `add_field`/`update_field` patterns before editing.
4. **Update index** → `"in-progress"`.
5. **Implement** CRUD methods + dispatch + CreateFormTool coverage + tests.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Added add_dependency, update_dependency, remove_dependency, add_post_dependency, remove_post_dependency to EditToolkit. All use rule-integrity validation before mutating. _replace_field_in_form and _check_rules helpers added. All methods dispatchable via execute_tool. CreateFormTool system prompt updated with depends_on/post_depends schema + toolkit system prompt updated with new tool names. 17 tests pass.

**Deviations from spec**: none
