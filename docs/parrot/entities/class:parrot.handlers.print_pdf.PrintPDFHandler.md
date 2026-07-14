---
type: Wiki Entity
title: PrintPDFHandler
id: class:parrot.handlers.print_pdf.PrintPDFHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Converts HTML to PDF and returns the PDF as a binary response.
---

# PrintPDFHandler

Defined in [`parrot.handlers.print_pdf`](../summaries/mod:parrot.handlers.print_pdf.md).

```python
class PrintPDFHandler(BaseView)
```

Converts HTML to PDF and returns the PDF as a binary response.

Endpoints:
    POST /api/v1/utilities/print2pdf

Accepts:
    - Content-Type: text/html — raw HTML body.
    - Content-Type: application/json — ``{"html": "...", "filename": "...", "disposition": "..."}``.

Returns:
    application/pdf binary with Content-Disposition header.

## Methods

- `def post_init(self, *args: Any, **kwargs: Any) -> None`
- `async def post(self) -> web.Response` — Accept HTML body and return a PDF binary response.
