---
type: Wiki Summary
title: parrot.tools.dataset_manager.tool
id: mod:parrot.tools.dataset_manager.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'DatasetManager: A Toolkit and Data Catalog for PandasAgent.'
relates_to:
- concept: class:parrot.tools.dataset_manager.tool.DatasetEntry
  rel: defines
- concept: class:parrot.tools.dataset_manager.tool.DatasetInfo
  rel: defines
- concept: class:parrot.tools.dataset_manager.tool.DatasetManager
  rel: defines
- concept: class:parrot.tools.dataset_manager.tool.FileEntry
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.auth.dataplane_guard
  rel: references
- concept: mod:parrot.auth.dataset_guard
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.auth.resolver
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.tools.dataset_manager.computed
  rel: references
- concept: mod:parrot.tools.dataset_manager.csv_reader
  rel: references
- concept: mod:parrot.tools.dataset_manager.excel_analyzer
  rel: references
- concept: mod:parrot.tools.dataset_manager.filtering.compiler
  rel: references
- concept: mod:parrot.tools.dataset_manager.filtering.contracts
  rel: references
- concept: mod:parrot.tools.dataset_manager.filtering.store
  rel: references
- concept: mod:parrot.tools.dataset_manager.filtering.values
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.airtable
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.authorizing
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.composite
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.deltatable
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.iceberg
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.memory
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.mongo
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.smartsheet
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.sql
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.compiler
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.dataset_manager.tool`

DatasetManager: A Toolkit and Data Catalog for PandasAgent.

Provides:
- Dataset catalog with add/remove/activate/deactivate
- Full metadata/EDA capabilities (replaces MetadataTool)
- Column type categorization and metrics guide generation
- Data quality checks (NaN detection, completeness)
- LLM-exposed tools for discovery, metadata retrieval, and management

## Classes

- **`DatasetInfo(BaseModel)`** — Schema for dataset information exposed to LLM.
- **`DatasetEntry`** — Lifecycle wrapper around a DataSource.
- **`FileEntry`** — A file loaded into DatasetManager (not a DataFrame).
- **`DatasetManager(AbstractToolkit)`** — Dataset Catalog and toolkit for managing DataFrames and Queries.
