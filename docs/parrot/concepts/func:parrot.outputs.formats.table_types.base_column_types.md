---
type: Concept
title: base_column_types()
id: func:parrot.outputs.formats.table_types.base_column_types
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Map DataFrame column dtypes to the FEAT-218 storage vocabulary.
---

# base_column_types

```python
def base_column_types(df: pd.DataFrame) -> dict[str, str]
```

Map DataFrame column dtypes to the FEAT-218 storage vocabulary.

Calls :meth:`DatasetManager.categorize_columns` (read-only) and maps its
coarse categories to the compact storage vocabulary used by
:class:`~parrot.models.outputs.TableColumn`:

- ``integer`` → ``"integer"``
- ``float`` → ``"number"``
- ``datetime`` → ``"datetime"``
- ``boolean`` → ``"boolean"``
- ``categorical`` / ``categorical_text`` / ``text`` → ``"string"``
- anything else → ``"any"``

Args:
    df: Source DataFrame.  The function is read-only — it never mutates
        the DataFrame or its columns.

Returns:
    A ``{column_name: storage_type}`` dict with one entry per column.
