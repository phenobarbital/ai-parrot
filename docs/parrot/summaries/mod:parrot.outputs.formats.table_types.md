---
type: Wiki Summary
title: parrot.outputs.formats.table_types
id: mod:parrot.outputs.formats.table_types
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'FEAT-218: Deterministic dtype→vocabulary map + canonical value serialization.'
relates_to:
- concept: func:parrot.outputs.formats.table_types.base_column_types
  rel: defines
- concept: func:parrot.outputs.formats.table_types.canonical_records
  rel: defines
- concept: mod:parrot.tools.dataset_manager.tool
  rel: references
---

# `parrot.outputs.formats.table_types`

FEAT-218: Deterministic dtype→vocabulary map + canonical value serialization.

Provides two pure functions that the ``StructuredTableRenderer`` uses to build
the deterministic half of the structured-table schema:

- :func:`base_column_types` — maps ``DatasetManager.categorize_columns`` output
  onto the FEAT-218 storage vocabulary.
- :func:`canonical_records` — serializes DataFrame rows to plain dicts with
  type-safe, JSON-boundary-safe values (ISO-8601 UTC datetimes, big-ints-as-strings,
  NaN/None → None).

Neither function performs I/O or LLM calls; both are fully deterministic and
independently unit-testable.

## Functions

- `def base_column_types(df: pd.DataFrame) -> dict[str, str]` — Map DataFrame column dtypes to the FEAT-218 storage vocabulary.
- `def canonical_records(df: pd.DataFrame, row_limit: int=1000) -> tuple[list[dict], int, bool]` — Serialize DataFrame rows to canonical, JSON-boundary-safe dicts.
