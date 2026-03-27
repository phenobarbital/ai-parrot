# TASK-440 — Odoo CRUD Convenience Methods

**Feature**: FEAT-054 — odoo-interface
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-374

---

## Objective

Add typed convenience methods to `OdooInterface` for all standard Odoo model operations: `search`, `search_read`, `read`, `create`, `write`, `unlink`, `search_count`, and `fields_get`. All delegate to `execute_kw`.

## File(s) to Modify

- `parrot/interfaces/odoointerface.py`

## Implementation Details

All methods delegate to `self.execute_kw(model, method_name, args, kwargs)`.

### 1. `search(model, domain=None, offset=0, limit=None, order=None) -> list[int]`
- Args: `[domain or []]`
- Kwargs: `{"offset": offset, "limit": limit, "order": order}` (omit None values)

### 2. `search_read(model, domain=None, fields=None, offset=0, limit=None, order=None) -> list[dict]`
- Args: `[domain or []]`
- Kwargs: `{"fields": fields, "offset": offset, "limit": limit, "order": order}` (omit None values)

### 3. `read(model, ids, fields=None) -> list[dict]`
- Args: `[ids]`
- Kwargs: `{"fields": fields}` if fields provided

### 4. `create(model, values) -> int | list[int]`
- If `values` is a dict: Args `[values]` → returns single int
- If `values` is a list: Args `[values]` → returns list[int]

### 5. `write(model, ids, values) -> bool`
- Args: `[ids, values]`

### 6. `unlink(model, ids) -> bool`
- Args: `[ids]`

### 7. `search_count(model, domain=None) -> int`
- Args: `[domain or []]`

### 8. `fields_get(model, attributes=None) -> dict`
- Args: `[]`
- Kwargs: `{"attributes": attributes}` if provided

### Helper
- `_clean_kwargs(**kw) -> dict`: Filter out None values from kwargs dict before passing to execute_kw.

## Acceptance Criteria

- [ ] All 8 convenience methods implemented with correct type hints.
- [ ] Each method constructs the correct `execute_kw` args/kwargs per Odoo JSON-RPC protocol.
- [ ] None-valued optional params are omitted from the kwargs dict.
- [ ] `create` handles both single dict and list of dicts.
- [ ] Google-style docstrings on every method.

## Tests

- `test_search` — verify args/kwargs passed to execute_kw.
- `test_search_read` — verify fields and domain forwarded correctly.
- `test_read` — verify ids and fields.
- `test_create_single` — single dict returns int.
- `test_create_batch` — list of dicts returns list[int].
- `test_write` — verify ids + values forwarded.
- `test_unlink` — verify ids forwarded.
- `test_search_count` — verify domain forwarded.
- `test_fields_get` — verify attributes forwarded.
- `test_none_kwargs_omitted` — optional params with None not sent.
