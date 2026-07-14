---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.base
id: mod:parrot.outputs.a2ui.catalog.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI component catalog — contract types and registry internals (Module 2).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.base.BasicNode
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.CatalogError
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.CatalogValidationError
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.ComponentContractError
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.ComponentDefinition
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.ProducerOrigin
  rel: defines
- concept: class:parrot.outputs.a2ui.catalog.base.RegisteredComponent
  rel: defines
---

# `parrot.outputs.a2ui.catalog.base`

A2UI component catalog — contract types and registry internals (Module 2).

The catalog is the security allowlist at the heart of spec goal **G1**: only
components with a registered :class:`ComponentDefinition` may appear in an
envelope, so nothing unknown ever reaches a renderer. It also carries:

* the **mandatory lowering contract** (G4/D8) — every registrable component ships
  a pure, deterministic ``lower(component, data_model) -> BasicTree``, enforced at
  registration time (not by convention); and
* the ``requires_actions`` gate (G2/D10b) — LLM-produced envelopes may not contain
  action-bearing components in v1.

This module holds the low-level types and the registry dict. The public decorator
and validation entry points live in :mod:`parrot.outputs.a2ui.catalog` (``__init__``).

## Classes

- **`ProducerOrigin(str, Enum)`** — Origin of an envelope, controlling ``requires_actions`` enforcement.
- **`BasicNode(BaseModel)`** — A node in a lowered A2UI *Basic Catalog* tree.
- **`ComponentDefinition(BaseModel)`** — Metadata describing a registered catalog component (spec §2 Data Models).
- **`RegisteredComponent`** — A catalog entry: the component's definition plus its implementing class.
- **`CatalogError(Exception)`** — Base class for catalog errors.
- **`ComponentContractError(CatalogError)`** — Raised when a component class violates the registration contract.
- **`CatalogValidationError(CatalogError)`** — Raised when an envelope fails catalog allowlist / ``requires_actions`` checks.
