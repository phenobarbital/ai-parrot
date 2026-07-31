---
type: Wiki Entity
title: PowerPointTool
id: class:parrot_tools.powerpoint.PowerPointTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: PowerPoint Presentation Generator Tool.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: extends
---

# PowerPointTool

Defined in [`parrot_tools.powerpoint`](../summaries/mod:parrot_tools.powerpoint.md).

```python
class PowerPointTool(AbstractDocumentTool)
```

PowerPoint Presentation Generator Tool.

This tool converts text content (including Markdown and HTML) into professionally
formatted PowerPoint presentations. It automatically splits content into slides
based on headings and supports custom templates, styling, and layout options.

Features:
- Automatic slide splitting based on headings (H1, H2, H3, etc.)
- Markdown to PowerPoint conversion with proper formatting
- HTML to PowerPoint conversion support
- Custom PowerPoint template support
- Jinja2 HTML template processing
- Configurable slide layouts and styling
- Table, list, and content formatting
- Professional presentation generation

Slide Splitting Logic:
- H1 (# Title) → Title slide (layout 0)
- H2 (## Section) → Content slide (layout 1)
- H3 (### Subsection) → Content slide (layout 1)
- Content between headings → Added to the slide

## Methods

- `def debug_content_parsing(self, content: str) -> Dict[str, Any]` — Debug method to see how content is being parsed.
