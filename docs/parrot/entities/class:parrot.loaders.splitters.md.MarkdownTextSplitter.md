---
type: Wiki Entity
title: MarkdownTextSplitter
id: class:parrot.loaders.splitters.md.MarkdownTextSplitter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Markdown-aware splitter backed by the Rust crate. Never cuts inside
relates_to:
- concept: class:parrot.loaders.splitters.base.BaseTextSplitter
  rel: extends
---

# MarkdownTextSplitter

Defined in [`parrot.loaders.splitters.md`](../summaries/mod:parrot.loaders.splitters.md.md).

```python
class MarkdownTextSplitter(BaseTextSplitter)
```

Markdown-aware splitter backed by the Rust crate. Never cuts inside
fenced code blocks, headers, or list items. Pass ``tokenizer=`` for
token-based capacity.

## Methods

- `def split_text(self, text: str) -> List[str]` — Return chunk strings; never breaks inside fenced code blocks.
- `def create_chunks(self, text: str, metadata: Optional[Dict[str, Any]]=None) -> List[TextChunk]` — Return TextChunk objects with char offsets and metadata.
