---
type: Concept
title: canonical_records()
id: func:parrot.outputs.formats.table_types.canonical_records
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serialize DataFrame rows to canonical, JSON-boundary-safe dicts.
---

# canonical_records

```python
def canonical_records(df: pd.DataFrame, row_limit: int=1000) -> tuple[list[dict], int, bool]
```

Serialize DataFrame rows to canonical, JSON-boundary-safe dicts.

Applies ``row_limit`` truncation and serializes cell values so that the
resulting list can be safely round-tripped through JSON without precision
loss or type ambiguity:

- **datetime / Timestamp** → ISO-8601 UTC string (``"2026-01-01T00:00:00Z"``).
- **integer > 2^53** → ``str`` (avoids IEEE-754 precision loss in JSON).
- **NaN / pd.NaT / None** → Python ``None`` (serializes as JSON ``null``).
- **All other scalar types** → passed through as-is (int, float, bool, str).

Args:
    df: Source DataFrame.  The function is read-only.
    row_limit: Maximum number of rows to include in the output list.
        Defaults to 1000.

Returns:
    A three-tuple ``(rows, total_rows, truncated)`` where:

    - ``rows`` is a ``list[dict]`` of at most ``row_limit`` records.
    - ``total_rows`` is the original row count of ``df`` (before capping).
    - ``truncated`` is ``True`` when ``len(df) > row_limit``.
