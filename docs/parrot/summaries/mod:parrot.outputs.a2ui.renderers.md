---
type: Wiki Summary
title: parrot.outputs.a2ui.renderers
id: mod:parrot.outputs.a2ui.renderers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI renderer registry and contract (Module 4, core side).
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: defines
- concept: class:parrot.outputs.a2ui.renderers.RendererCapabilities
  rel: defines
- concept: func:parrot.outputs.a2ui.renderers.get_a2ui_renderer
  rel: defines
- concept: func:parrot.outputs.a2ui.renderers.register_a2ui_renderer
  rel: defines
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.renderers`

A2UI renderer registry and contract (Module 4, core side).

Core ships only the renderer *contract* — :class:`RendererCapabilities`,
:class:`AbstractA2UIRenderer`, and the register/resolve functions. ALL concrete
renderers live in ``ai-parrot-visualizations`` under the ``parrot.outputs.a2ui_renderers``
PEP 420 namespace, behind the ``a2ui`` / ``a2ui-pdf`` extras (spec G8).

Resolution copies the ``EmbeddingRegistry`` dispatch shape: look up the registry
first; if the name is unknown, ``importlib.import_module`` the satellite module
(which self-registers on import), then re-read the registry. A missing satellite
raises an actionable :class:`ImportError` naming the pip extra.

## Classes

- **`RendererCapabilities(BaseModel)`** — Declared capabilities of an A2UI renderer (spec §2 Data Models).
- **`AbstractA2UIRenderer(ABC)`** — Abstract base for every A2UI renderer (spec §2 New Public Interfaces).

## Functions

- `def register_a2ui_renderer(name: str, capabilities: RendererCapabilities) -> Callable[[type[AbstractA2UIRenderer]], type[AbstractA2UIRenderer]]` — Register an A2UI renderer class under ``name``.
- `def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]` — Resolve a renderer class by name, importing its satellite module if needed.
