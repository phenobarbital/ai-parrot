---
type: Wiki Summary
title: parrot.tools.dataset_manager
id: mod:parrot.tools.dataset_manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DatasetManager subpackage.
relates_to:
- concept: mod:parrot.tools
  rel: references
---

# `parrot.tools.dataset_manager`

DatasetManager subpackage.

Provides:
- DatasetManager: A Toolkit and Data Catalog for PandasAgent
- DatasetEntry: Lifecycle wrapper around a DataSource
- DatasetInfo: Pydantic schema for dataset metadata exposed to LLM
- DataSource: Abstract base for all data source types
- CompositeDataSource / JoinSpec: Virtual JOIN datasets
- ComputedColumnDef: Post-materialization computed column definition
