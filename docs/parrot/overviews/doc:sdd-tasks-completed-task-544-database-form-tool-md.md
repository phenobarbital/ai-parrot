---
type: Wiki Overview
title: 'TASK-544: DatabaseFormTool — Core Implementation'
id: doc:sdd-tasks-completed-task-544-database-form-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core task for FEAT-078. It implements the `DatabaseFormTool`
  — an `AbstractTool`
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-544: DatabaseFormTool — Core Implementation

**Feature**: Form Builder from Database Definition
**Spec**: `sdd/specs/formbuilder-database.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core task for FEAT-078. It implements the `DatabaseFormTool` — an `AbstractTool`
subclass that queries PostgreSQL for a form definition (by `formid` + `orgid`) and
deterministically transforms it into a `FormSchema`.

Implements **Module 1** from the spec.

---

## Scope

- Implement `DatabaseFormTool(AbstractTool)` in a new file
- Define `DatabaseFormInput` Pydantic model with `formid: int`, `orgid: int`, `persist: bool`
- Implement the SQL query using `asyncdb.AsyncDB` with `parrot.conf.default_dsn`
- Implement metadata index builder: `column_name → {column_id, data_type, description}`
- Implement `question_id → column_name` reverse index (for conditional logic resolution)
- Implement DB field type → `FieldType` mapping table:
  - `FIELD_TEXT` → `text`
  - `FIELD_TEXTAREA` → `text_area`
  - `FIELD_INTEGER` → `integer`
  - `FIELD_FLOAT2` → `number`
  - `FIELD_YES_NO` → `boolean`
  - `FIELD_MULTISELECT` → `multi_select`
  - `FIELD_IMAGE_UPLOAD_MULTIPLE` → `file` with `meta={"accept": "image/*", "multiple": true}`
  - `FIELD_DISPLAY_TEXT` → `text` with `read_only=True`, `meta={"render_as": "display_text"}`
  - `FIELD_DISPLAY_IMAGE` → `image` with `read_only=True`, `meta={"render_as": "display_image"}`
  - `FIELD_SIGNATURE_CAPTURE` → skip (log warning)
- Implement question block → `FormSection` mapping (each block = one section)
- Implement question → `FormField` mapping:
  - `field_id = f"field_{column_name}"`
  - `label` from `question_description`
  - `required=True` if validations contain `responseRequired`
  - Skip if `question_column_name` not in active metadata
  - Skip if `data_type` is unsupported
- Implement conditional logic translation:
  - `condition_logic: "EQUALS"` → `ConditionOperator.EQ`
  - `condition_question_reference_id` → resolve via question_id→column_name index → `field_id`
  - Multiple conditions in one `logic_group` → `logic="or"`
  - Multiple `logic_groups` on one question → `logic="and"`
  - All rules use `effect="show"`
- Implement `FIELD_MULTISELECT` option extraction from conditional references
  (collect `condition_comparison_value` + `condition_option_id` across all conditions
  referencing that field to build `FieldOption` lists)
- Register generated `FormSchema` in `FormRegistry`
- Return `FormSchema` in `ToolResult.metadata["form"]`
- Error handling: form not found, malformed JSON, DB connection failure → descriptive error `ToolResult`

**NOT in scope**: Package exports (TASK-545), example UI (TASK-546), tests (TASK-547)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/tools/database_form.py` | CREATE | DatabaseFormTool implementation |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the pattern from create_form.py
class DatabaseFormTool(AbstractTool):
    name: str = "database_form"
    description: str = "Load a form definition from PostgreSQL into a FormSchema"
    input_model = DatabaseFormInput

    def __init__(self, registry: FormRegistry, dsn: str | None = None):
        self.registry = registry
        self.dsn = dsn
        ...

    async def _execute(self, formid: int, orgid: int, persist: bool = False) -> ToolResult:
        ...
```

### SQL Query (parameterized)
```sql
SELECT
    f.formid, f.form_name, f.description, f.client_id, f.client_name, f.orgid,
    f.question_blocks,
    jsonb_agg(
        jsonb_build_object(
            'column_id', m.column_id, 'column_name', m.column_name,
            'description', m.description, 'data_type', m.data_type
        )
    ) AS metadata
FROM networkninja.forms f
JOIN networkninja.form_metadata m USING(formid)
WHERE f.formid = $1 AND f.orgid = $2 AND m.is_active = true
GROUP BY f.formid, f.form_name, f.description, f.client_id, f.client_name,
         f.orgid, f.question_blocks
```

### Key Constraints
- `question_column_name` is int in JSON, `column_name` in metadata is string — cast for comparison
- `question_blocks` is a JSON string (text column), not native JSONB — must `json.loads()`
- Use `self.logger` for warnings (skipped fields) and info (form loaded)
- Parameterized queries only — no string interpolation

### References in Codebase
- `packages/ai-parrot/src/parrot/forms/tools/create_form.py` — tool pattern
- `packages/ai-parrot/src/parrot/forms/schema.py` — FormSchema, FormSection, FormField
- `packages/ai-parrot/src/parrot/forms/types.py` — FieldType enum
- `packages/ai-parrot/src/parrot/forms/constraints.py` — DependencyRule, FieldCondition, ConditionOperator
- `packages/ai-parrot/src/parrot/forms/options.py` — FieldOption
- `packages/ai-parrot/src/parrot/forms/registry.py` — FormRegistry

---

## Acceptance Criteria

- [ ] `DatabaseFormTool` can be instantiated with a `FormRegistry`
- [ ] Executes parameterized SQL query via `asyncdb`
- [ ] All supported DB field types map to correct `FieldType`
- [ ] Unsupported types are skipped with `self.logger.warning()`
- [ ] Display-only fields have `read_only=True` + correct `meta`
- [ ] Each question block → separate `FormSection`
- [ ] Questions not in active metadata are skipped
- [ ] `responseRequired` → `required=True`
- [ ] Conditional logic translates to `DependencyRule` correctly
- [ ] Multi-select options are extracted from conditional references
- [ ] Form registers in `FormRegistry`
- [ ] Error cases return descriptive `ToolResult` (not exceptions)

---

## Test Specification

```python
# Tests are in TASK-547 — this task focuses on implementation only
# Manual verification: instantiate tool, call with known formid/orgid
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formbuilder-database.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-544-database-form-tool.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-start)
**Date**: 2026-04-03
**Notes**: Implemented `DatabaseFormTool` in `packages/ai-parrot/src/parrot/forms/tools/database_form.py`.
All 10 field type mappings implemented. Multi-select option extraction via pre-scan of
logic_groups. Conditional logic correctly maps EQUALS conditions to DependencyRule.
Single-group multiple conditions → logic="or"; multiple groups → logic="and".
All error cases (form not found, malformed JSON, DB failure) return descriptive ToolResult.
274 existing form tests continue to pass.

**Deviations from spec**: none
