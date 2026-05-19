---
id: F003
query: Q003
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
---

## Core Form Models (224 lines)

**FormField**: field_id (str), field_type (FieldType — 52 types), label,
required, default, constraints, options, depends_on, children, meta.

**FormSchema**: form_id, version, title, sections (list[FormSection]),
submit (SubmitAction | None), meta, created_at, tenant.

**FormSection**: section_id, title, fields (list[SectionItem]).
- `iter_fields()` flattens through subsections.

**Key field_id structure**: Each field has a unique `field_id` within
the form. Partial saves will key data by `field_id` — this is the
natural identifier for individual answers.

**Nested fields**: GROUP fields have children, ARRAY fields have
item_template. Partial saves must handle nested keys (e.g.,
`"group_1.child_field"` or `"array_1[0].item_field"`).
