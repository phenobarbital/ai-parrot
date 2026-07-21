---
type: Wiki Entity
title: WordToMarkdownTool
id: class:parrot_tools.msword.WordToMarkdownTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for converting Word documents to Markdown format.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: extends
---

# WordToMarkdownTool

Defined in [`parrot_tools.msword`](../summaries/mod:parrot_tools.msword.md).

```python
class WordToMarkdownTool(AbstractDocumentTool)
```

Tool for converting Word documents to Markdown format.

This tool downloads Word documents from URLs and converts them to Markdown
format for easier processing by LLMs and other text analysis tools.

## Methods

- `async def convert_from_url(self, url: str, save_markdown: bool=False, **kwargs) -> Dict[str, Any]` — Convert Word document from URL to Markdown.
