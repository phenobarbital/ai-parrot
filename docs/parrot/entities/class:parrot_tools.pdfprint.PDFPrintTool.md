---
type: Wiki Entity
title: PDFPrintTool
id: class:parrot_tools.pdfprint.PDFPrintTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Enhanced PDF Print Tool with improved Markdown table support.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# PDFPrintTool

Defined in [`parrot_tools.pdfprint`](../summaries/mod:parrot_tools.pdfprint.md).

```python
class PDFPrintTool(AbstractTool)
```

Enhanced PDF Print Tool with improved Markdown table support.

This tool processes both plain text and Markdown content, with special
attention to proper table rendering in PDF output.

## Methods

- `def execute_sync(self, text: str, file_prefix: str='document', template_name: Optional[str]=None, template_vars: Optional[Dict[str, Any]]=None, stylesheets: Optional[List[str]]=None, auto_detect_markdown: bool=True) -> Dict[str, Any]` — Execute PDF generation synchronously.
- `def get_available_templates(self) -> List[str]` — Get list of available HTML templates.
- `def get_available_stylesheets(self) -> List[str]` — Get list of available CSS stylesheets.
- `def preview_markdown(self, text: str) -> str` — Convert Markdown to HTML for preview purposes.
