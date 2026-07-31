---
type: Concept
title: csv_to_markdown()
id: func:parrot.tools.dataset_manager.csv_reader.csv_to_markdown
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a CSV file to a clean markdown table.
---

# csv_to_markdown

```python
def csv_to_markdown(path: Union[str, Path], max_rows: int=200, separator: Optional[str]=None, **kwargs) -> str
```

Convert a CSV file to a clean markdown table.

Args:
    path: Path to the CSV file.
    max_rows: Maximum rows to include (truncates with note).
    separator: Column separator. Auto-detected if None.
    **kwargs: Passed to pandas.read_csv().

Returns:
    Markdown string with table header and data.
