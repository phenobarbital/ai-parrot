---
type: Wiki Entity
title: SemanticTextSplitter
id: class:parrot.loaders.splitters.semantic.SemanticTextSplitter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Sentence/paragraph-aware splitter backed by the Rust crate. Never
relates_to:
- concept: class:parrot.loaders.splitters.base.BaseTextSplitter
  rel: extends
---

# SemanticTextSplitter

Defined in [`parrot.loaders.splitters.semantic`](../summaries/mod:parrot.loaders.splitters.semantic.md).

```python
class SemanticTextSplitter(BaseTextSplitter)
```

Sentence/paragraph-aware splitter backed by the Rust crate. Never
produces mid-word cuts. Pass ``tokenizer=`` for token-based capacity.

## Methods

- `def split_text(self, text: str) -> List[str]` — Return chunk strings; never produces mid-word cuts.
- `def create_chunks(self, text: str, metadata: Optional[Dict[str, Any]]=None) -> List[TextChunk]` — Return TextChunk objects with char offsets and metadata.
