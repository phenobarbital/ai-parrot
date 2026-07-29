---
type: Wiki Entity
title: FormStorage
id: class:parrot.forms.registry.FormStorage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for form persistence backends.
---

# FormStorage

Defined in [`parrot.forms.registry`](../summaries/mod:parrot.forms.registry.md).

```python
class FormStorage(ABC)
```

Abstract base class for form persistence backends.

Implementations provide save/load/delete/list operations on persisted
FormSchema objects. Used by FormRegistry when persist=True.

Example implementation: PostgreSQLFormStorage (TASK-529).

## Methods

- `async def save(self, form: FormSchema, style: StyleSchema | None=None) -> str` — Persist a form schema.
- `async def load(self, form_id: str, version: str | None=None) -> FormSchema | None` — Load a form schema by ID.
- `async def delete(self, form_id: str) -> bool` — Delete a persisted form.
- `async def list_forms(self) -> list[dict[str, str]]` — List all persisted forms.
- `async def close(self) -> None` — Release any resources held by this storage backend.
