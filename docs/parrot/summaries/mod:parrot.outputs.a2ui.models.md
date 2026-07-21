---
type: Wiki Summary
title: parrot.outputs.a2ui.models
id: mod:parrot.outputs.a2ui.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: A2UI v1.0 wire message models.
relates_to:
- concept: class:parrot.outputs.a2ui.models.A2UIMessageBase
  rel: defines
- concept: class:parrot.outputs.a2ui.models.Action
  rel: defines
- concept: class:parrot.outputs.a2ui.models.ActionResponse
  rel: defines
- concept: class:parrot.outputs.a2ui.models.CallFunction
  rel: defines
- concept: class:parrot.outputs.a2ui.models.Component
  rel: defines
- concept: class:parrot.outputs.a2ui.models.CreateSurface
  rel: defines
- concept: class:parrot.outputs.a2ui.models.UpdateComponents
  rel: defines
- concept: class:parrot.outputs.a2ui.models.UpdateDataModel
  rel: defines
- concept: func:parrot.outputs.a2ui.models.is_binding_expression
  rel: defines
- concept: func:parrot.outputs.a2ui.models.is_valid_pointer
  rel: defines
---

# `parrot.outputs.a2ui.models`

A2UI v1.0 wire message models.

This module ships the complete `A2UI v1.0 <https://a2ui.org/specification/v1.0-a2ui/>`_
message set as Pydantic v2 models exposed through a discriminated union.

Design invariants (spec FEAT-273):

* **Greenfield / one-way import rule (G8)** — nothing in this module imports from
  ``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Only Pydantic v2
  and the standard library are used.
* **``version`` is NOT owned here (G3)** — no model in this module declares,
  defaults, or validates the protocol ``version`` field. That field is the sole
  responsibility of :mod:`parrot.outputs.a2ui.serialization`. This keeps a future
  A2UI protocol fork absorbable in exactly one place.
* **Bindings are validated for *syntax* only** — data-model bindings embedded in
  component properties are checked with a light regex for JSON-Pointer shape.
  Full JSON Pointer *resolution* is deferred to the bake pass (Module 6) in the
  ``ai-parrot-visualizations`` satellite, which owns the ``jsonpointer`` dependency.

## Classes

- **`Component(BaseModel)`** — A single node in an A2UI component adjacency list.
- **`A2UIMessageBase(BaseModel)`** — Base for every A2UI v1.0 wire message.
- **`CreateSurface(A2UIMessageBase)`** — ``createSurface`` — create a UI surface, optionally with inline content.
- **`UpdateComponents(A2UIMessageBase)`** — ``updateComponents`` — replace/extend a surface's component adjacency list.
- **`UpdateDataModel(A2UIMessageBase)`** — ``updateDataModel`` — patch a surface's data model.
- **`Action(A2UIMessageBase)`** — ``action`` — a user-originated action from a component (schema only in v1).
- **`ActionResponse(A2UIMessageBase)`** — ``actionResponse`` — an agent's response to a prior ``action`` (schema only).
- **`CallFunction(A2UIMessageBase)`** — ``callFunction`` — an agent invokes a named client-side function (schema only).

## Functions

- `def is_valid_pointer(pointer: str) -> bool` — Return whether ``pointer`` is a syntactically well-formed JSON Pointer.
- `def is_binding_expression(value: Any) -> bool` — Return whether ``value`` is a data-model binding expression.
