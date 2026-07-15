---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.opaque
id: mod:parrot.tools.dataset_manager.sources.opaque
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Opaque-Source Resolvers for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: func:parrot.tools.dataset_manager.sources.opaque.resolve_opaque_source
  rel: defines
- concept: mod:parrot.tools.dataset_manager.sources.airtable
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.deltatable
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.iceberg
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.mongo
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.resolver
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.smartsheet
  rel: references
---

# `parrot.tools.dataset_manager.sources.opaque`

Opaque-Source Resolvers for FEAT-228 Data-Plane Authorization.

Per-type resource identifier extraction for non-SQL DataSource subclasses
(Mongo, Iceberg, Delta, Airtable, Smartsheet).  Each source type has a
dedicated extraction strategy that returns a :class:`PhysicalResources` with
``source_type`` and ``source_id`` populated.

Resource identifier format (Spec §2):
    ``source:<type>:<identifier>``
    (e.g. ``source:mongo:finance_db.transactions``)

This module is imported lazily by the physical-resource resolver
(:mod:`parrot.tools.dataset_manager.sources.resolver`) for any source type
it does not handle directly.  All source imports are conditional (wrapped in
``try/except ImportError``) because Mongo, Iceberg, and Delta are optional
dependencies.

Usage::

    from parrot.tools.dataset_manager.sources.opaque import resolve_opaque_source

    resources = resolve_opaque_source(mongo_source)
    # resources.source_type = "mongo"
    # resources.source_id  = "finance_db.transactions"

## Functions

- `def resolve_opaque_source(source: 'DataSource') -> 'PhysicalResources'` — Extract resource identifiers from non-SQL DataSource subclasses.
