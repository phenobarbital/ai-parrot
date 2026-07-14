---
type: Wiki Entity
title: PdfRenderer
id: class:parrot_formdesigner.renderers.pdf.PdfRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render a ``FormSchema`` as a fillable PDF (AcroForm).
---

# PdfRenderer

Defined in [`parrot_formdesigner.renderers.pdf`](../summaries/mod:parrot_formdesigner.renderers.pdf.md).

```python
class PdfRenderer(AbstractFormRenderer)
```

Render a ``FormSchema`` as a fillable PDF (AcroForm).

Layout: single-column vertical, A4 portrait. Section headers in bold,
label above each input. ``style`` / ``prefilled`` / ``errors`` are
accepted (per the base contract) but only ``prefilled`` is used to
seed default values on textfields where supported.

The renderer logs warnings for unsupported field types
(``FILE``/``IMAGE``/``ARRAY``/``GROUP``) and includes them in
``RenderedForm.metadata["unsupported_fields"]``.

## Methods

- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render ``form`` as a fillable PDF.
