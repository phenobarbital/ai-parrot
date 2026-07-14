---
type: Wiki Summary
title: parrot_tools.pdfprint
id: mod:parrot_tools.pdfprint
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Enhanced PDF Print Tool with improved Markdown table support.
relates_to:
- concept: class:parrot_tools.pdfprint.PDFPrintArgs
  rel: defines
- concept: class:parrot_tools.pdfprint.PDFPrintTool
  rel: defines
- concept: func:parrot_tools.pdfprint.count_tokens
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.pdfprint`

Enhanced PDF Print Tool with improved Markdown table support.

## Classes

- **`PDFPrintArgs(BaseModel)`** — Arguments schema for PDFPrintTool.
- **`PDFPrintTool(AbstractTool)`** — Enhanced PDF Print Tool with improved Markdown table support.

## Functions

- `def count_tokens(text: str, model: str='gpt-4') -> int` — Count tokens in text using tiktoken.
