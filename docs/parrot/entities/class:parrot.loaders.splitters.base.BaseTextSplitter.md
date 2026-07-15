---
type: Wiki Entity
title: BaseTextSplitter
id: class:parrot.loaders.splitters.base.BaseTextSplitter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for all text splitters
---

# BaseTextSplitter

Defined in [`parrot.loaders.splitters.base`](../summaries/mod:parrot.loaders.splitters.base.md).

```python
class BaseTextSplitter(ABC)
```

Base class for all text splitters

## Methods

- `def split_text(self, text: str) -> List[str]` — Split text into chunks
- `def create_chunks(self, text: str, metadata: Optional[Dict[str, Any]]=None) -> List[TextChunk]` — Create TextChunk objects with metadata
