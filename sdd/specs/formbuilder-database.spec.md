# Feature Specification: Form Builder from Database Definition

**Feature ID**: FEAT-078
**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.9.x
**Brainstorm**: `sdd/proposals/formbuilder-database.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The Form Abstraction Layer (FEAT-076) creates forms via LLM natural language prompts (`CreateFormTool`).
However, the NetworkNinja platform stores hundreds of form definitions in PostgreSQL
(`networkninja.forms` + `networkninja.form_metadata`) with rich structure: question blocks,
conditional logic groups, field validations, and per-column data types.

There is currently no way to import these database-defined forms into the `FormSchema` system.
Users must manually recreate forms that already exist, losing conditional logic, validation rules,
and section structure.

### Goals

- Provide a `DatabaseFormTool` that loads a form definition from PostgreSQL by `formid` + `orgid`
  and returns a fully functional `FormSchema`
- Translate `question_blocks` JSON into `FormSection`s with correct field ordering
- Map DB field types (`FIELD_INTEGER`, `FIELD_TEXT`, etc.) to `FieldType` enum values
- Translate `logic_groups` into `DependencyRule` conditional visibility
- Translate `validations` (e.g., `responseRequired`) into `required` flags
- Register the resulting `FormSchema` in `FormRegistry` for reuse
- Integrate into the example form server UI with formid/orgid inputs

### Non-Goals (explicitly out of scope)

- Writing forms back to the database (read-only)
- LLM-based interpretation of field descriptions — this is deterministic mapping
- Supporting `FIELD_SIGNATURE_CAPTURE` or other hardware-dependent field types
- Modifying the existing `FormSchema`, `FormField`, or `FieldType` models
- Multi-select option fetching from separate DB tables — options are embedded in
  `condition_comparison_value` / `condition_option_id`

---

## 2. Architectural Design

### Overview

A new `DatabaseFormTool` (subclass of `AbstractTool`) queries PostgreSQL via `asyncdb`,
receives a single-row result containing form header fields + `question_blocks` (JSON string)
+ `metadata` (JSONB aggregate), and deterministically transforms it into a `FormSchema`.

The transformation pipeline:

1. **Query** — fetch form + metadata in one SQL query
2. **Index** — build metadata lookup by `column_name`
3. **Map sections** — each `question_block` → `FormSection`
4. **Map fields** — each `question` → `FormField` (skip if not in active metadata or unsupported type)
5. **Map logic** — `logic_groups` → `DependencyRule` with `ConditionOperator.EQ`
6. **Map validations** — `responseRequired` → `required=True`
7. **Register** — store in `FormRegistry`

### Component Diagram

```
                    ┌─────────────────────┐
                    │   DatabaseFormTool   │
                    │   (AbstractTool)     │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
    ┌─────────────┐  ┌───────────────┐  ┌──────────────┐
    │   asyncdb   │  │ FieldTypeMap  │  │ FormRegistry │
    │ (PostgreSQL)│  │ (DB→FieldType)│  │  (storage)   │
    └──────┬──────┘  └───────────────┘  └──────────────┘
           │
           ▼
  ┌──────────────────┐
  │ networkninja.    │
  │ forms +          │
  │ form_metadata    │
  └──────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractTool` | extends | `DatabaseFormTool` inherits tool interface |
| `FormRegistry` | uses | Register generated `FormSchema` for later retrieval |
| `FormSchema` / `FormSection` / `FormField` | uses | Build form structure from DB data |
| `DependencyRule` / `FieldCondition` / `ConditionOperator` | uses | Translate conditional logic |
| `FieldOption` | uses | Build options for multi-select fields from embedded data |
| `parrot.conf.default_dsn` | depends on | PostgreSQL connection string |
| `asyncdb.AsyncDB` | depends on | Async database driver |
| `form_server.py` example | extends | Add DB loading UI + API endpoint |

### Data Models

```python
class DatabaseFormInput(BaseModel):
    """Input schema for DatabaseFormTool."""
    formid: int = Field(..., description="Form ID from networkninja.forms")
    orgid: int = Field(..., description="Organization/tenant ID")
    persist: bool = Field(default=False, description="Persist to storage backend")
```

### DB Field Type → FieldType Mapping

| DB `data_type` | `FieldType` | `read_only` | `meta` |
|---|---|---|---|
| `FIELD_TEXT` | `text` | `False` | — |
| `FIELD_TEXTAREA` | `text_area` | `False` | — |
| `FIELD_INTEGER` | `integer` | `False` | — |
| `FIELD_FLOAT2` | `number` | `False` | — |
| `FIELD_YES_NO` | `boolean` | `False` | — |
| `FIELD_MULTISELECT` | `multi_select` | `False` | — |
| `FIELD_IMAGE_UPLOAD_MULTIPLE` | `file` | `False` | `{"accept": "image/*", "multiple": true}` |
| `FIELD_DISPLAY_TEXT` | `text` | `True` | `{"render_as": "display_text"}` |
| `FIELD_DISPLAY_IMAGE` | `image` | `True` | `{"render_as": "display_image"}` |
| `FIELD_SIGNATURE_CAPTURE` | *(skipped)* | — | Unsupported |

### Conditional Logic Translation

**DB structure** (per question):
```
logic_groups: [
  {
    logic_group_id: int,
    conditions: [
      {condition_logic: "EQUALS", condition_comparison_value: str,
       condition_question_reference_id: int, condition_option_id: int|null}
    ]
  }
]
```

**FormSchema mapping:**
- Each `condition` → `FieldCondition(field_id="field_{ref_column_name}", operator=EQ, value=condition_comparison_value)`
- Multiple conditions within one `logic_group` → `logic="or"` (any condition matches)
- Multiple `logic_groups` on one question → `logic="and"` (all groups must match)
- All dependency rules use `effect="show"`
- `condition_question_reference_id` is a `question_id` — must resolve to the referenced question's `column_name` to build the `field_id`

### New Public Interfaces

```python
class DatabaseFormTool(AbstractTool):
    """Load a form definition from PostgreSQL into a FormSchema.

    Args:
        registry: FormRegistry to store the generated form.
        dsn: PostgreSQL DSN. Defaults to parrot.conf.default_dsn.
    """

    async def _execute(
        self, formid: int, orgid: int, persist: bool = False
    ) -> ToolResult:
        """Query DB, transform to FormSchema, register, return."""
        ...
```

---

## 3. Module Breakdown

### Module 1: DatabaseFormTool

- **Path**: `packages/ai-parrot/src/parrot/forms/tools/database_form.py`
- **Responsibility**:
  - Accept `formid` + `orgid` input
  - Execute parameterized SQL query via `asyncdb`
  - Parse `question_blocks` JSON and `metadata` JSONB
  - Build metadata index (`column_name` → type info)
  - Build `question_id` → `column_name` reverse index (for conditional logic resolution)
  - Map each `question_block` to `FormSection`
  - Map each `question` to `FormField` (with type mapping, validation, conditional logic)
  - Skip questions not in active metadata or with unsupported types
  - Register in `FormRegistry`
  - Return `FormSchema` in `ToolResult.metadata`
- **Depends on**: `AbstractTool`, `FormSchema`, `FormRegistry`, `asyncdb`, `parrot.conf`

### Module 2: Package Exports

- **Path**: `packages/ai-parrot/src/parrot/forms/tools/__init__.py` and `packages/ai-parrot/src/parrot/forms/__init__.py`
- **Responsibility**: Export `DatabaseFormTool` from the forms package
- **Depends on**: Module 1

### Module 3: Example UI Integration

- **Path**: `examples/forms/form_server.py`
- **Responsibility**:
  - Add a "Load from Database" section to the index page with `formid` and `orgid` input fields
  - Add `POST /api/forms/from-db` endpoint that calls `DatabaseFormTool`
  - Redirect to the rendered form after loading
- **Depends on**: Module 1, Module 2

### Module 4: Unit & Integration Tests

- **Path**: `tests/forms/test_database_form.py`
- **Responsibility**:
  - Unit tests for type mapping, conditional logic translation, validation mapping
  - Integration test with mock DB result → full `FormSchema` generation
  - Edge case tests (empty form, unsupported types, missing metadata, malformed JSON)
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_field_type_mapping` | Module 1 | Each DB `data_type` maps to correct `FieldType` |
| `test_unsupported_type_skipped` | Module 1 | `FIELD_SIGNATURE_CAPTURE` fields are omitted |
| `test_display_text_readonly` | Module 1 | `FIELD_DISPLAY_TEXT` → `text` with `read_only=True` + meta |
| `test_display_image_readonly` | Module 1 | `FIELD_DISPLAY_IMAGE` → `image` with `read_only=True` + meta |
| `test_file_upload_meta` | Module 1 | `FIELD_IMAGE_UPLOAD_MULTIPLE` → `file` with accept/multiple meta |
| `test_required_validation` | Module 1 | `responseRequired` validation → `required=True` |
| `test_conditional_logic_single` | Module 1 | Single condition → `DependencyRule` with EQ operator |
| `test_conditional_logic_multi_conditions` | Module 1 | Multiple conditions in one group → `logic="or"` |
| `test_conditional_logic_multi_groups` | Module 1 | Multiple logic groups → `logic="and"` |
| `test_question_not_in_metadata_skipped` | Module 1 | Question with inactive/missing metadata is omitted |
| `test_question_blocks_to_sections` | Module 1 | Each question block → separate `FormSection` |
| `test_form_header_mapping` | Module 1 | `form_name` → title, `formid` → form_id |
| `test_question_id_to_field_id_resolution` | Module 1 | Conditional refs resolve `question_id` → `column_name` → `field_id` |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_form_from_mock_db_result` | Mock a complete DB result (header + question_blocks + metadata), verify full FormSchema with sections, fields, conditionals, and validations |
| `test_form_not_found` | Empty DB result → error ToolResult |
| `test_malformed_json` | Invalid `question_blocks` JSON → error ToolResult |
| `test_registry_registration` | Generated form is retrievable from FormRegistry |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_db_row():
    """Minimal form DB result with 2 question blocks, mixed field types, and conditional logic."""
    return {
        "formid": 4,
        "form_name": "Assembly Checklist",
        "description": "Daily assembly report",
        "client_id": 1,
        "client_name": "TestClient",
        "orgid": 71,
        "question_blocks": json.dumps([
            {
                "question_block_id": 1,
                "question_block_type": "simple",
                "questions": [
                    {
                        "question_id": 84,
                        "question_column_name": 8550,
                        "question_description": "Manager name",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}]
                    },
                    {
                        "question_id": 85,
                        "question_column_name": 8551,
                        "question_description": "Area ready?",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}]
                    },
                    {
                        "question_id": 86,
                        "question_column_name": 8552,
                        "question_description": "Time to get ready",
                        "logic_groups": [{"logic_group_id": 1, "conditions": [
                            {"condition_logic": "EQUALS", "condition_comparison_value": "0",
                             "condition_question_reference_id": 85, "condition_option_id": None}
                        ]}],
                        "validations": [{"validation_type": "responseRequired"}]
                    }
                ]
            }
        ]),
        "metadata": [
            {"column_id": 84, "column_name": "8550", "data_type": "FIELD_TEXT", "description": "Manager name"},
            {"column_id": 85, "column_name": "8551", "data_type": "FIELD_YES_NO", "description": "Area ready?"},
            {"column_id": 86, "column_name": "8552", "data_type": "FIELD_FLOAT2", "description": "Time to get ready"},
        ]
    }

@pytest.fixture
def sample_metadata_with_unsupported():
    """Metadata that includes an unsupported type (FIELD_SIGNATURE_CAPTURE)."""
    return [
        {"column_id": 272, "column_name": "8740", "data_type": "FIELD_SIGNATURE_CAPTURE", "description": "Signature"},
        {"column_id": 84, "column_name": "8550", "data_type": "FIELD_TEXT", "description": "Name"},
    ]
```

---

## 5. Acceptance Criteria

- [x] `DatabaseFormTool` loads a form by `formid` + `orgid` and returns a valid `FormSchema`
- [x] All supported DB field types map correctly to `FieldType` values
- [x] Unsupported field types (`FIELD_SIGNATURE_CAPTURE`) are silently skipped with a log warning
- [x] Display-only fields (`FIELD_DISPLAY_TEXT`, `FIELD_DISPLAY_IMAGE`) render as `read_only=True` with `meta.render_as`
- [x] `FIELD_IMAGE_UPLOAD_MULTIPLE` maps to `file` with `meta={"accept": "image/*", "multiple": true}`
- [x] Each `question_block` becomes a separate `FormSection`
- [x] Questions not present in active metadata are skipped
- [x] `responseRequired` validation maps to `required=True`
- [x] `logic_groups` translate to `DependencyRule` with `ConditionOperator.EQ` and `effect="show"`
- [x] Multiple conditions in one logic group use `logic="or"`
- [x] Multiple logic groups on one question use `logic="and"`
- [x] `condition_question_reference_id` resolves correctly through `question_id` → `column_name` → `field_id`
- [x] Generated `FormSchema` registers in `FormRegistry` and is retrievable
- [x] Error handling: form not found, malformed JSON, DB connection failure → descriptive error `ToolResult`
- [x] Example UI has formid/orgid inputs that load and render database forms
- [x] All unit and integration tests pass
- [x] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Inherit from `AbstractTool` following the pattern in `create_form.py`
- Use `Pydantic BaseModel` for `DatabaseFormInput` input schema
- Use `asyncdb.AsyncDB` with parameterized queries (prevent SQL injection)
- Use `self.logger` for all logging (warnings for skipped fields, info for form load)
- Return `ToolResult` with `FormSchema` in `metadata["form"]`

### SQL Query

```sql
SELECT
    f.formid, f.form_name, f.description, f.client_id, f.client_name, f.orgid,
    f.question_blocks,
    jsonb_agg(
        jsonb_build_object(
            'column_id', m.column_id,
            'column_name', m.column_name,
            'description', m.description,
            'data_type', m.data_type
        )
    ) AS metadata
FROM networkninja.forms f
JOIN networkninja.form_metadata m USING(formid)
WHERE f.formid = $1 AND f.orgid = $2 AND m.is_active = true
GROUP BY f.formid, f.form_name, f.description, f.client_id, f.client_name,
         f.orgid, f.question_blocks
```

### Key Implementation Details

- `question_column_name` in `question_blocks` is numeric (int) but `column_name` in metadata is a string — cast to string for comparison
- Build a `question_id → column_name` lookup from all questions across all blocks before processing conditional logic (a condition may reference a question in a different block)
- `FIELD_MULTISELECT` options are derived from `condition_comparison_value` / `condition_option_id` found across all conditions that reference that field — collect these to build `FieldOption` lists
- `field_id` format: `"field_{column_name}"` (e.g., `"field_8550"`)
- `section_id` format: `"block_{question_block_id}"` (e.g., `"block_11"`)
- `form_id` format: `"db-form-{formid}"` (e.g., `"db-form-4"`)

### Known Risks / Gotchas

- **Large forms**: Forms with 190+ fields will produce large `FormSchema` objects — this is expected and the renderer handles it, but rendering time may be noticeable
- **question_blocks is a JSON string**: The `question_blocks` column is stored as `text` containing JSON, not as native JSONB — must `json.loads()` it
- **Cross-block conditional references**: A question in block 2 may reference a question in block 1 — the `question_id → column_name` index must span all blocks
- **Missing options for multi-select**: Multi-select fields may not have explicit option lists in the DB. Options are embedded in conditional references. If no conditions reference a multi-select field, it will have no options — log a warning

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` | (existing) | Async PostgreSQL driver |
| `pydantic` | `>=2.0` | FormSchema model validation |

---

## 7. Open Questions

All open questions from brainstorm have been resolved:

- [x] Multi-select options: embedded in `condition_comparison_value` / `condition_option_id`
- [x] Caching: Uses `FormRegistry` (in-memory), Redis caching deferred to future enhancement
- [x] Multiple logic groups: AND logic (all groups must match)

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks sequential in one worktree
- **Rationale**: Small feature (3-4 files to create/modify), no parallelizable tasks, no shared file conflicts
- **Cross-feature dependencies**: None — FEAT-076 (Form Abstraction Layer) is already merged. No conflict with in-flight FEAT-077 (PBAC)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-03 | Jesus Lara | Initial draft from brainstorm |
