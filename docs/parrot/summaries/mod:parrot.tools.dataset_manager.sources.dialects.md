---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.dialects
id: mod:parrot.tools.dataset_manager.sources.dialects
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Driver–Dialect Map for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: func:parrot.tools.dataset_manager.sources.dialects.driver_to_dialect
  rel: defines
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.dataset_manager.sources.dialects`

Driver–Dialect Map for FEAT-228 Data-Plane Authorization.

Maps ai-parrot driver aliases (as returned by ``normalize_driver``) to
sqlglot 30.9.0 dialect identifiers. Used by the physical-resource resolver
to parse SQL with the correct dialect so that table extraction is accurate
for each database backend.

Usage::

    from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

    dialect = driver_to_dialect("bigquery")   # returns "bigquery"
    dialect = driver_to_dialect("bq")          # returns "bigquery" (via normalize_driver)
    dialect = driver_to_dialect("unknown")     # returns None

## Functions

- `def driver_to_dialect(driver: str) -> Optional[str]` — Map an ai-parrot driver name to a sqlglot dialect identifier.
