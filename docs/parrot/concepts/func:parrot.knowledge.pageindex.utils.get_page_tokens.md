---
type: Concept
title: get_page_tokens()
id: func:parrot.knowledge.pageindex.utils.get_page_tokens
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract page text and token counts from a PDF.
---

# get_page_tokens

```python
def get_page_tokens(pdf_path: str | BytesIO, model: str='gpt-4o', pdf_parser: str='PyMuPDF') -> list[tuple[str, int]]
```

Extract page text and token counts from a PDF.
