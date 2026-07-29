---
type: Wiki Entity
title: DocumentConverterInterface
id: class:parrot.interfaces.doc_converter.DocumentConverterInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps Docling's DocumentConverter with async support and configurable options.
---

# DocumentConverterInterface

Defined in [`parrot.interfaces.doc_converter`](../summaries/mod:parrot.interfaces.doc_converter.md).

```python
class DocumentConverterInterface
```

Wraps Docling's DocumentConverter with async support and configurable options.

## Methods

- `async def convert(self, source: Union[str, Path], *, output_format: str='markdown', max_num_pages: Optional[int]=None, max_file_size: Optional[int]=None) -> Union[str, Dict[str, Any]]` — Convert a document source to the requested output format.
- `async def convert_to_markdown(self, source: Union[str, Path], **kwargs) -> str` — Convenience wrapper returning markdown.
- `async def convert_to_json(self, source: Union[str, Path], **kwargs) -> Dict[str, Any]` — Convenience wrapper returning a JSON-serializable dict.
