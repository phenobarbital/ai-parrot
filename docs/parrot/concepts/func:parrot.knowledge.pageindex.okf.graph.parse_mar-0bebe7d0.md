---
type: Concept
title: parse_markdown_links()
id: func:parrot.knowledge.pageindex.okf.graph.parse_markdown_links
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract markdown hyperlink targets from body text.
---

# parse_markdown_links

```python
def parse_markdown_links(body: str) -> list[str]
```

Extract markdown hyperlink targets from body text.

Links inside fenced code blocks are skipped.  Leading slashes are
stripped from targets (bundle-relative links per OKF §5.1).

Args:
    body: Markdown body string.

Returns:
    List of link target strings (concept_id candidates), deduplicated
    and ordered by appearance.
