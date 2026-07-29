---
type: Wiki Entity
title: ArxivTool
id: class:parrot_tools.arxiv_tool.ArxivTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for searching academic papers on arXiv.org.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ArxivTool

Defined in [`parrot_tools.arxiv_tool`](../summaries/mod:parrot_tools.arxiv_tool.md).

```python
class ArxivTool(AbstractTool)
```

Tool for searching academic papers on arXiv.org.

This tool allows searching for papers by keywords, authors, categories, or any combination.
Returns comprehensive paper information including:
- Title
- Authors
- Publication date
- Abstract/Summary
- ArXiv ID
- PDF URL
- Categories

Example queries:
- "machine learning transformers"
- "quantum computing"
- "au:LeCun" (search by author)
- "cat:cs.AI" (search by category)

See https://info.arxiv.org/help/api/user-manual.html for advanced query syntax.
