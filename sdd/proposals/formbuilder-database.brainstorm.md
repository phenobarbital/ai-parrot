# Brainstorm: Form Builder from Database Definition

**Date**: 2026-04-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot's Form Abstraction Layer (FEAT-076) currently creates forms via LLM natural language prompts (`CreateFormTool`). However, the NetworkNinja platform already has hundreds of form definitions stored in PostgreSQL (`networkninja.forms` + `networkninja.form_metadata`) with rich structure: question blocks, conditional logic groups, field validations, and per-column type metadata.

There is no way to import these existing database-defined forms into the FormSchema system. Users must manually recreate forms that already exist, losing the conditional logic, validation rules, and section structure. This affects developers and operators who need to expose existing NetworkNinja forms through AI-Parrot agents or web interfaces.

## Constraints & Requirements

- Must use `asyncdb` with the default PostgreSQL DSN (`from parrot.conf import default_dsn`)
- Must produce a valid `FormSchema` compatible with all existing renderers (HTML5, etc.)
- Must preserve question ordering from `question_blocks` JSON
- Must translate `logic_groups` into `DependencyRule` conditional visibility
- Must translate `validations` (e.g., `responseRequired`) into field `required` flags
- Must join `question_blocks` with `form_metadata` using `question_column_name` ↔ `column_name` — skip questions not present in active metadata
- Must handle unsupported `data_type` values gracefully (skip or mark as ignored)
- Must register the resulting `FormSchema` in `FormRegistry`
- Tool interface: receives `formid` (int) + `orgid` (int), returns `FormSchema`
- Each `question_block` maps to a separate `FormSection`

---

## Options Explored

### Option A: Direct Database Tool (DatabaseFormTool)

A standalone `AbstractTool` subclass that queries the database directly, parses the raw result, and programmatically builds a `FormSchema` using the existing Pydantic models. No LLM involvement — pure deterministic mapping.

The tool:
1. Accepts `formid` + `orgid` as input
2. Executes the SQL query via `asyncdb`
3. Parses `question_blocks` JSON for structure/ordering/logic
4. Joins with `metadata` JSONB for `data_type` mapping
5. Maps DB field types → `FieldType` enum
6. Maps `logic_groups` → `DependencyRule`
7. Maps `validations` → `required` + `FieldConstraints`
8. Constructs `FormSchema` with sections per question block
9. Registers in `FormRegistry`

✅ **Pros:**
- Deterministic — same input always produces same output
- Fast — single DB query, no LLM call needed
- Precise — exact mapping of conditional logic, no hallucination risk
- Testable — pure transformation logic, easy to unit test
- No additional API costs

❌ **Cons:**
- Requires maintaining a type mapping table (DB types → FieldType)
- Complex conditional logic translation needs careful implementation
- Cannot "interpret" ambiguous field descriptions like an LLM could

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | PostgreSQL connectivity | Already in project, uses `default_dsn` |
| `pydantic` | FormSchema model validation | Already in project |

🔗 **Existing Code to Reuse:**
- `parrot/forms/schema.py` — FormSchema, FormSection, FormField models
- `parrot/forms/types.py` — FieldType enum
- `parrot/forms/constraints.py` — DependencyRule, FieldCondition, ConditionOperator, FieldConstraints
- `parrot/forms/options.py` — FieldOption for multi-select fields
- `parrot/forms/registry.py` — FormRegistry for storage
- `parrot/forms/tools/create_form.py` — Pattern for tool structure (AbstractTool subclass)
- `parrot/conf` — `default_dsn` for database connection

---

### Option B: LLM-Assisted Database Tool (Hybrid)

Query the database for the raw data, then pass it to the LLM (like `CreateFormTool` does) to generate the FormSchema JSON. The LLM interprets the question descriptions and data types to produce a richer schema.

✅ **Pros:**
- LLM can infer better field labels, descriptions, and grouping
- Can leverage LLM to suggest additional validations based on question text
- Simpler mapping code — LLM handles the translation

❌ **Cons:**
- Non-deterministic — same input may produce different output
- Slow — requires LLM API call for each form load
- Expensive — LLM API cost per form generation
- Risk of losing conditional logic precision (LLM may hallucinate wrong dependencies)
- Forms with 190+ fields would produce very long prompts — token limits and cost
- Overkill — the DB already has all the structured information needed

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | PostgreSQL connectivity | Already in project |
| LLM client | Schema generation | Already in project, adds API cost |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus `parrot/forms/tools/create_form.py` for LLM generation pattern

---

### Option C: Database Extractor (Extractor Pattern)

Instead of a Tool, implement a `DatabaseFormExtractor` following the existing extractor pattern in `parrot/forms/extractors/` (alongside `PydanticExtractor`, `JsonSchemaExtractor`, `YamlExtractor`). The extractor would accept a DB result dict and return a `FormSchema`. A thin tool wrapper calls the extractor.

✅ **Pros:**
- Follows established extractor pattern in the codebase
- Separation of concerns — extraction logic reusable without tool wrapper
- Could be used programmatically without the tool interface
- Clean architecture

❌ **Cons:**
- Existing extractors work with static data (Pydantic models, JSON schemas, YAML files), not live DB queries — the pattern doesn't fit perfectly since this needs async DB access
- Two components to maintain (extractor + tool) instead of one
- The "extraction" here is more complex than existing extractors (conditional logic, cross-field references) — the pattern may be too simple
- Over-engineering for a single-source transformation

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | PostgreSQL connectivity | Already in project |
| `pydantic` | FormSchema model validation | Already in project |

🔗 **Existing Code to Reuse:**
- All of Option A, plus `parrot/forms/extractors/` for extractor base pattern

---

## Recommendation

**Option A** is recommended because:

- The database already contains fully structured data with explicit types, ordering, conditional logic, and validations. There is nothing for an LLM to "interpret" — this is a deterministic transformation.
- Forms can have 190+ fields with deep conditional trees. LLM-based generation (Option B) would be slow, expensive, and fragile at this scale.
- A single `DatabaseFormTool` keeps the implementation focused. The extractor pattern (Option C) adds architectural overhead for a transformation that is tightly coupled to a specific DB schema — it won't be reused for other sources.
- Deterministic output means the same `formid`/`orgid` always produces the exact same form — critical for reliability.

The tradeoff is maintaining a type-mapping table, but this is straightforward and easily testable.

---

## Feature Description

### User-Facing Behavior

From the web UI (form_server example), the user sees two numeric input fields: **Form ID** and **Org ID**. After entering values and clicking "Load from Database", the system fetches the form definition from PostgreSQL and renders it as a fully functional HTML5 form with:

- Sections corresponding to each question block
- All field types correctly mapped (text inputs, number inputs, yes/no toggles, multi-selects, file uploads, display-only info blocks)
- Conditional visibility working (e.g., bike repair questions only appear when "Returned Bikes/Repairs" is selected)
- Required field validation on submission
- Unsupported field types (e.g., `FIELD_SIGNATURE_CAPTURE`) gracefully omitted

The tool can also be invoked programmatically by an agent: `DatabaseFormTool.execute(formid=4, orgid=71)` returns the `FormSchema` object.

### Internal Behavior

**1. SQL Query Phase:**
- `DatabaseFormTool` receives `formid` + `orgid`
- Opens async connection via `AsyncDB('pg', dsn=default_dsn)`
- Executes parameterized query joining `networkninja.forms` with `networkninja.form_metadata`
- Returns a single row with form header fields + `question_blocks` (JSON string) + `metadata` (JSONB aggregate)

**2. Metadata Index Phase:**
- Parse `metadata` JSONB array into a lookup dict: `{column_name: {column_id, data_type, description}}`
- This dict is used to validate which questions are active and to determine field types

**3. Type Mapping Phase:**
- Map DB `data_type` values to `FieldType` enum:

| DB data_type | FieldType | Notes |
|---|---|---|
| `FIELD_TEXT` | `text` | |
| `FIELD_TEXTAREA` | `text_area` | |
| `FIELD_INTEGER` | `integer` | |
| `FIELD_FLOAT2` | `number` | |
| `FIELD_YES_NO` | `boolean` | |
| `FIELD_MULTISELECT` | `multi_select` | |
| `FIELD_IMAGE_UPLOAD_MULTIPLE` | `file` | `meta={"accept": "image/*", "multiple": true}` |
| `FIELD_DISPLAY_TEXT` | `text` | `read_only=True, meta={"render_as": "display_text"}` |
| `FIELD_DISPLAY_IMAGE` | `image` | `read_only=True, meta={"render_as": "display_image"}` |
| `FIELD_SIGNATURE_CAPTURE` | *(skipped)* | Unsupported — omit from form |

**4. Question Block → FormSection Phase:**
- Parse `question_blocks` JSON string into list of block dicts
- For each `question_block`:
  - Create a `FormSection(section_id=f"block_{question_block_id}")`
  - For each `question` in `questions`:
    - Look up `question_column_name` in metadata index — skip if not found (not active)
    - Determine `FieldType` from metadata `data_type` — skip if unsupported
    - Create `FormField` with `field_id=f"field_{column_name}"`
    - Set `label` from `question_description`
    - Set `required=True` if validations contain `responseRequired`

**5. Conditional Logic Translation Phase:**
- For each question with `logic_groups`:
  - Build a `DependencyRule` with `effect="show"`
  - For each condition in the logic group:
    - Map `condition_question_reference_id` → find the referenced question's `column_name` → `field_id`
    - Map `condition_logic: "EQUALS"` → `ConditionOperator.EQ`
    - Set `value` from `condition_comparison_value`
    - If `condition_option_id` is present, the value is from a multi-select option
  - When multiple conditions exist in one logic group, combine with `logic="or"`
  - When multiple logic groups exist on one question, combine with `logic="and"` (each group must be satisfied)

**6. Registration Phase:**
- Construct `FormSchema` with `form_id=f"db-form-{formid}"`, sections, title from `form_name`
- Register in `FormRegistry` with `persist=False` (in-memory only, re-fetchable from DB)
- Return `FormSchema` in `ToolResult.metadata`

### Edge Cases & Error Handling

- **Form not found**: Query returns empty result → return error `ToolResult` with message "Form {formid} not found for org {orgid}"
- **Empty question_blocks**: Form exists but has no questions → return empty `FormSchema` with zero sections
- **Unsupported data_type**: Skip the field, log a warning with `self.logger.warning()`
- **Question in blocks but not in metadata**: Skip (field is inactive) — no error
- **Circular conditional references**: Unlikely from DB data, but `FormValidator` will catch during registration
- **Malformed question_blocks JSON**: Catch `json.JSONDecodeError`, return error result
- **Database connection failure**: Catch connection errors, return descriptive error result
- **Duplicate column_names**: Use first occurrence (shouldn't happen with active metadata)
- **NULL description/form_name**: Use sensible defaults (empty string or "Untitled Form")

---

## Capabilities

### New Capabilities
- `database-form-builder`: Load form definitions from PostgreSQL database into FormSchema, translating question blocks, conditional logic, field types, and validations

### Modified Capabilities
- `form-server-example`: Add UI inputs for formid/orgid to load database-defined forms alongside the existing natural language form builder

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/forms/tools/` | extends | New `DatabaseFormTool` alongside `CreateFormTool` |
| `parrot/forms/__init__.py` | modifies | Export `DatabaseFormTool` |
| `parrot/forms/tools/__init__.py` | modifies | Export `DatabaseFormTool` |
| `examples/forms/form_server.py` | extends | Add DB form loading UI + API endpoint |
| `parrot/conf` | depends on | Uses `default_dsn` for DB connection |
| `asyncdb` | depends on | PostgreSQL async driver |
| `networkninja.forms` | depends on | External DB schema (read-only) |
| `networkninja.form_metadata` | depends on | External DB schema (read-only) |

No breaking changes. This is purely additive.

---

## Parallelism Assessment

- **Internal parallelism**: Mixed — the tool implementation (`DatabaseFormTool`) and the example UI changes are independent and could be developed in parallel
- **Cross-feature independence**: No conflicts with in-flight FEAT-077 (PBAC). Touches `parrot/forms/tools/` which is not modified by other features
- **Recommended isolation**: `per-spec` — total scope is small enough for sequential tasks in one worktree
- **Rationale**: Only 2-3 files to create/modify, the tool and UI integration are straightforward sequential work

---

## Open Questions

- [x] Should `FIELD_MULTISELECT` options be fetched from a separate DB table, or are the option values embedded in `condition_comparison_value` / `condition_option_id` fields? — *Owner: Jesus Lara*: are the options embedded in `condition_comparison_value` / `condition_option_id` fields
- [x] Should the tool support caching (avoid re-querying DB for the same formid/orgid within a session)? — *Owner: Jesus Lara*: Uses FormRegistry for caching, can add Redis caching to FormRegistry as well if necessary.
- [x] Should multiple `logic_groups` on a single question be combined with AND or OR? Current assumption is AND (all groups must match). — *Owner: Jesus Lara*: Current implementation uses AND (all groups must match).
