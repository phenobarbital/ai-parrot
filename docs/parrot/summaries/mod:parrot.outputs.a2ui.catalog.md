---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog
id: mod:parrot.outputs.a2ui.catalog
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI component catalog — public decorator, lookup, and envelope validation.
relates_to:
- concept: func:parrot.outputs.a2ui.catalog.catalog_instructions
  rel: defines
- concept: func:parrot.outputs.a2ui.catalog.get_component
  rel: defines
- concept: func:parrot.outputs.a2ui.catalog.list_components
  rel: defines
- concept: func:parrot.outputs.a2ui.catalog.register_component
  rel: defines
- concept: func:parrot.outputs.a2ui.catalog.unregister_component
  rel: defines
- concept: func:parrot.outputs.a2ui.catalog.validate_envelope
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog`

A2UI component catalog — public decorator, lookup, and envelope validation.

Registration pattern mirrors :func:`parrot.outputs.formats.register_renderer`
(module-level registry dict + decorator that inserts and returns the class), with
the added registration-time enforcement of the mandatory ``lower()`` contract.

A registrable component class MUST:

* implement a callable ``lower(self, component, data_model) -> BasicTree``
  (pure and deterministic — golden-file tested in Module 3); and
* optionally expose class attributes ``SCHEMA`` (dict) and ``INSTRUCTIONS`` (str),
  which the decorator folds into the component's :class:`ComponentDefinition`.

## Functions

- `def register_component(name: str, *, requires_actions: bool=False, catalog_id: str=DEFAULT_CATALOG_ID) -> Callable[[type], type]` — Register a catalog component under ``name``.
- `def unregister_component(name: str) -> None` — Remove a component from the catalog (primarily for test isolation).
- `def get_component(name: str) -> RegisteredComponent` — Return the registered component for ``name``.
- `def list_components() -> list[ComponentDefinition]` — Return the definitions of all registered components (name-sorted).
- `def catalog_instructions() -> str` — Aggregate every component's embedded ``instructions`` for the LLM producer.
- `def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin=ProducerOrigin.TOOL) -> None` — Validate an envelope against the catalog allowlist and the action gate.
