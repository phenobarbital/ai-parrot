---
type: Wiki Summary
title: parrot.tools.dataset_manager.spatial.compiler
id: mod:parrot.tools.dataset_manager.spatial.compiler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SpatialCompiler — compile and execute spatial filter queries (FEAT-219).
relates_to:
- concept: class:parrot.tools.dataset_manager.spatial.compiler.CompiledQuery
  rel: defines
- concept: class:parrot.tools.dataset_manager.spatial.compiler.SpatialCompiler
  rel: defines
- concept: mod:parrot.tools.dataset_manager.sources.memory
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
---

# `parrot.tools.dataset_manager.spatial.compiler`

SpatialCompiler — compile and execute spatial filter queries (FEAT-219).

Two execution paths, selected by ``getattr(source, "driver", None)``:

1. **Engine push-down** (pg, bigquery): emits an ``ST_DWITHIN`` + ``ST_AsGeoJSON``
   SQL query using driver-specific dialect templates.  ``compile()`` is I/O-free
   and ``syrupy``-snapshotable.  ``execute()`` runs via AsyncDB.

2. **Pandas bbox fallback** (mysql, unknown, InMemorySource): derives a bounding
   box from ``(point, radius)``, pushes a BETWEEN predicate, fetches box survivors,
   then refines to the exact circle with vectorized haversine (numpy).

Design principles (FEAT-219 spec §2):
- ``compile()`` is deterministic and I/O-free — no DB calls.
- ``execute()`` is async and performs all I/O.
- ``geodesic`` is declared on the profile and verified at compile time; the true
  path (geodesic vs spherical-approx) is returned in ``CompiledQuery.geodesic``.
- Never route through ``DatasetEntry.materialize`` / Redis Parquet cache (spec G4).
- TASK-1437 resolved NO-GO for Ibis — two hand-written SQL dialect templates are used.

Classes:
    CompiledQuery: Immutable result of compile() — SQL + metadata, no I/O.
    SpatialCompiler: Stateless compiler + executor.

## Classes

- **`CompiledQuery`** — Immutable result of SpatialCompiler.compile().
- **`SpatialCompiler`** — Stateless spatial filter compiler and executor.
