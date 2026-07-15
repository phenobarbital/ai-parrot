---
type: Wiki Entity
title: PageSnapshot
id: class:parrot_tools.scraping.page_snapshot.PageSnapshot
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compact page data for LLM prompt building.
---

# PageSnapshot

Defined in [`parrot_tools.scraping.page_snapshot`](../summaries/mod:parrot_tools.scraping.page_snapshot.md).

```python
class PageSnapshot
```

Compact page data for LLM prompt building.

Fields are plain strings so they interpolate cleanly into the
``PLAN_GENERATION_PROMPT`` template.

Args:
    title: Page ``<title>`` or ``og:title``.
    text_excerpt: First ~2000 chars of visible text.
    element_hints: Newline-separated list of notable elements with
        their tag, id, class, data-*, aria-*, and role attributes.
    structure: Pruned DOM outline (indented, repetition-collapsed)
        showing the repeating-block patterns the LLM should anchor
        its selectors on.
    links: Newline-separated ``text -> href`` pairs (up to 50).
