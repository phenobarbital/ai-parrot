---
type: Concept
title: strip_html_text()
id: func:parrot.utils.jsonld_extractors.strip_html_text
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render arbitrary text as clean plain text.
---

# strip_html_text

```python
def strip_html_text(text: Any) -> str
```

Render arbitrary text as clean plain text.

Replicates ``WebScrapingLoader._strip_html`` exactly:
1. HTML-unescape entities (``&amp;`` → ``&``, ``&nbsp;`` → space, …).
2. Strip HTML tags via BeautifulSoup so nested anchors/lists collapse
   to their visible text.
3. Collapse whitespace runs (including ``\xa0`` from ``&nbsp;``) to a
   single space and strip leading/trailing whitespace.

Args:
    text: Any value.  ``None`` returns ``""``; non-strings are coerced
        to ``str`` before processing.

Returns:
    Cleaned plain-text string.
