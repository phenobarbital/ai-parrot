---
id: F001
title: Current DatabaseFormTool — structure & networkninja-specific surface
source_queries: [Q001]
---

## Target path correction

User's brief says `parrot_designer/tools/database_form.py`. Actual canonical
location is **`packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`**
(package = `parrot-formdesigner`, namespace = `parrot_formdesigner`).

## What is generic vs. networkninja-specific

Citations refer to `packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`.

### Networkninja-specific (must move into `NetworkninjaFormService`)

- `_FORM_QUERY` (lines 43-58) — the SQL referencing `networkninja.forms` and
  `networkninja.form_metadata`.
- `_FIELD_TYPE_MAP` (lines 66-98) — DB `data_type` strings (`FIELD_TEXT`,
  `FIELD_YES_NO`, `FIELD_SIGNATURE_CAPTURE`, …) → `(FieldType, kwargs)`.
  These constants are NetworkNinja's, not generic.
- `_OPTION_FIELD_TYPES` (lines 101-105).
- `_fetch_form_row()` (lines 289-314) — runs the query via `asyncdb.AsyncDB("pg")`.
- `_build_form_schema()` (lines 320-367) — knows the row's column structure.
- `_build_metadata_index()` (373-393), `_build_question_id_index()` (395-422),
  `_collect_select_options()` (428-518), `_map_block_to_section()` (524-563),
  `_map_question_to_field()` (565-648), `_map_logic_groups()` (654-731).
- `_get_dsn()` (lines 179-201) — currently in the tool but only needed if the
  tool owns DB access. Should move with the service.

### Tool-level (stays in `DatabaseFormTool`)

- `name: str = "database_form"` and `description` (149-153).
- `args_schema = DatabaseFormInput` (154).
- Registry coupling: `await self._registry.register(form, persist=persist)`
  (line 240). The tool registers; the service does not need to know about
  the registry.
- Error handling + logging in `_execute()` (lines 207-283).

### Input model surface

`DatabaseFormInput` (lines 113-127):
- `formid: int` (≥1)
- `orgid: int` (≥1)
- `persist: bool = False`

These two ID fields are NetworkNinja's primary key shape. A service-agnostic
input will need a way to pass service-specific selectors.

## Constructor signature consumed by callers

```python
DatabaseFormTool(
    registry: FormRegistry,
    db: Any | None = None,
    dsn: str | None = None,
    **kwargs,
)
```
(lines 156-177). Changing this signature affects every caller (see F005).
