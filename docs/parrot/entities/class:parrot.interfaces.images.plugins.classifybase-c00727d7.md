---
type: Wiki Entity
title: ClassifyBase
id: class:parrot.interfaces.images.plugins.classifybase.ClassifyBase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClassifyBase is an Abstract base class for performing image classification.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# ClassifyBase

Defined in [`parrot.interfaces.images.plugins.classifybase`](../summaries/mod:parrot.interfaces.images.plugins.classifybase.md).

```python
class ClassifyBase(ImagePlugin)
```

ClassifyBase is an Abstract base class for performing image classification.
Uses Gemini 2.5 multimodal model for image classification tasks.

## Methods

- `async def start(self, **kwargs)`
- `async def process_dataset(self, dataset: pd.DataFrame) -> pd.DataFrame` — Process the dataset with optional filtering.
- `def configure_filtering(self, filter_column: Optional[str]=None, filter_by: Optional[List[str]]=None) -> None` — Dynamically configure filtering parameters.
