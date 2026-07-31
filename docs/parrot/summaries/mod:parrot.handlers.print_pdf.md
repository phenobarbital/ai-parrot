---
type: Wiki Summary
title: parrot.handlers.print_pdf
id: mod:parrot.handlers.print_pdf
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PrintPDFHandler — Convert HTML to PDF via HTTP.
relates_to:
- concept: class:parrot.handlers.print_pdf.PrintPDFHandler
  rel: defines
- concept: mod:parrot._imports
  rel: references
---

# `parrot.handlers.print_pdf`

PrintPDFHandler — Convert HTML to PDF via HTTP.

Provides a simple utility endpoint that accepts an HTML body and returns
a PDF binary response using weasyprint.

## Classes

- **`PrintPDFHandler(BaseView)`** — Converts HTML to PDF and returns the PDF as a binary response.
