---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.resolver
id: mod:parrot.tools.dataset_manager.sources.resolver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Physical-Resource Resolver for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.resolver.PhysicalResources
  rel: defines
- concept: class:parrot.tools.dataset_manager.sources.resolver.ReadOnlyViolation
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.resolver.physical_tables
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.resolver.resolve_physical_resources
  rel: defines
- concept: mod:parrot.tools.dataset_manager.sources.dialects
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.memory
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.opaque
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
---

# `parrot.tools.dataset_manager.sources.resolver`

Physical-Resource Resolver for FEAT-228 Data-Plane Authorization.

Pure function module that maps any :class:`~parrot.tools.dataset_manager.sources.base.DataSource`
to the set of physical resources (driver + tables / source identifiers) it
will actually touch when executed.

This is the anti-alias-spoofing boundary: authorization decisions are made on
*what the source physically accesses*, not on the LLM-chosen dataset name.

Architecture (Spec §2, Module 1):
- SQL sources: sqlglot parses the query and extracts physical table references,
  excluding CTE aliases.  A read-only gate rejects DML/DDL.
- TableSource: trivially extracts ``driver:table`` from instance attributes.
- QuerySlugSource: returns empty resources (slug-level grants handled separately).
- InMemorySource: returns empty resources (no driver round-trip).
- Opaque sources (Mongo, Iceberg, Delta, Airtable, Smartsheet): delegates to
  :mod:`parrot.tools.dataset_manager.sources.opaque`.

Usage::

    from parrot.tools.dataset_manager.sources.resolver import (
        resolve_physical_resources, physical_tables,
        PhysicalResources, ReadOnlyViolation,
    )

    resources = resolve_physical_resources(my_sql_source)
    # resources.driver = "bigquery"
    # resources.tables = {"bigquery:schema.table"}

## Classes

- **`ReadOnlyViolation(Exception)`** — Raised when a SQL statement is not read-only (DML/DDL detected).
- **`PhysicalResources(BaseModel)`** — Resolved physical resources for a DataSource.

## Functions

- `def physical_tables(sql: str, dialect: str) -> set[str]` — Extract physical table references from a SQL query using sqlglot.
- `def resolve_physical_resources(source: 'DataSource') -> PhysicalResources` — Resolve a DataSource to the set of physical resources it will touch.
