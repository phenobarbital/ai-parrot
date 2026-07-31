---
type: Wiki Summary
title: parrot.outputs.a2ui.baking
id: mod:parrot.outputs.a2ui.baking
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI baking pass (Module 6).
relates_to:
- concept: class:parrot.outputs.a2ui.baking.BakeError
  rel: defines
- concept: func:parrot.outputs.a2ui.baking.bake_envelope
  rel: defines
- concept: func:parrot.outputs.a2ui.baking.persist_envelope
  rel: defines
- concept: mod:parrot.outputs.a2ui.models
  rel: references
- concept: mod:parrot.storage.models
  rel: references
---

# `parrot.outputs.a2ui.baking`

A2UI baking pass (Module 6).

Static surfaces (email, PDF, Teams card, baked HTML) cannot hold live data-model
bindings. The bake pass resolves EVERY ``{"$bind": "/pointer"}`` expression against
the envelope's data model, yielding a self-contained tree with zero live bindings.

**Core dependency hygiene (spec G8)**: this module imports ``jsonpointer`` *lazily*
inside :func:`_load_jsonpointer` — importing ``parrot.outputs.a2ui.baking`` therefore
works on a core-only install (zero new core deps). Full pointer *resolution* runs
only where ``jsonpointer`` is available (i.e. in the ``ai-parrot-visualizations[a2ui]``
satellite); calling it without the extra raises an actionable :class:`ImportError`.
Core-only installs can still *syntax-validate* bindings via Module 1's regex.

## Classes

- **`BakeError(Exception)`** — Raised when an envelope cannot be fully baked (e.g. unresolvable pointer).

## Functions

- `def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]` — Bake an envelope: resolve all bindings against its data model.
- `async def persist_envelope(envelope: CreateSurface, store: Any, *, user_id: str, agent_id: str, session_id: str, artifact_id: str | None=None, title: str='A2UI envelope') -> str` — Persist the source envelope via ``ArtifactStore`` and return its reference.
