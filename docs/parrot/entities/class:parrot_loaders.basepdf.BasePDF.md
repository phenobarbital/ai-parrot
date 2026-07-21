---
type: Wiki Entity
title: BasePDF
id: class:parrot_loaders.basepdf.BasePDF
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base Abstract loader for all PDF-file Loaders.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# BasePDF

Defined in [`parrot_loaders.basepdf`](../summaries/mod:parrot_loaders.basepdf.md).

```python
class BasePDF(AbstractLoader)
```

Base Abstract loader for all PDF-file Loaders.

## Methods

- `def build_default_meta(self, path: Union[str, PurePath], *, language: Optional[str]=None, title: Optional[str]=None, **kwargs) -> dict` — Return canonical metadata for a PDF source.
