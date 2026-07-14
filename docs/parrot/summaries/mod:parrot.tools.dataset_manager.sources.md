---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources
id: mod:parrot.tools.dataset_manager.sources
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource implementations for DatasetManager.
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: references
---

# `parrot.tools.dataset_manager.sources`

DataSource implementations for DatasetManager.

Available source types:
- DataSource: Abstract base class (ABC)
- InMemorySource: Wraps an already-loaded pd.DataFrame
- QuerySlugSource: Wraps QuerySource slug (lazy, no schema prefetch by default)
- MultiQuerySlugSource: Wraps multiple QuerySource slugs
- SQLQuerySource: User-provided SQL with {param} interpolation
- TableSource: Table reference with INFORMATION_SCHEMA schema prefetch
- AirtableSource: Airtable table or view
- SmartsheetSource: Smartsheet sheet
- CompositeDataSource: Virtual dataset that JOINs two or more existing datasets
- IcebergSource: Apache Iceberg table via asyncdb iceberg driver
  (requires asyncdb[iceberg] extra)
- MongoSource: MongoDB/DocumentDB collection via asyncdb mongo driver
  (requires asyncdb[mongo] extra)
- DeltaTableSource: Delta Lake table via asyncdb delta driver (local, S3, GCS)
  (requires asyncdb[delta] extra)
