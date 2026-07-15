---
type: Wiki Entity
title: InteractiveCatalogRegistry
id: class:parrot.tools.interactive.catalog_registry.InteractiveCatalogRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Eager-loading registry of catalog libraries and scaffold templates.
---

# InteractiveCatalogRegistry

Defined in [`parrot.tools.interactive.catalog_registry`](../summaries/mod:parrot.tools.interactive.catalog_registry.md).

```python
class InteractiveCatalogRegistry
```

Eager-loading registry of catalog libraries and scaffold templates.

Args:
    catalog_dir: Root directory containing ``libraries/`` and ``templates/``.
        Defaults to the bundled :data:`CATALOG_DIR`.

## Methods

- `def load(self) -> 'InteractiveCatalogRegistry'` — Load (or reload) all libraries and templates from disk.
- `async def ensure_loaded_async(self) -> None` — Load the catalog in a thread pool executor to avoid blocking the event loop.
- `def get_library(self, name: str) -> LibraryEntry` — Return the library entry ``name`` or raise ``KeyError``.
- `def get_template(self, name: str) -> ScaffoldTemplate` — Return the scaffold template ``name`` or raise ``KeyError``.
- `def list_libraries(self) -> List[LibraryEntry]` — Return all loaded libraries, sorted by name.
- `def list_templates(self) -> List[ScaffoldTemplate]` — Return all loaded templates, sorted by name.
- `def render_prompt_index(self) -> str` — Render the static ``<interactive_catalog>`` prompt index.
