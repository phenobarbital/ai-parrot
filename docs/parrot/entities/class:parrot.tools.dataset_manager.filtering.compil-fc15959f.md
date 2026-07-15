---
type: Wiki Entity
title: FilterCompiler
id: class:parrot.tools.dataset_manager.filtering.compiler.FilterCompiler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Stateless compiler that translates FilterCondition to SQL or pandas.
---

# FilterCompiler

Defined in [`parrot.tools.dataset_manager.filtering.compiler`](../summaries/mod:parrot.tools.dataset_manager.filtering.compiler.md).

```python
class FilterCompiler
```

Stateless compiler that translates FilterCondition to SQL or pandas.

All methods are pure (no I/O, no state) so instances are reusable and
easily unit-testable.

SQL dialect notes:
- Column names are always double-quoted via ``_quote_column`` to prevent
  SQL injection through column name interpolation.
- Values are escaped with single-quoting (strings) or left as literals
  (numbers), matching the ``TableSource._build_filter_clause`` pattern.
- ``ne`` emits ``<>``; ``not_in`` emits ``NOT IN``.
- ``range`` emits ``BETWEEN … AND …``.

Raises:
    ValueError: When an unsupported operator is passed, when a column is
        not found in the DataFrame, or when a ``range`` value is malformed.

## Methods

- `def compile_where(self, column: str, condition: FilterCondition) -> Tuple[str, List[Any]]` — Translate a FilterCondition to a SQL WHERE fragment.
- `def compile_pandas(self, df: pd.DataFrame, column: str, condition: FilterCondition) -> pd.Series` — Translate a FilterCondition to a pandas boolean Series (mask).
