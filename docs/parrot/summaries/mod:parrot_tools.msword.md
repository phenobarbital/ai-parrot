---
type: Wiki Summary
title: parrot_tools.msword
id: mod:parrot_tools.msword
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MS Word Tool migrated to use AbstractDocumentTool framework.
relates_to:
- concept: class:parrot_tools.msword.MSWordArgs
  rel: defines
- concept: class:parrot_tools.msword.MSWordTool
  rel: defines
- concept: class:parrot_tools.msword.WordToMarkdownTool
  rel: defines
- concept: mod:parrot_tools.document
  rel: references
---

# `parrot_tools.msword`

MS Word Tool migrated to use AbstractDocumentTool framework.

## Classes

- **`MSWordArgs(DocumentGenerationArgs)`** — Arguments schema for MS Word Document generation.
- **`MSWordTool(AbstractDocumentTool)`** — Microsoft Word Document Generation Tool.
- **`WordToMarkdownTool(AbstractDocumentTool)`** — Tool for converting Word documents to Markdown format.
