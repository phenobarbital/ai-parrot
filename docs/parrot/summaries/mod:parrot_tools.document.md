---
type: Wiki Summary
title: parrot_tools.document
id: mod:parrot_tools.document
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AbstractDocumentTool - Base class for document generation tools.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: defines
- concept: class:parrot_tools.document.DocumentGenerationArgs
  rel: defines
- concept: class:parrot_tools.document.DocumentMetadata
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.document`

AbstractDocumentTool - Base class for document generation tools.

This extends AbstractTool with common functionality for document generators like:
- PowerPoint, Word, Excel, PDF tools
- Standard document output management
- File path validation and generation
- Async file operations
- Template management

## Classes

- **`DocumentGenerationArgs(BaseModel)`** — Base arguments schema for document generation tools.
- **`DocumentMetadata(BaseModel)`** — Metadata for generated documents.
- **`AbstractDocumentTool(AbstractTool)`** — Abstract base class for document generation tools.
