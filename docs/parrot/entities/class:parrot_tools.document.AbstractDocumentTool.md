---
type: Wiki Entity
title: AbstractDocumentTool
id: class:parrot_tools.document.AbstractDocumentTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for document generation tools.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# AbstractDocumentTool

Defined in [`parrot_tools.document`](../summaries/mod:parrot_tools.document.md).

```python
class AbstractDocumentTool(AbstractTool)
```

Abstract base class for document generation tools.

This class provides common functionality for tools that generate documents
like PowerPoint presentations, Word documents, Excel spreadsheets, PDFs, etc.

Features:
- Standardized document output management
- File path validation and generation
- Async file operations with aiofiles
- Template management support
- Duplicate file handling
- Comprehensive metadata generation

## Methods

- `def get_supported_extensions(self) -> List[str]` — Get list of supported file extensions for this document type.
- `def get_available_templates(self) -> List[str]` — Get list of available template files.
- `async def template_exists(self, template_name: str) -> bool` — Check if a template file exists.
- `def get_document_info(self) -> Dict[str, Any]` — Get information about this document tool.
