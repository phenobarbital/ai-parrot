---
type: Concept
title: render_markdown()
id: func:parrot_loaders.ocr.layout.render_markdown
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a :class:`LayoutResult` into a Markdown string.
---

# render_markdown

```python
def render_markdown(layout: LayoutResult) -> str
```

Convert a :class:`LayoutResult` into a Markdown string.

Rendering rules:

* **Headers** → ``## <text>``
* **Table lines** → rendered as a Markdown table with a separator row
  after the first row.
* **Regular lines** → plain text; consecutive non-table, non-header lines
  are joined within a paragraph (separated by spaces), and paragraphs are
  separated by ``\n\n``.

Args:
    layout: The layout result to render.

Returns:
    A Markdown-formatted string.
