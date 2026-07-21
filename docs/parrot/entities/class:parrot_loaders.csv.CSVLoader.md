---
type: Wiki Entity
title: CSVLoader
id: class:parrot_loaders.csv.CSVLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CSV Loader that creates one JSON Document per row using pandas.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# CSVLoader

Defined in [`parrot_loaders.csv`](../summaries/mod:parrot_loaders.csv.md).

```python
class CSVLoader(AbstractLoader)
```

CSV Loader that creates one JSON Document per row using pandas.

This loader reads CSV files with pandas and converts each row into a separate
Document with JSON content. Perfect for creating searchable knowledge bases
from tabular data where each row represents an entity or record.

Features:
- One document per CSV row
- JSON serialization of row data
- Configurable pandas read options
- Row indexing and metadata
- Header preservation
- Data type inference
- Error handling for malformed data

## Methods

- `def get_csv_info(self, path: Union[str, PurePath]) -> Dict[str, Any]` — Get information about a CSV file without loading all data.
- `def estimate_documents_count(self, path: Union[str, PurePath]) -> int` — Estimate how many documents will be created from a CSV file.
- `def get_configuration_summary(self) -> Dict[str, Any]` — Get current loader configuration.
