---
type: Wiki Entity
title: MSWordTool
id: class:parrot_tools.msword.MSWordTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Microsoft Word Document Generation Tool.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: extends
---

# MSWordTool

Defined in [`parrot_tools.msword`](../summaries/mod:parrot_tools.msword.md).

```python
class MSWordTool(AbstractDocumentTool)
```

Microsoft Word Document Generation Tool.

This tool converts text content (including Markdown and HTML) into professionally
formatted Word documents (.docx). It supports custom templates, styling, and
advanced document formatting features.

Features:
- Markdown to Word conversion with proper formatting
- HTML to Word conversion support
- Custom DOCX template support
- Jinja2 HTML template processing
- Configurable styling and page setup
- Table, list, and heading support
- Professional document formatting
