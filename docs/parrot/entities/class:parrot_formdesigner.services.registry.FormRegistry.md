---
type: Wiki Entity
title: FormRegistry
id: class:parrot_formdesigner.services.registry.FormRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Thread-safe, multi-tenant registry for FormSchema objects.
---

# FormRegistry

Defined in [`parrot_formdesigner.services.registry`](../summaries/mod:parrot_formdesigner.services.registry.md).

```python
class FormRegistry
```

Thread-safe, multi-tenant registry for FormSchema objects.

Supports in-memory registration scoped by tenant, optional persistence
via FormStorage, async event callbacks, and YAML directory loading via
YamlExtractor.

Internal state is ``dict[tenant, dict[form_id, FormSchema]]``.
Every public read/write method accepts a kwarg-only ``tenant=`` parameter
that resolves via: explicit kwarg > form.tenant (register paths) >
``default_tenant``.

Example::

    registry = FormRegistry()
    await registry.register(form_schema)                     # requires form.tenant
    form = await registry.get("my-form", tenant="navigator")

    # With persistence
    registry = FormRegistry(storage=PostgreSQLFormStorage(...))
    await registry.register(form_schema, persist=True)
    await registry.load_from_storage(tenant="navigator")

    # Cross-tenant admin pattern (explicit loop — no aggregation via tenant=None):
    all_forms: list[FormSchema] = []
    for t in await registry.list_tenants():
        all_forms.extend(await registry.list_forms(tenant=t))

## Methods

- `def default_tenant(self) -> str` — Tenant slug used when callers don't supply one explicitly.
- `async def register(self, form: FormSchema, *, persist: bool=False, overwrite: bool=True, tenant: str | None=None) -> None` — Register a form schema under a specific tenant.
- `def set_storage(self, storage: FormStorage) -> None` — Set the FormStorage backend for this registry.
- `def set_public_toggle_callback(self, callback: Callable[[str, bool], Awaitable[None]]) -> None` — Register a callback invoked when a form's ``is_public`` flag changes.
- `async def on_startup(self, app: 'web.Application') -> None` — aiohttp ``on_startup`` signal handler.
- `async def on_shutdown(self, app: 'web.Application') -> None` — aiohttp ``on_shutdown`` signal handler.
- `async def unregister(self, form_id: str, *, tenant: str | None=None) -> bool` — Unregister a form schema from a specific tenant.
- `async def clone_form(self, source_form_id: str, new_form_id: str, patch: dict[str, Any] | None=None, *, persist: bool=True, tenant: str | None=None) -> FormSchema` — Clone an existing form under a new ``form_id``.
- `async def get(self, form_id: str, *, tenant: str | None=None) -> FormSchema | None` — Get a form schema by ID within a specific tenant.
- `async def list_forms(self, *, tenant: str | None=None) -> list[FormSchema]` — List all registered form schemas for a specific tenant.
- `async def list_form_ids(self, *, tenant: str | None=None) -> list[str]` — List all registered form IDs for a specific tenant.
- `async def contains(self, form_id: str, *, tenant: str | None=None) -> bool` — Check if a form is registered under a specific tenant.
- `async def clear(self, *, tenant: str | None=None) -> None` — Clear all registered forms for a specific tenant only.
- `async def clear_all(self) -> None` — Drop every tenant's forms.
- `async def list_tenants(self) -> list[str]` — Return a sorted list of tenants that have at least one registered form.
- `async def load_from_directory(self, path: str | Path, *, recursive: bool=True, overwrite: bool=False, tenant: str | None=None) -> int` — Load YAML form definitions from a directory using YamlExtractor.
- `async def load_from_storage(self, *, tenant: str | None=None) -> int` — Load all persisted forms from storage into memory for a tenant.
- `def has_storage(self) -> bool` — Return True if a FormStorage backend is configured.
- `def storage(self) -> 'FormStorage | None'` — Return the configured FormStorage backend, or None.
- `def on_register(self, callback: Callable[[FormSchema], Awaitable[None]]) -> None` — Register a callback invoked when a form is registered.
- `def on_unregister(self, callback: Callable[[str, str], Awaitable[None]]) -> None` — Register a callback invoked when a form is unregistered.
