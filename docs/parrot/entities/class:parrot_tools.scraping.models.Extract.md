---
type: Wiki Entity
title: Extract
id: class:parrot_tools.scraping.models.Extract
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract data from the page using CSS selectors or XPath.
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# Extract

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class Extract(BrowserAction)
```

Extract data from the page using CSS selectors or XPath.

Two usage shapes:

1. Flat (single value):
   ``{action: "extract", selector: ".price", extract_type: "text",
     extract_name: "price"}`` — writes ``extracted_data["price"]``.

2. Row-of-fields (LLM-friendly): set ``fields`` to a dict of
   ``{column_name: FieldSpec}``. The parent ``selector`` picks row
   elements (use ``multiple: true`` for lists); each field selector
   runs RELATIVE to its row. Result: a list of dicts keyed by field
   names, written to ``extracted_data[extract_name or name]``.
