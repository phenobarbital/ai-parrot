---
type: Wiki Summary
title: parrot.tools.dataset_manager.csv_reader
id: mod:parrot.tools.dataset_manager.csv_reader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CSV-to-markdown converter for DatasetManager file loading.
relates_to:
- concept: func:parrot.tools.dataset_manager.csv_reader.csv_to_markdown
  rel: defines
- concept: func:parrot.tools.dataset_manager.csv_reader.csv_to_structural_summary
  rel: defines
---

# `parrot.tools.dataset_manager.csv_reader`

CSV-to-markdown converter for DatasetManager file loading.

## Functions

- `def csv_to_markdown(path: Union[str, Path], max_rows: int=200, separator: Optional[str]=None, **kwargs) -> str` — Convert a CSV file to a clean markdown table.
- `def csv_to_structural_summary(path: Union[str, Path]) -> str` — Return a brief structural summary of a CSV file.
