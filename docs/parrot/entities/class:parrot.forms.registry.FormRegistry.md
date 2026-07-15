---
type: Wiki Entity
title: FormRegistry
id: class:parrot.forms.registry.FormRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Thread-safe registry for FormSchema objects.
---

# FormRegistry

Defined in [`parrot.forms.registry`](../summaries/mod:parrot.forms.registry.md).

```python
class FormRegistry
```

Thread-safe registry for FormSchema objects.

Supports in-memory registration, optional persistence via FormStorage,
async event callbacks, and YAML directory loading via YamlExtractor.

Example:
    registry = FormRegistry()
    await registry.register(form_schema)
    form = await registry.get("my-form")

    # With persistence
    registry = FormRegistry(storage=PostgreSQLFormStorage(...))
    await registry.register(form_schema, persist=True)
    await registry.load_from_storage()

## Methods

- `async def register(self, form: FormSchema, *, persist: bool=False, overwrite: bool=True) -> None` — Register a form schema.
- `async def on_startup(self, app: 'web.Application') -> None` — aiohttp startup signal handler.
- `async def on_shutdown(self, app: 'web.Application') -> None` — aiohttp shutdown signal handler.
- `async def unregister(self, form_id: str) -> bool` — Unregister a form schema.
- `async def get(self, form_id: str) -> FormSchema | None` — Get a form schema by ID.
- `async def list_forms(self) -> list[FormSchema]` — List all registered form schemas.
- `async def list_form_ids(self) -> list[str]` — List all registered form IDs.
- `async def contains(self, form_id: str) -> bool` — Check if a form is registered.
- `async def clear(self) -> None` — Clear all registered forms.
- `async def load_from_directory(self, path: str | Path, *, recursive: bool=True, overwrite: bool=False) -> int` — Load YAML form definitions from a directory using YamlExtractor.
- `async def load_from_storage(self) -> int` — Load all persisted forms from storage into memory.
- `def on_register(self, callback: Callable[[FormSchema], Awaitable[None]]) -> None` — Register a callback invoked when a form is registered.
- `def on_unregister(self, callback: Callable[[str], Awaitable[None]]) -> None` — Register a callback invoked when a form is unregistered.
