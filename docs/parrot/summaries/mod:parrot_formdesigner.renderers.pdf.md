---
type: Wiki Summary
title: parrot_formdesigner.renderers.pdf
id: mod:parrot_formdesigner.renderers.pdf
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PDF AcroForm fillable renderer for ``FormSchema`` (FEAT-152 Wave 2b).
relates_to:
- concept: class:parrot_formdesigner.renderers.pdf.PdfRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
---

# `parrot_formdesigner.renderers.pdf`

PDF AcroForm fillable renderer for ``FormSchema`` (FEAT-152 Wave 2b).

Uses ``reportlab.pdfgen.canvas.Canvas`` + ``canvas.acroForm`` to emit a
fillable PDF (AcroForm). Layout: vertical single-column with section
headers and label-above-input blocks.

Per Q4 (resolved): fields not natively expressible in AcroForm
(``FILE``, ``IMAGE``, ``ARRAY``, ``GROUP``) become flat textfield
placeholders with a form-level meta note listing them.

Output format: ``RenderedForm(content=<pdf-bytes>, content_type="application/pdf",
metadata={"unsupported_fields": [...]})``.

## Classes

- **`PdfRenderer(AbstractFormRenderer)`** — Render a ``FormSchema`` as a fillable PDF (AcroForm).
