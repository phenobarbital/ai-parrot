---
type: Concept
title: extract_text()
id: func:parrot_tools.rss.fetcher.extract_text
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract the main readable text from an HTML page.
---

# extract_text

```python
def extract_text(html: str) -> str
```

Extract the main readable text from an HTML page.

Uses trafilatura when installed; otherwise falls back to a BeautifulSoup
text dump with script/style/noscript removed.

Args:
    html: Raw page HTML.

Returns:
    Extracted text, or '' when nothing could be extracted.
