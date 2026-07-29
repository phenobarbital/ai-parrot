---
type: Wiki Entity
title: TemplateEngine
id: class:parrot.template.engine.TemplateEngine
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Async-only Jinja2 template engine with:'
---

# TemplateEngine

Defined in [`parrot.template.engine`](../summaries/mod:parrot.template.engine.md).

```python
class TemplateEngine
```

Async-only Jinja2 template engine with:
    - multiple directories
    - in-memory templates
    - pluggable extensions/filters/globals
    - optional bytecode cache

## Methods

- `def add_template_dir(self, path: PathLike) -> None` — Add a new filesystem directory to the search path at runtime.
- `def add_templates(self, templates: Mapping[str, str]) -> None` — Add/override in-memory templates.
- `def get_template(self, name: str)` — Get a compiled template by name (raises FileNotFoundError on miss).
- `async def render(self, name: str, params: Optional[Mapping[str, Any]]=None) -> str` — Async render of a template by name.
- `async def render_string(self, source: str, params: Optional[Mapping[str, Any]]=None) -> str` — Async render from a string (compiled via the current environment).
- `def add_filters(self, filters: Mapping[str, Any]) -> None` — Register additional filters (supports async filters too).
- `def add_globals(self, globals_: Mapping[str, Any]) -> None` — Register additional global variables/functions.
- `def compile_directory(self, target: PathLike, *, zip: Optional[str]='deflated') -> None` — Optionally precompile all templates from filesystem loaders into `target`.
